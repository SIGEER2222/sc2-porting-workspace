$ErrorActionPreference = "Stop"

function Get-CmreOverlayRoot {
    return (Join-Path (Split-Path -Parent $PSScriptRoot) "overlays\cmre-alenger")
}

function Read-CmreUtf8 {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { throw "Overlay input not found: $Path" }
    return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
}

function Write-CmreUtf8NoBom {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )
    [System.IO.File]::WriteAllText($Path, $Content, [System.Text.UTF8Encoding]::new($false))
}

function Assert-CmreGalaxyToken {
    param([Parameter(Mandatory = $true)][string]$Value, [Parameter(Mandatory = $true)][string]$Name)
    if ($Value -notmatch '^[A-Za-z0-9_]+$') {
        throw "$Name contains unsafe characters for Galaxy template substitution: $Value"
    }
}

function Expand-CmreTemplate {
    param(
        [Parameter(Mandatory = $true)][string]$TemplatePath,
        [Parameter(Mandatory = $true)][hashtable]$Values
    )
    $text = Read-CmreUtf8 -Path $TemplatePath
    foreach ($key in $Values.Keys) {
        $text = $text.Replace("{{$key}}", [string]$Values[$key])
    }
    if ($text -match '{{[A-Z0-9_]+}}') {
        throw "Unresolved placeholder in template $TemplatePath"
    }
    return $text
}

function Add-CmreLinesAfter {
    param(
        [Parameter(Mandatory = $true)][string]$Content,
        [Parameter(Mandatory = $true)][string]$Anchor,
        [Parameter(Mandatory = $true)][string[]]$Lines
    )
    if (-not $Content.Contains($Anchor)) { throw "Anchor not found: $Anchor" }
    $missing = @($Lines | Where-Object { $_ -ne "" -and -not $Content.Contains($_) })
    if ($missing.Count -eq 0) { return $Content }
    return $Content.Replace($Anchor, ($Anchor + [Environment]::NewLine + ($missing -join [Environment]::NewLine)))
}

function Add-CmreForwardProtos {
    <#
    .SYNOPSIS
        形态E / VIBE_GEN_009：在 invoke 层挂载点之前补齐 MapScript 本体函数的前置原型。

    .DESCRIPTION
        Galaxy 与 C 一样「先声明后使用」，include 是纯文本展开。overlay 把 invoke 层
        （LibVibeInvokeCommon 的 funcref 静态表 + LibVibeInvoke_NN 的 Call 适配器）挂在
        `include "LibVibeKernel"` 之后，也就是文件头部；而地图本体的函数原型区排在
        200+ 行、定义排在 500+ 行，全在挂载点**之后**。于是 invoke 层引用地图本体的
        gf_* / gt_*_Func / auto_gf_*_TriggerFunc 时符号尚未声明：

          - 取址 `return gf_Foo;`  => "解析返回时出错，可能在行尾缺失分号：';'"（VIBE_GEN_008）
          - 调用 `gf_Foo(a, b);`   => "参数无效，可能有不正确的变量名"（VIBE_GEN_009）

        两者都是编译错误 => SC2 **静默丢弃整个 MapScript** => runtime listener 永不就绪。
        2026-08-09 真机取证：亡者之夜 `LibVibeInvoke_08.galaxy (14)` 卡死在
        `auto_gf_AIBigTextMessage_TriggerFunc`，就是本函数缺席导致的。

        注意判据是「**挂载点之前**有没有原型」，不是「整个文件里有没有原型」——
        地图自带原型区也在挂载点之后，对 invoke 层一样太晚。重复原型（前插一份 +
        本体原型区一份）在 Galaxy 里合法，2026-08-08 真机 proto_test P0-A/P0-B 双 PASS。

        【勿改成「把 include 后移」】2026-08-08 真机二分实测 Galaxy include 存在位置
        硬阈值：line 76 PASS / 212 PASS / 2128 PASS / 3089 FAIL / 7802 FAIL，失败形态是
        join_game 阶段直接崩溃（4/4 复现）。include 位置必须保持在头部。
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Content,
        [Parameter(Mandatory = $true)][string]$Anchor
    )
    $marker = "VIBE_FORWARD_PROTOS"
    if ($Content.Contains("BEGIN $marker")) { return $Content }
    if (-not $Content.Contains($Anchor)) { throw "Anchor not found: $Anchor" }

    $nl = [Environment]::NewLine
    $mountOffset = $Content.IndexOf($Anchor)
    $head = $Content.Substring(0, $mountOffset)

    # MapScript 顶层（列 0 起）的原型 / 定义。Galaxy 生成的 MapScript 参数恒为单行。
    $protoRe = [regex]'(?m)^([A-Za-z_]\w*)[ \t]+(\w+)[ \t]*\(([^;{)]*)\)[ \t]*;'
    $defRe = [regex]'(?m)^([A-Za-z_]\w*)[ \t]+(\w+)[ \t]*\(([^){]*)\)[ \t]*\{'

    $have = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($m in $protoRe.Matches($head)) { [void]$have.Add($m.Groups[2].Value) }

    # 生命周期入口永不前置声明；控制流关键字会被列 0 的 `if (...) {` 误吞，必须排除。
    $skip = @('InitMap', 'InitLibs', 'InitGlobals', 'InitTriggers')
    $keywords = @('if', 'while', 'for', 'switch', 'else', 'do', 'return')
    $seen = New-Object 'System.Collections.Generic.HashSet[string]'
    $generated = New-Object 'System.Collections.Generic.List[string]'
    foreach ($m in $defRe.Matches($Content)) {
        $typeName = $m.Groups[1].Value
        $funcName = $m.Groups[2].Value
        $params = $m.Groups[3].Value.Trim()
        if ($keywords -contains $typeName) { continue }
        if ($skip -contains $funcName) { continue }
        if ($have.Contains($funcName)) { continue }
        if (-not $seen.Add($funcName)) { continue }
        $generated.Add("$typeName $funcName ($params);")
    }
    if ($generated.Count -eq 0) { return $Content }

    $block = @(
        "// ==== BEGIN $marker ====",
        "// 形态E / VIBE_GEN_009：invoke 层（Common funcref 表 + shard 适配器）引用地图本体",
        "// gf_*/gt_*_Func/auto_*_TriggerFunc，Galaxy 先声明后使用，必须在挂载点之前补原型。",
        "// 地图自带原型区排在挂载点之后、对 invoke 层太晚。重复原型合法（真机 proto_test 取证）。",
        "// 由 Add-CmreForwardProtos 生成，**勿手删**：删掉 = SC2 静默丢弃整个 MapScript。"
    ) + $generated.ToArray() + @("// ==== END $marker ====", "")
    return $Content.Replace($Anchor, (($block -join $nl) + $nl + $Anchor))
}

function Select-CmreExistingAnchor {
    param(
        [Parameter(Mandatory = $true)][string]$Content,
        [Parameter(Mandatory = $true)][string[]]$Candidates,
        [Parameter(Mandatory = $true)][string]$Name
    )
    foreach ($candidate in $Candidates) {
        if ($Content.Contains($candidate)) { return $candidate }
    }
    throw "$Name anchor not found; tried: $($Candidates -join ', ')"
}

function Add-CmreBlockAfter {
    param(
        [Parameter(Mandatory = $true)][string]$Content,
        [Parameter(Mandatory = $true)][string]$Anchor,
        [Parameter(Mandatory = $true)][string]$Marker,
        [Parameter(Mandatory = $true)][string]$Block
    )
    if ($Content.Contains($Marker)) { return $Content }
    if (-not $Content.Contains($Anchor)) { throw "Anchor not found: $Anchor" }
    return $Content.Replace($Anchor, ($Anchor + [Environment]::NewLine + $Block.TrimEnd()))
}

function Add-CmreBlockAfterInFunction {
    param(
        [Parameter(Mandatory = $true)][string]$Content,
        [Parameter(Mandatory = $true)][string]$FunctionAnchor,
        [Parameter(Mandatory = $true)][string]$Anchor,
        [Parameter(Mandatory = $true)][string]$Marker,
        [Parameter(Mandatory = $true)][string]$Block
    )
    if ($Content.Contains($Marker)) { return $Content }
    $functionIndex = $Content.IndexOf($FunctionAnchor, [System.StringComparison]::Ordinal)
    if ($functionIndex -lt 0) { throw "Function anchor not found: $FunctionAnchor" }
    $anchorIndex = $Content.IndexOf($Anchor, $functionIndex, [System.StringComparison]::Ordinal)
    if ($anchorIndex -lt 0) { throw "Function-local anchor not found: $FunctionAnchor -> $Anchor" }
    $insertIndex = $anchorIndex + $Anchor.Length
    return $Content.Substring(0, $insertIndex) + [Environment]::NewLine + $Block.TrimEnd() + $Content.Substring($insertIndex)
}

function Add-CmreBlockBefore {
    param(
        [Parameter(Mandatory = $true)][string]$Content,
        [Parameter(Mandatory = $true)][string]$Anchor,
        [Parameter(Mandatory = $true)][string]$Marker,
        [Parameter(Mandatory = $true)][string]$Block
    )
    if ($Content.Contains($Marker)) { return $Content }
    if (-not $Content.Contains($Anchor)) { throw "Anchor not found: $Anchor" }
    return $Content.Replace($Anchor, ($Block.TrimEnd() + [Environment]::NewLine + [Environment]::NewLine + $Anchor))
}

function Replace-CmreBlockBetweenMarkers {
    param(
        [Parameter(Mandatory = $true)][string]$Content,
        [Parameter(Mandatory = $true)][string]$StartMarker,
        [Parameter(Mandatory = $true)][string]$EndMarker,
        [Parameter(Mandatory = $true)][string]$Block,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $startIndex = $Content.IndexOf($StartMarker, [System.StringComparison]::Ordinal)
    if ($startIndex -lt 0) { throw "$Name start marker not found: $StartMarker" }
    $endSearchIndex = $startIndex + $StartMarker.Length
    $endIndex = $Content.IndexOf($EndMarker, $endSearchIndex, [System.StringComparison]::Ordinal)
    if ($endIndex -lt 0) { throw "$Name end marker not found: $EndMarker" }
    return $Content.Substring(0, $startIndex) + $Block.TrimEnd() +
        [Environment]::NewLine + [Environment]::NewLine + $Content.Substring($endIndex)
}

function Replace-CmreFirstRegex {
    param(
        [Parameter(Mandatory = $true)][string]$Content,
        [Parameter(Mandatory = $true)][string]$Pattern,
        [Parameter(Mandatory = $true)][string]$Replacement,
        [Parameter(Mandatory = $true)][string]$AlreadyMarker,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ($Content.Contains($AlreadyMarker)) { return $Content }
    if (-not [regex]::IsMatch($Content, $Pattern)) { throw "$Label anchor not found" }
    return [regex]::Replace($Content, $Pattern, $Replacement, 1)
}

function Copy-CmreOverlayFiles {
    param(
        [Parameter(Mandatory = $true)][object[]]$Files,
        [Parameter(Mandatory = $true)][string]$DestinationRoot
    )
    [System.IO.Directory]::CreateDirectory($DestinationRoot) | Out-Null
    foreach ($file in $Files) {
        if (-not (Test-Path -LiteralPath $file.Source)) { throw "Overlay source not found: $($file.Source)" }
        [System.IO.File]::Copy($file.Source, (Join-Path $DestinationRoot $file.Name), $true)
    }
}

function Initialize-CmreRuntimeListenerBank {
    $banksRoot = Join-Path $env:USERPROFILE "Documents\StarCraft II\Banks"
    $bankXml = '<?xml version="1.0" encoding="utf-8"?>' + [Environment]::NewLine + '<Bank version="1"><Section name="debug"/><Section name="ally"/></Bank>'
    $vibeBankXml = '<?xml version="1.0" encoding="utf-8"?>' + [Environment]::NewLine + '<Bank version="1"><Section name="index"/><Section name="request"/><Section name="response"/><Section name="ally"/><Section name="diag"/></Bank>'
    $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($bankXml)
    $vibeBytes = [System.Text.UTF8Encoding]::new($false).GetBytes($vibeBankXml)
    [System.IO.Directory]::CreateDirectory($banksRoot) | Out-Null
    foreach ($dir in @($banksRoot, (Join-Path $banksRoot "1"), (Join-Path $banksRoot "2"), (Join-Path $banksRoot "14"))) {
        [System.IO.Directory]::CreateDirectory($dir) | Out-Null
        $bankFile = Join-Path $dir "CMRERebornDebug.SC2Bank"
        if (-not (Test-Path -LiteralPath $bankFile)) {
            [System.IO.File]::WriteAllBytes($bankFile, $bytes)
        }
        $vibeBankFile = Join-Path $dir "GalaxyVibe.SC2Bank"
        if (-not (Test-Path -LiteralPath $vibeBankFile)) {
            [System.IO.File]::WriteAllBytes($vibeBankFile, $vibeBytes)
            continue
        }

        $vibeDocument = [System.Xml.XmlDocument]::new()
        $vibeDocument.PreserveWhitespace = $true
        try {
            $vibeDocument.Load($vibeBankFile)
        } catch {
            # A malformed GalaxyVibe bank prevents the launcher from reaching
            # the map. Recover only while no SC2-related process is running:
            # an active game may be writing the same Bank at this instant.
            $activeSc2 = @(Get-Process -Name "SC2_x64", "SC2", "SC2Switcher_x64", "SC2Switcher" -ErrorAction SilentlyContinue)
            if ($activeSc2.Count -gt 0) {
                $processes = ($activeSc2 | Sort-Object Id | ForEach-Object { "$($_.ProcessName):$($_.Id)" }) -join ", "
                throw "GalaxyVibe bank is malformed but will not be repaired while SC2 is active ($processes): $vibeBankFile"
            }

            # File.Replace keeps a timestamped backup in the same directory and
            # atomically publishes a validated replacement. Do not recurse into
            # author-hash directories beyond this launcher's explicit targets.
            $stamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssfffZ")
            $backupPath = "$vibeBankFile.invalid-$stamp-$([Guid]::NewGuid().ToString('N')).bak"
            $replacementPath = "$vibeBankFile.repair-$([Guid]::NewGuid().ToString('N')).tmp"
            try {
                [System.IO.File]::WriteAllBytes($replacementPath, $vibeBytes)
                $replacementDocument = [System.Xml.XmlDocument]::new()
                $replacementDocument.Load($replacementPath)
                [System.IO.File]::Replace($replacementPath, $vibeBankFile, $backupPath)
                Write-Host "[bank-recovery] quarantined malformed GalaxyVibe bank: $vibeBankFile -> $backupPath"
            } finally {
                if ([System.IO.File]::Exists($replacementPath)) {
                    [System.IO.File]::Delete($replacementPath)
                }
            }
            continue
        }

        # BankValueSetFrom* can update existing sections, but an empty bank
        # produced by an earlier probe is not consistently writable on the
        # direct-map path. Seed the typed Vibe sections before SC2 loads it.
        try {
            foreach ($sectionName in @("index", "request", "response", "ally", "diag")) {
                if (@($vibeDocument.Bank.Section | Where-Object { $_.name -eq $sectionName }).Count -eq 0) {
                    $section = $vibeDocument.CreateElement("Section")
                    $section.SetAttribute("name", $sectionName)
                    $vibeDocument.Bank.AppendChild($section) | Out-Null
                }
            }
            $vibeDocument.Save($vibeBankFile)
        } catch {
            throw "Could not initialize GalaxyVibe bank sections: $($_.Exception.Message)"
        }
    }
}

function Install-CmreNativeComputerCatalogOverlay {
    param(
        [Parameter(Mandatory = $true)][string]$Sc2Root
    )

    # CMRE overrides the shared BarracksTrain catalog and currently keeps only
    # the Tech Lab command. Restore the standard Marine command in the staged
    # CMRE mod so P2's native Computer can issue a real train order.
    $abilPath = Join-Path $Sc2Root "Mods\CMRE\CMRE_Core_Base.SC2Mod\Base.SC2Data\GameData\AbilData.xml"
    if (-not (Test-Path -LiteralPath $abilPath -PathType Leaf)) {
        throw "Native Computer catalog overlay source not found: $abilPath"
    }

    $document = [System.Xml.XmlDocument]::new()
    $document.PreserveWhitespace = $true
    $document.LoadXml((Read-CmreUtf8 -Path $abilPath))
    $ability = $document.SelectSingleNode("/Catalog/CAbilTrain[@id='BarracksTrain']")
    if ($null -eq $ability) {
        throw "Native Computer catalog overlay anchor not found: BarracksTrain"
    }

    $train1 = $ability.SelectSingleNode("./InfoArray[@index='Train1']")
    $changed = $false
    if ($null -eq $train1) {
        $train1 = $document.CreateElement("InfoArray")
        $train1.SetAttribute("index", "Train1")
        $train1.SetAttribute("Time", "25")
        $button = $document.CreateElement("Button")
        $button.SetAttribute("DefaultButtonFace", "Marine")
        $button.SetAttribute("State", "Available")
        $removedUnit = $document.CreateElement("Unit")
        $removedUnit.SetAttribute("index", "0")
        $removedUnit.SetAttribute("removed", "1")
        $unit = $document.CreateElement("Unit")
        $unit.SetAttribute("index", "0")
        $unit.SetAttribute("value", "Marine")
        [void]$train1.AppendChild($button)
        [void]$train1.AppendChild($removedUnit)
        [void]$train1.AppendChild($unit)
        $train2 = $ability.SelectSingleNode("./InfoArray[@index='Train2']")
        if ($null -ne $train2) {
            [void]$ability.InsertBefore($train1, $train2)
        } else {
            [void]$ability.AppendChild($train1)
        }
        $changed = $true
    } else {
        $unit = $train1.SelectSingleNode("./Unit")
        if ($null -ne $unit -and $unit.GetAttribute("value") -ne "Marine") {
            throw "Native Computer catalog overlay found non-Marine BarracksTrain/Train1: $($unit.GetAttribute('value'))"
        }
        if ($null -eq $unit) {
            $unit = $document.CreateElement("Unit")
            $unit.SetAttribute("index", "0")
            $unit.SetAttribute("value", "Marine")
            [void]$train1.AppendChild($unit)
            $changed = $true
        }
        if ($unit.GetAttribute("index") -ne "0") {
            $unit.SetAttribute("index", "0")
            $changed = $true
        }
        $removedUnit = $train1.SelectSingleNode("./Unit[@removed='1']")
        if ($null -eq $removedUnit) {
            $removedUnit = $document.CreateElement("Unit")
            $removedUnit.SetAttribute("index", "0")
            $removedUnit.SetAttribute("removed", "1")
            [void]$train1.InsertBefore($removedUnit, $unit)
            $changed = $true
        }
        if (-not $train1.HasAttribute("Time")) {
            $train1.SetAttribute("Time", "25")
            $changed = $true
        }
        $button = $train1.SelectSingleNode("./Button")
        if ($null -eq $button) {
            $button = $document.CreateElement("Button")
            [void]$train1.AppendChild($button)
            $changed = $true
        }
        if ($button.GetAttribute("DefaultButtonFace") -ne "Marine") {
            $button.SetAttribute("DefaultButtonFace", "Marine")
            $changed = $true
        }
        if ($button.GetAttribute("State") -ne "Available") {
            $button.SetAttribute("State", "Available")
            $changed = $true
        }
        if ($button.GetAttribute("Requirements") -ne "") {
            $button.SetAttribute("Requirements", "")
            $changed = $true
        }
    }

    if ($changed) {
        $settings = [System.Xml.XmlWriterSettings]::new()
        $settings.Encoding = [System.Text.UTF8Encoding]::new($false)
        $settings.Indent = $false
        $stream = [System.IO.MemoryStream]::new()
        $writer = [System.Xml.XmlWriter]::Create($stream, $settings)
        try {
            $document.Save($writer)
        } finally {
            $writer.Dispose()
        }
        [System.IO.File]::WriteAllBytes($abilPath, $stream.ToArray())
        $stream.Dispose()
        Write-Host "Native Computer catalog overlay: restored BarracksTrain/Train1 -> Marine"
    } else {
        Write-Host "Native Computer catalog overlay: BarracksTrain/Train1 -> Marine already present"
    }

    $verify = [System.Xml.XmlDocument]::new()
    $verify.LoadXml((Read-CmreUtf8 -Path $abilPath))
    $verifiedTrain1 = $verify.SelectSingleNode("/Catalog/CAbilTrain[@id='BarracksTrain']/InfoArray[@index='Train1']")
    if ($null -eq $verifiedTrain1) {
        throw "Native Computer catalog overlay verification failed: BarracksTrain/Train1 is missing"
    }
    $verifiedUnit = $verifiedTrain1.SelectSingleNode("./Unit[@value='Marine']")
    if ($null -eq $verifiedUnit -or $verifiedUnit.GetAttribute("value") -ne "Marine") {
        throw "Native Computer catalog overlay verification failed: BarracksTrain/Train1 is not Marine"
    }
}

function Install-CmreNativeComputerMapCatalogOverlay {
    param(
        [Parameter(Mandatory = $true)][string]$MapPath
    )

    # Keep the compatibility fix in the map adapter layer as well as the
    # staged CMRE mod. Map-local catalog data has the final load precedence and
    # avoids depending on the mod cache's merge order.
    $gameData = Join-Path $MapPath "Base.SC2Data\GameData"
    $abilPath = Join-Path $gameData "AbilData.xml"
    [System.IO.Directory]::CreateDirectory($gameData) | Out-Null

    $document = [System.Xml.XmlDocument]::new()
    $catalog = $document.CreateElement("Catalog")
    [void]$document.AppendChild($catalog)
    # CMRE's BarracksTrain is a partial override used by the commander
    # production cards. Do not inherit it here: its parent only retains a
    # Tech Lab command, and that partial catalog entry makes an otherwise
    # visible child command fail UnitOrderIsValid at runtime. Keep this
    # map-local Computer card self-contained and native-costed.
    $ability = $document.CreateElement("CAbilTrain")
    $ability.SetAttribute("id", "P2MarineTrain")
    $categories = $document.CreateElement("EditorCategories")
    $categories.SetAttribute("value", "Race:Terran,AbilityorEffectType:Structures")
    [void]$ability.AppendChild($categories)
    $queueFlag = $document.CreateElement("Flags")
    $queueFlag.SetAttribute("index", "UnitOrderQueue")
    $queueFlag.SetAttribute("value", "1")
    [void]$ability.AppendChild($queueFlag)
    $range = $document.CreateElement("Range")
    $range.SetAttribute("value", "5")
    [void]$ability.AppendChild($range)
    $info = $document.CreateElement("InfoArray")
    $info.SetAttribute("index", "Train1")
    $info.SetAttribute("Time", "25")
    $button = $document.CreateElement("Button")
    $button.SetAttribute("DefaultButtonFace", "Marine")
    $button.SetAttribute("State", "Available")
    $button.SetAttribute("Requirements", "")
    $unit = $document.CreateElement("Unit")
    $unit.SetAttribute("value", "Marine")
    [void]$info.AppendChild($button)
    [void]$info.AppendChild($unit)
    [void]$ability.AppendChild($info)
    [void]$catalog.AppendChild($ability)

    $settings = [System.Xml.XmlWriterSettings]::new()
    $settings.Encoding = [System.Text.UTF8Encoding]::new($false)
    $settings.Indent = $true
    $stream = [System.IO.MemoryStream]::new()
    $writer = [System.Xml.XmlWriter]::Create($stream, $settings)
    try {
        $document.Save($writer)
    } finally {
        $writer.Dispose()
    }
    [System.IO.File]::WriteAllBytes($abilPath, $stream.ToArray())
    $stream.Dispose()

    $unitPath = Join-Path $gameData "UnitData.xml"
    $unitDocument = [System.Xml.XmlDocument]::new()
    $unitDocument.PreserveWhitespace = $true
    if (Test-Path -LiteralPath $unitPath -PathType Leaf) {
        $unitDocument.LoadXml((Read-CmreUtf8 -Path $unitPath))
    } else {
        $unitCatalog = $unitDocument.CreateElement("Catalog")
        [void]$unitDocument.AppendChild($unitCatalog)
    }
    $unitCatalog = $unitDocument.SelectSingleNode("/Catalog")
    if ($null -eq $unitCatalog) {
        throw "Native Computer map catalog overlay could not find UnitData Catalog"
    }
    $barracksOverride = $unitCatalog.SelectSingleNode("./CUnit[@id='Barracks']")
    if ($null -eq $barracksOverride) {
        $barracksOverride = $unitDocument.CreateElement("CUnit")
        $barracksOverride.SetAttribute("id", "Barracks")
        [void]$unitCatalog.AppendChild($barracksOverride)
    }
    $nativeAbility = $barracksOverride.SelectSingleNode("./AbilArray[@Link='BarracksTrain']")
    if ($null -eq $nativeAbility) {
        $nativeAbility = $unitDocument.CreateElement("AbilArray")
        $nativeAbility.SetAttribute("Link", "BarracksTrain")
        [void]$barracksOverride.AppendChild($nativeAbility)
    }
    $producedMarine = $barracksOverride.SelectSingleNode("./TechTreeProducedUnitArray[@value='Marine']")
    if ($null -eq $producedMarine) {
        $producedMarine = $unitDocument.CreateElement("TechTreeProducedUnitArray")
        $producedMarine.SetAttribute("value", "Marine")
        [void]$barracksOverride.AppendChild($producedMarine)
    }
    $p2Ability = $barracksOverride.SelectSingleNode("./AbilArray[@Link='P2MarineTrain']")
    if ($null -eq $p2Ability) {
        $p2Ability = $unitDocument.CreateElement("AbilArray")
        $p2Ability.SetAttribute("Link", "P2MarineTrain")
        [void]$barracksOverride.AppendChild($p2Ability)
    }
    $cardLayout = $barracksOverride.SelectSingleNode("./CardLayouts[@index='0']")
    if ($null -eq $cardLayout) {
        $cardLayout = $unitDocument.CreateElement("CardLayouts")
        $cardLayout.SetAttribute("index", "0")
        [void]$barracksOverride.AppendChild($cardLayout)
    }
    $nativeMarineButton = $cardLayout.SelectSingleNode("./LayoutButtons[@AbilCmd='BarracksTrain,Train1']")
    if ($null -eq $nativeMarineButton) {
        $nativeMarineButton = $unitDocument.CreateElement("LayoutButtons")
        $nativeMarineButton.SetAttribute("Face", "Marine")
        $nativeMarineButton.SetAttribute("Type", "AbilCmd")
        $nativeMarineButton.SetAttribute("AbilCmd", "BarracksTrain,Train1")
        $nativeMarineButton.SetAttribute("Row", "0")
        $nativeMarineButton.SetAttribute("Column", "0")
        [void]$cardLayout.AppendChild($nativeMarineButton)
    }
    $marineButton = $cardLayout.SelectSingleNode("./LayoutButtons[@AbilCmd='P2MarineTrain,Train1']")
    if ($null -eq $marineButton) {
        $marineButton = $unitDocument.CreateElement("LayoutButtons")
        $marineButton.SetAttribute("Face", "Marine")
        $marineButton.SetAttribute("Type", "AbilCmd")
        $marineButton.SetAttribute("AbilCmd", "P2MarineTrain,Train1")
        $marineButton.SetAttribute("Row", "0")
        $marineButton.SetAttribute("Column", "0")
        [void]$cardLayout.AppendChild($marineButton)
    }
    $unitSettings = [System.Xml.XmlWriterSettings]::new()
    $unitSettings.Encoding = [System.Text.UTF8Encoding]::new($false)
    $unitSettings.Indent = $true
    $unitStream = [System.IO.MemoryStream]::new()
    $unitWriter = [System.Xml.XmlWriter]::Create($unitStream, $unitSettings)
    try {
        $unitDocument.Save($unitWriter)
    } finally {
        $unitWriter.Dispose()
    }
    [System.IO.File]::WriteAllBytes($unitPath, $unitStream.ToArray())
    $unitStream.Dispose()

    $verify = [System.Xml.XmlDocument]::new()
    $verify.LoadXml((Read-CmreUtf8 -Path $abilPath))
    $verified = $verify.SelectSingleNode("/Catalog/CAbilTrain[@id='P2MarineTrain']/InfoArray[@index='Train1']/Unit[@value='Marine']")
    if ($null -eq $verified -or $verified.GetAttribute("value") -ne "Marine") {
        throw "Native Computer map catalog overlay verification failed: P2MarineTrain/Train1 is not Marine"
    }
    $unitVerify = [System.Xml.XmlDocument]::new()
    $unitVerify.LoadXml((Read-CmreUtf8 -Path $unitPath))
    $unitLink = $unitVerify.SelectSingleNode("/Catalog/CUnit[@id='Barracks']/AbilArray[@Link='P2MarineTrain']")
    if ($null -eq $unitLink) {
        throw "Native Computer map catalog overlay verification failed: Barracks does not link P2MarineTrain"
    }
    $nativeLink = $unitVerify.SelectSingleNode("/Catalog/CUnit[@id='Barracks']/AbilArray[@Link='BarracksTrain']")
    if ($null -eq $nativeLink) {
        throw "Native Computer map catalog overlay verification failed: Barracks does not link BarracksTrain"
    }
    $producedVerify = $unitVerify.SelectSingleNode("/Catalog/CUnit[@id='Barracks']/TechTreeProducedUnitArray[@value='Marine']")
    if ($null -eq $producedVerify) {
        throw "Native Computer map catalog overlay verification failed: Barracks does not produce Marine"
    }
    $nativeButtonVerify = $unitVerify.SelectSingleNode("/Catalog/CUnit[@id='Barracks']/CardLayouts[@index='0']/LayoutButtons[@AbilCmd='BarracksTrain,Train1']")
    if ($null -eq $nativeButtonVerify) {
        throw "Native Computer map catalog overlay verification failed: Barracks does not expose native Marine card"
    }
    $buttonVerify = $unitVerify.SelectSingleNode("/Catalog/CUnit[@id='Barracks']/CardLayouts[@index='0']/LayoutButtons[@AbilCmd='P2MarineTrain,Train1']")
    if ($null -eq $buttonVerify) {
        throw "Native Computer map catalog overlay verification failed: Barracks does not expose P2MarineTrain card"
    }
    Write-Host "Native Computer map catalog overlay: staged P2MarineTrain/Train1 -> Marine"
}

function Assert-CmreCommanderSelectionRemoved {
    param([Parameter(Mandatory = $true)][string]$MapPath)
    $baseData = Join-Path $MapPath "Base.SC2Data"
    $paths = @(
        (Join-Path $baseData "LibCOOC.galaxy"),
        (Join-Path $MapPath "MapScript.galaxy")
    ) | Where-Object { Test-Path -LiteralPath $_ }
    $blockedTokens = @(
        'CommanderSelectionScreen',
        'libCMFE_gf_CMUIX_StartupApplySavedConfiguration'
    )
    $matches = @(
        foreach ($token in $blockedTokens) {
            $paths | Select-String -Pattern $token -SimpleMatch
        }
    )
    if ($matches.Count -gt 0) {
        $matchPaths = ($matches | ForEach-Object { $_.Path }) -join ", "
        throw "CMRE commander-selection code remains in staged map: $matchPaths"
    }
    $libPath = Join-Path $baseData "LibCOOC.galaxy"
    if (-not (Test-Path -LiteralPath $libPath) -or
        -not (Select-String -Path $libPath -Pattern 'CMRE_ON_DEMAND_PRESELECTED_COMMANDER_STARTUP' -SimpleMatch -Quiet)) {
        throw "CMRE preselected commander startup marker missing from staged map: $libPath"
    }
}

function Install-CmreStartupDebugMarkersOverlay {
    param([Parameter(Mandatory = $true)][string]$MapPath)

    $baseData = Join-Path $MapPath "Base.SC2Data"
    $libPath = Join-Path $baseData "LibCOOC.galaxy"
    $lib = Read-CmreUtf8 -Path $libPath
    $markerBodies = @{
        "void libCOOC_gf_LoadAlliedCommandersData (string lp_map, trigger lp_startTrigger) {" = "startup_load_allied"
        "void libCOOC_gf_CC_DevStartupBegin () {" = "startup_dev_begin"
        "void libCOOC_gf_CC_CustomStartupLaunch () {" = "startup_custom_launch"
        "void libCOOC_gf_CC_DevStartupFinish () {" = "startup_dev_finish"
    }
    foreach ($anchor in $markerBodies.Keys) {
        $key = $markerBodies[$anchor]
        $marker = "CMRE_ON_DEMAND_STARTUP_MARKER_$key"
        if ($lib.Contains($marker)) { continue }
        $block = @"
    // $marker
    BankLoad("CMRERebornDebug", 1);
    if (BankLastCreated() != null) {
        BankValueSetFromInt(BankLastCreated(), "debug", "$key", 1);
        BankSave(BankLastCreated());
    }
"@
        # Galaxy requires all local declarations to precede executable code.
        # Insert after this function's declaration section, not immediately
        # after the signature, or the generated CMRE library will not compile.
        $lib = Add-CmreBlockAfterInFunction -Content $lib -FunctionAnchor $anchor -Anchor '    // Implementation' -Marker $marker -Block $block
    }
    Write-CmreUtf8NoBom -Path $libPath -Content $lib

    $mapScriptPath = Join-Path $MapPath "MapScript.galaxy"
    $mapScript = Read-CmreUtf8 -Path $mapScriptPath
    # Do not inject a second raw BankLoad into InitMap after the observer's
    # map_init_entered write. On a fresh session this probe can stop map
    # initialization before InitLibs, so startup_map_init remains a reset
    # key for older banks but is intentionally not emitted by the map glue.
    Write-CmreUtf8NoBom -Path $mapScriptPath -Content $mapScript
    Write-Host "CMRE startup debug markers applied"
}

function Install-CmreTriggerCustomScriptOverlay {
    param([Parameter(Mandatory = $true)][string]$MapPath)

    $path = Join-Path $MapPath "Triggers"
    $content = Read-CmreUtf8 -Path $path
    $marker = "CMRE_ON_DEMAND_TRIGGER_CUSTOM_SCRIPT_V1"
    $previousVersionMarker = "CMRE_ON_DEMAND_TRIGGER_CUSTOM_SCRIPT_V2"
    $versionMarker = "CMRE_ON_DEMAND_TRIGGER_CUSTOM_SCRIPT_V3"

    # Keep this first probe independent from the copied runtime libraries. A
    # root-level map CustomScript is emitted into the generated
    # InitCustomScript() body by the editor/runtime trigger pipeline. The
    # editor stores the entry point in InitFunc; free-standing statements in
    # ScriptCode are only declarations and are not invoked by the bootstrap.
    $script = @'
// CMRE_ON_DEMAND_TRIGGER_CUSTOM_SCRIPT_V3
// API CreateGame invokes this CustomScript entry but may skip MapScript.InitMap.
// Keep the map bootstrap in one owner so the normal map path and API path share
// the same InitLibs/InitGlobals/InitTriggers and CMRE adapter initialization.
// Vibe registration belongs after the generated InitTriggers graph; InitMap
// is the single path that preserves that ordering for API CustomScript too.
void cmre_on_demand_trigger_customscript_init() {
    BankLoad("CMRERebornDebug", 1);
    if (BankLastCreated() != null) {
        BankValueSetFromInt(BankLastCreated(), "debug", "api_customscript_init_started", 1);
        BankValueSetFromInt(BankLastCreated(), "debug", "triggers_customscript_entered", 1);
        BankValueSetFromInt(BankLastCreated(), "debug", "api_customscript_minimal_probe", 1);
        BankValueSetFromInt(BankLastCreated(), "debug", "api_customscript_init_complete", 1);
        BankSave(BankLastCreated());
    }
    // Reborn campaign maps can enter the API game through CustomScript without
    // the engine invoking MapScript.InitMap. InitMap owns an independent
    // re-entry guard, so this also remains safe when the normal map path ran.
    InitMap();
}
'@.Trim()

    if ($content.Contains($versionMarker)) {
        Write-Host "CMRE trigger custom-script overlay already has V3 bootstrap"
        return
    }

    # Upgrade a map staged by the previous V1 launcher revision without
    # leaving a duplicate CustomScript item with the same editor ID.
    if ($content.Contains($marker) -or $content.Contains($previousVersionMarker)) {
        $escapedScript = [System.Security.SecurityElement]::Escape($script)
        $pattern = '(?s)(<Element Type="CustomScript" Id="C0D15A15">\s*<ScriptCode>).*?(</ScriptCode>\s*<InitFunc>cmre_on_demand_trigger_customscript_init</InitFunc>\s*</Element>)'
        $replacement = '$1' + [Environment]::NewLine + $escapedScript + [Environment]::NewLine + '        $2'
        $updated = [regex]::Replace($content, $pattern, $replacement, 1)
        if ($updated -eq $content) { throw "CMRE V1 custom-script element not found for upgrade: $path" }
        Write-CmreUtf8NoBom -Path $path -Content $updated
        Write-Host "CMRE trigger custom-script overlay upgraded to V3: $path"
        return
    }

    # Validate the existing document before making the bounded text insertion.
    # XML serialization would rewrite a multi-megabyte editor document and add
    # unrelated formatting churn to the staged map.
    $document = [System.Xml.XmlDocument]::new()
    $document.LoadXml($content)
    # TriggerData may contain one Root per Library followed by the actual map
    # root. Locate the top-level map Root instead of the first library Root.
    $lastLibraryClose = $content.LastIndexOf("</Library>", [System.StringComparison]::Ordinal)
    $rootSearchStart = if ($lastLibraryClose -ge 0) { $lastLibraryClose + "</Library>".Length } else { 0 }
    $rootOpenIndex = $content.IndexOf("<Root>", $rootSearchStart, [System.StringComparison]::Ordinal)
    if ($rootOpenIndex -lt 0) { throw "Triggers map root element not found: $path" }
    $rootIndex = $content.IndexOf("</Root>", $rootOpenIndex, [System.StringComparison]::Ordinal)
    if ($rootIndex -lt 0) { throw "Triggers map root closing element not found: $path" }
    $documentClose = "</TriggerData>"
    $documentCloseIndex = $content.LastIndexOf($documentClose, [System.StringComparison]::Ordinal)
    if ($documentCloseIndex -lt 0) { throw "Triggers document closing element not found: $path" }

    $item = '    <Item Type="CustomScript" Id="C0D15A15"/>' + [Environment]::NewLine
    $content = $content.Substring(0, $rootIndex) + $item + $content.Substring($rootIndex)

    $escapedScript = [System.Security.SecurityElement]::Escape($script)
    $element = @"
    <Element Type="CustomScript" Id="C0D15A15">
        <ScriptCode>
$escapedScript
        </ScriptCode>
        <InitFunc>cmre_on_demand_trigger_customscript_init</InitFunc>
    </Element>
"@
    # Append the element at document scope, outside all Library and Root
    # containers. The custom-script item above is the only ownership link.
    $documentCloseIndex = $documentCloseIndex + $item.Length
    $content = $content.Substring(0, $documentCloseIndex) + $element.TrimEnd() + [Environment]::NewLine + $content.Substring($documentCloseIndex)
    Write-CmreUtf8NoBom -Path $path -Content $content
    Write-Host "CMRE trigger custom-script overlay applied: $path"
}

function Install-CmrePreselectedCommanderStartupOverlay {
    param(
        [Parameter(Mandatory = $true)][string]$MapPath,
        [Parameter(Mandatory = $true)][string]$Commander,
        [switch]$SkipCountdown,
        [switch]$ApiMinimal,
        [switch]$SkipPause,
        [switch]$KeepPlayer1Vanilla
    )
    Assert-CmreGalaxyToken -Value $Commander -Name "Commander"
    $path = Join-Path $MapPath "Base.SC2Data\LibCOOC.galaxy"
    $content = Read-CmreUtf8 -Path $path
    if ($ApiMinimal) {
        Write-Host "CMRE ApiMinimal: applying headless startup patch; client still drives CreateGame+JoinGame"
    }

    $startupRoot = Join-Path (Get-CmreOverlayRoot) "startup"
    $playerTemplate = Join-Path $startupRoot "player-commander.galaxy.tpl"
    $p1 = if ($KeepPlayer1Vanilla) { "" } else { Expand-CmreTemplate -TemplatePath $playerTemplate -Values @{ PLAYER = "1"; COMMANDER = $Commander } }
    $p2 = Expand-CmreTemplate -TemplatePath $playerTemplate -Values @{ PLAYER = "2"; COMMANDER = $Commander }
    $replacement = Expand-CmreTemplate -TemplatePath (Join-Path $startupRoot "preselected-commander-startup.galaxy.tpl") -Values @{
        P1_COMMANDER_SETUP = $p1.TrimEnd()
        P2_COMMANDER_SETUP = $p2.TrimEnd()
    }

    if ($SkipPause) {
        $customPattern = '(?m)(void libCOOC_gf_CC_CustomStartupBegin \(\) \{[\s\S]*?    // Implementation\r?\n)    GameSetMissionTimePaused\(true\);\r?\n    AITimePause\(true\);\r?\n    UnitPauseAll\(true\);'
        $customReplacement = '$1' + (Read-CmreUtf8 -Path (Join-Path $startupRoot "pause.custom-startup.skip.galaxy")).TrimEnd()
        $content = Replace-CmreFirstRegex -Content $content -Pattern $customPattern -Replacement $customReplacement -AlreadyMarker "CMRE_ON_DEMAND_SKIP_CUSTOM_STARTUP_PAUSE" -Label "CustomStartupBegin pause"
        $devPattern = '(?m)^    // Implementation\r?\n    GameSetMissionTimePaused\(true\);\r?\n    AITimePause\(true\);\r?\n    UnitPauseAll\(true\);'
        $devReplacement = (Read-CmreUtf8 -Path (Join-Path $startupRoot "pause.dev-startup.skip.galaxy")).TrimEnd()
        $content = Replace-CmreFirstRegex -Content $content -Pattern $devPattern -Replacement $devReplacement -AlreadyMarker "CMRE_ON_DEMAND_SKIP_DEV_STARTUP_PAUSE" -Label "DevStartupBegin pause"
    }

    $startupPattern = '(?m)^    if \(\(libCMFE_gf_CMUIX_StartupApplySavedConfiguration\(\) == true\)\) \{\r?\n        Wait\(1\.0, c_timeReal\);\r?\n        CMUIX_ReadyBeginCountdown\(\);\r?\n        return ;\r?\n    \}'
    $startupFallbackPattern = '(?m)^    if \(\(libCMFE_gf_CMUIX_StartupApplySavedConfiguration\(\) == true\)\) \{\r?\n        TriggerSendEvent\("CU_CommChoiceEventClosed"\);\r?\n        return ;\r?\n    \}'
    $preselectedStartupPattern = '(?ms)^    // CMRE_ON_DEMAND_PRESELECTED_COMMANDER_STARTUP.*?^    return ;'
    $directOnlyStartupPattern = '(?ms)^    // CMRE_DIRECT_MAP_STARTUP_ONLY.*?^    return ;'
    $existingStartupPattern = '(?ms)^    // CMRE_ON_DEMAND_SAVED_PROFILE_STARTUP.*?^    return ;'
    $fixedStartupPattern = '(?ms)^    // CMRE_ON_DEMAND_FIXED_EMPIRE_STARTUP.*?^    return ;'
    if ([regex]::IsMatch($content, $preselectedStartupPattern)) {
        $content = [regex]::Replace($content, $preselectedStartupPattern, $replacement.TrimEnd(), 1)
    } elseif ([regex]::IsMatch($content, $directOnlyStartupPattern)) {
        $content = [regex]::Replace($content, $directOnlyStartupPattern, $replacement.TrimEnd(), 1)
    } elseif ([regex]::IsMatch($content, $fixedStartupPattern)) {
        $content = [regex]::Replace($content, $fixedStartupPattern, $replacement.TrimEnd(), 1)
    } elseif ([regex]::IsMatch($content, $existingStartupPattern)) {
        $content = [regex]::Replace($content, $existingStartupPattern, $replacement.TrimEnd(), 1)
    } elseif ([regex]::IsMatch($content, $startupPattern)) {
        $content = [regex]::Replace($content, $startupPattern, $replacement, 1)
    } elseif ([regex]::IsMatch($content, $startupFallbackPattern)) {
        $content = [regex]::Replace($content, $startupFallbackPattern, $replacement, 1)
    } else {
        throw "CMRE preselected commander startup anchor not found"
    }
    $selectionPattern = '(?ms)\r?\n    if \(\(libCOOC_gf_CC_MapIsLauncher\(libCOOC_gf_CC_CurrentMap\(\)\) == true\)\) \{\r?\n        libCOTF_gf_RunTriggerByNameEasy\(UserDataGetString\("GlobalOptions", "CommanderSelectionScreen", "TriggerString", 1\), false, false\);\r?\n    \}\r?\n'
    if ([regex]::IsMatch($content, $selectionPattern)) {
        $content = [regex]::Replace(
            $content,
            $selectionPattern,
            ([Environment]::NewLine + "    // CMRE_ON_DEMAND_NO_COMMANDER_SELECTION" + [Environment]::NewLine),
            1)
    } elseif (-not $content.Contains("CMRE_ON_DEMAND_NO_COMMANDER_SELECTION")) {
        # The owned map mirror may already have the fallback fully deleted,
        # rather than retaining the marker used by first-time source patches.
        Write-Host "CMRE commander-selection fallback already absent"
    }
    Write-CmreUtf8NoBom -Path $path -Content $content
    Assert-CmreCommanderSelectionRemoved -MapPath $MapPath
    Write-Host "CMRE preselected commander startup overlay applied from versioned assets: $Commander"
}

function Install-CmreRebornCampaignIntroSkipOverlay {
    param(
        [Parameter(Mandatory = $true)][string]$MapPath
    )
    $path = Join-Path $MapPath "MapScript.galaxy"
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Reborn campaign intro overlay MapScript not found: $path"
    }
    $content = Read-CmreUtf8 -Path $path
    $marker = "CMRE_REBORN_SKIP_CAMPAIGN_INTRO"
    if (-not $content.Contains($marker)) {
        # Keep map-owned setup/cleanup, but do not wait for the campaign
        # cinematic and transmission queue in API or PlayerMode sessions.
        $anchor = '    TriggerExecute(gt_IntroCinematic, true, true);' + [Environment]::NewLine + '    TriggerExecute(gt_IntroCinematicEnd, true, true);'
        # Reborn maps do not share one generated intro state declaration. Some
        # maps expose gv_introCinematicCompleted, while zexpedition03 only has
        # gv_introMusicCompleted. Never inject an undeclared Galaxy symbol into
        # a staged map just to skip an optional cinematic.
        $introStateAssignment = if ($content -match '(?m)^\s*bool\s+gv_introCinematicCompleted\s*;') {
            '    gv_introCinematicCompleted = false;'
        } else {
            '    // CMRE_REBORN_SKIP_CAMPAIGN_INTRO: map has no intro completion state to reset'
        }
        $replacement = @"
    // $marker
    // Preserve campaign setup and cleanup; skip only the interactive cinematic.
${introStateAssignment}
    // $marker
"@
        if ($content.Contains($anchor)) {
            $content = $content.Replace($anchor, $replacement.TrimEnd())
        } else {
            Write-Host "Reborn campaign intro not present; no cinematic skip required"
        }
    }

    # Both the map-owned intro cleanup and the Reborn library initialization
    # contain Wait(c_timeGame). A direct TriggerExecute from MapInit can start
    # that work while CMRE still has mission time paused, permanently disabling
    # SwarmSetup at its first wait. Schedule the intro after the first playable
    # game-time tick so the original setup/cleanup remains map-owned.
    # Keep the map's original intro queue timing. The campaign frontend
    # confirmation is handled by the launcher input shim before the runtime
    # listener gate; delaying gt_IntroQ changes mission-owned initialization.
    Write-CmreUtf8NoBom -Path $path -Content $content
    Write-Host "Reborn campaign intro skip overlay applied: $path"
}

function Install-CmreRebornCampaignFrontendGuardOverlay {
    param(
        [Parameter(Mandatory = $true)][string]$MapPath
    )
    $path = Join-Path $MapPath "MapScript.galaxy"
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Reborn campaign frontend guard map script not found: $path"
    }
    $content = Read-CmreUtf8 -Path $path
    $marker = "CMRE_REBORN_CAMPAIGN_FRONTEND_GUARD"
    if ($content.Contains($marker)) {
        Write-Host "Reborn campaign frontend guard already present"
        return
    }

    # Direct-map/API sessions have no campaign front-end context. Keep the
    # mission's local initialization triggers, but skip the two campaign-only
    # calls that invoke CampaignMode/CampaignProgress UI services and crash
    # the standalone map after the loading screen is dismissed.
    # The library prefix differs between the swarmstory campaign (libSwaC)
    # and CMRE co-op maps (libCOOC), so neutralise whichever variant the map
    # actually uses. If none of the candidate calls are present the map has no
    # campaign front-end dependency and the guard can be skipped safely
    # (mirrors Install-CmreRebornCampaignIntroSkipOverlay's "not present" path).
    $candidates = @(
        '    libSwaC_gf_ULoadCampaignData("ZChar1");',
        '    libSwaC_gf_PurchaseStorymodeTech();',
        '    libCOOC_gf_PurchaseStorymodeTech();'
    )
    $neutralized = 0
    foreach ($anchor in $candidates) {
        if ($content.Contains($anchor)) {
            $content = $content.Replace($anchor, "    // ${marker}: campaign/co-op story-mode tech/data call isolated for standalone/API sessions")
            $neutralized++
        }
    }
    # Reborn mission maps pass their own campaign id (for example
    # "ZExpedition3"), so the fixed ZChar1 literal above is not sufficient.
    # Remove any standalone campaign-data load call in the map initialization
    # script; the copied SwarmCampaignLib still supplies the mission helpers.
    $campaignDataPattern = '(?m)^\s*libSwaC_gf_ULoadCampaignData\("[^"]+"\);\s*$'
    if ([regex]::IsMatch($content, $campaignDataPattern)) {
        $content = [regex]::Replace(
            $content,
            $campaignDataPattern,
            "    // ${marker}: campaign data load isolated for standalone/API sessions",
            1)
        $neutralized++
    }
    if ($neutralized -eq 0) {
        Write-Host "Reborn campaign frontend guard anchors not present in MapScript; no frontend guard required: $path"
    }
    Write-CmreUtf8NoBom -Path $path -Content $content
    Write-Host "Reborn campaign frontend calls isolated in staged MapScript: $path"
}

function Install-CmreRebornStandaloneCatalogGuard {
    param(
        [Parameter(Mandatory = $true)][string]$MapPath
    )
    $path = Join-Path $MapPath "MapScript.galaxy"
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Reborn standalone catalog guard MapScript not found: $path"
    }
    $content = Read-CmreUtf8 -Path $path
    $marker = "CMRE_REBORN_STANDALONE_CATALOG_PLAYER_GUARD"
    if ($content.Contains($marker)) {
        Write-Host "Reborn standalone catalog player guard already present"
        return
    }

    # zexpedition03 invokes these catalog writes from map initialization, where
    # EventPlayer() resolves to the invalid sentinel 16. Keep the mission's
    # intended P1 standalone behavior and avoid changing the read-only source.
    $anchors = @(
        '    CatalogFieldValueSet(c_gameCatalogWeapon, "StoneZealot", "Range", EventPlayer(), "5");',
        '    CatalogFieldValueSet(c_gameCatalogWeapon, "StoneZealotEyeBlast", "Range", EventPlayer(), "6");'
    )
    $patched = 0
    foreach ($anchor in $anchors) {
        if ($content.Contains($anchor)) {
            $replacement = $anchor.Replace('EventPlayer()', '1') + " // $marker"
            $content = $content.Replace($anchor, $replacement)
            $patched++
        }
    }
    if ($patched -gt 0) {
        Write-CmreUtf8NoBom -Path $path -Content $content
        Write-Host "Reborn standalone catalog player guard applied: $patched call(s)"
    } else {
        Write-Host "Reborn standalone catalog player guard not required: $path"
    }
}

function Install-CmreObserverOverlay {
    param(
        [Parameter(Mandatory = $true)][string]$WorkspaceRoot,
        [Parameter(Mandatory = $true)][string]$MapPath,
        [Parameter(Mandatory = $true)][string]$MapName,
        [Parameter(Mandatory = $true)][bool]$IsAlengerCommander,
        [string]$AdapterLibPrefix = "",
        [object[]]$AdapterFiles = @(),
        [bool]$EnableReborn = $false,
        [string]$RebornCommander = "",
        [string]$VibeKernelOverride = "",
        [int]$InvokeTier = 0,
        [switch]$InvokeFull
    )
    if ($AdapterLibPrefix -ne "") { Assert-CmreGalaxyToken -Value $AdapterLibPrefix -Name "AdapterLibPrefix" }
    $baseData = Join-Path $MapPath "Base.SC2Data"
    $neuroRoot = Join-Path $WorkspaceRoot "reference\SC2-Neuro-API-Integration"
    $observerRoot = Join-Path $WorkspaceRoot "src\projects\cmre-porting\runtime"
    $adapterRoot = Join-Path $WorkspaceRoot "src\projects\cmre-porting\adapters\dead-of-night"
    $rebornAdapterRoot = Join-Path $WorkspaceRoot "src\projects\cmre-porting\adapters\reborn"
    $files = @(
        @{ Source = Join-Path $neuroRoot "Mod\NeuroIntegration.SC2Mod\Base.SC2Data\LibEFA54406_h.galaxy"; Name = "LibEFA54406_h.galaxy" },
        @{ Source = Join-Path $neuroRoot "Mod\NeuroIntegration.SC2Mod\Base.SC2Data\LibEFA54406.galaxy"; Name = "LibEFA54406.galaxy" },
        @{ Source = Join-Path $observerRoot "LibPortingObserver_h.galaxy"; Name = "LibPortingObserver_h.galaxy" },
        @{ Source = Join-Path $observerRoot "LibPortingObserver.galaxy"; Name = "LibPortingObserver.galaxy" },
        @{ Source = Join-Path $observerRoot "LibNeuroCommandBridge_h.galaxy"; Name = "LibNeuroCommandBridge_h.galaxy" },
        @{ Source = Join-Path $observerRoot "LibNeuroCommandBridge.galaxy"; Name = "LibNeuroCommandBridge.galaxy" },
        @{ Source = Join-Path $observerRoot "LibMapModBridge_h.galaxy"; Name = "LibMapModBridge_h.galaxy" },
        @{ Source = Join-Path $observerRoot "LibMapModBridge.galaxy"; Name = "LibMapModBridge.galaxy" },
        @{ Source = Join-Path $adapterRoot "LibDeadOfNightObserver_h.galaxy"; Name = "LibDeadOfNightObserver_h.galaxy" },
        @{ Source = Join-Path $adapterRoot "LibDeadOfNightObserver.galaxy"; Name = "LibDeadOfNightObserver.galaxy" }
    )
    # Mixed mode is supported: an Alenger commander can run on a Reborn map.
    # The Reborn library patch still calls the project-owned adapter for the
    # commander-specific opening even when no Reborn commander bank is selected.
    if ($EnableReborn) {
        $files += @(
            @{ Source = Join-Path $rebornAdapterRoot "LibRebornAdapter_h.galaxy"; Name = "LibRebornAdapter_h.galaxy" },
            @{ Source = Join-Path $rebornAdapterRoot "LibRebornAdapter.galaxy"; Name = "LibRebornAdapter.galaxy" }
        )
    }
    Copy-CmreOverlayFiles -Files $files -DestinationRoot $baseData
    if ($EnableReborn) {
        $bridgePath = Join-Path $baseData "LibMapModBridge.galaxy"
        $bridgeContent = Read-CmreUtf8 -Path $bridgePath
        $bridgeMarker = "// CMRE_REBORN_START_POINT_FALLBACK_V1"
        if (-not $bridgeContent.Contains($bridgeMarker)) {
            $bridgeAnchor = '    int lv_reused = 0;'
            if (-not $bridgeContent.Contains($bridgeAnchor)) {
                throw "Reborn start-point fallback declaration anchor not found in LibMapModBridge.galaxy"
            }
            # Galaxy requires local declarations to precede executable statements.
            # Keep the fallback declarations at function entry, then add the
            # position probe after the function's complete declaration block.
            $bridgeFunctionAnchor = 'void libMapModBridge_gf_CreateStartingUnits(int player, string structureType, string workerType, int workerCount) ' + [char]123
            if (-not $bridgeContent.Contains($bridgeFunctionAnchor)) {
                throw "Reborn start-point fallback function anchor not found in LibMapModBridge.galaxy"
            }
            $bridgeFallbackDeclarations = @"
    $bridgeMarker
    // Standalone campaign maps may expose a preplaced PreventDefeat structure
    // before PlayerStartLocation is available. Use its live position as the
    // commander opening point, preserving the map-owned structure.
    unitgroup lv_preventDefeatUnits;
    unit lv_preventDefeatUnit;
"@
            $bridgeFallbackProbe = @"
    lv_preventDefeatUnits = UnitGroup(null, player, RegionEntireMap(),
        UnitFilter((1 << c_targetFilterPreventDefeat), 0, 0,
            (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 0);
    lv_preventDefeatUnit = UnitGroupUnit(lv_preventDefeatUnits, 1);
    if ((lv_start == null) && (lv_preventDefeatUnit != null)) {
        lv_start = UnitGetPosition(lv_preventDefeatUnit);
        libMapModBridge_gf_WriteDebugBank("reborn_start_point_fallback_p" + IntToString(player), 1);
    }
"@
            $bridgeDeclarations = $bridgeFallbackDeclarations.TrimEnd() + [Environment]::NewLine
            $bridgeContent = $bridgeContent.Replace(
                $bridgeFunctionAnchor,
                $bridgeFunctionAnchor + [Environment]::NewLine + $bridgeDeclarations.TrimEnd())
            $bridgeFallback = $bridgeFallbackProbe.TrimEnd() + [Environment]::NewLine
            $bridgeContent = $bridgeContent.Replace($bridgeAnchor, $bridgeAnchor + [Environment]::NewLine + $bridgeFallback)
            Write-CmreUtf8NoBom -Path $bridgePath -Content $bridgeContent
            Write-Host "Reborn start-point fallback applied to staged LibMapModBridge"
        }
    }
    # The Vibe kernel is project-owned runtime code. Dead of Night keeps a
    # compatibility mirror for its historical map package, while generic CMRE
    # maps use the registered project kernel when they do not carry a mirror.
    $vibeKernelRoot = Join-Path $WorkspaceRoot "src\projects\cmre-porting\packages\Maps\$MapName\Base.SC2Data"
    if ($VibeKernelOverride -ne "") {
        $vibeKernelRoot = $VibeKernelOverride
        if (-not (Test-Path -LiteralPath (Join-Path $vibeKernelRoot "LibVibeKernel.galaxy"))) {
            throw "Vibe kernel override missing LibVibeKernel.galaxy: $vibeKernelRoot"
        }
        if (-not (Test-Path -LiteralPath (Join-Path $vibeKernelRoot "LibVibeKernel_h.galaxy"))) {
            throw "Vibe kernel override missing LibVibeKernel_h.galaxy: $vibeKernelRoot"
        }
        Write-Host "Vibe kernel diagnostic override: $vibeKernelRoot"
    }
    if ($VibeKernelOverride -eq "" -and
        (-not (Test-Path -LiteralPath (Join-Path $vibeKernelRoot "LibVibeKernel.galaxy")) -or
         -not (Test-Path -LiteralPath (Join-Path $vibeKernelRoot "LibVibeKernel_h.galaxy")))) {
        $vibeKernelRoot = Join-Path $WorkspaceRoot "tools\galaxy-vibe\kernel"
        Write-Host "Project Vibe kernel overlay: using registered shared kernel for $MapName"
    }
    if (Test-Path -LiteralPath $vibeKernelRoot) {
        $vibeKernelFiles = @(
            @{ Source = Join-Path $vibeKernelRoot "LibVibeKernel_h.galaxy"; Name = "LibVibeKernel_h.galaxy" },
            @{ Source = Join-Path $vibeKernelRoot "LibVibeKernel.galaxy"; Name = "LibVibeKernel.galaxy" },
            @{ Source = Join-Path $vibeKernelRoot "LibVibeHandles.galaxy"; Name = "LibVibeHandles.galaxy" }
        )
        Copy-CmreOverlayFiles -Files $vibeKernelFiles -DestinationRoot $baseData
        Write-Host "Project Vibe kernel overlay: copied $vibeKernelRoot"
    }
    # Stage 26: generated full-function invoke bundle (per-map adapter shards).
    # Files are copied flat into Base.SC2Data; names are globally unique via the
    # LibVibeInvoke prefix. The authoritative bundle lives in the shared kernel.
    # InvokeTier is opt-in: zero keeps production/WebUI launches on the stable
    # kernel and observer path. 100/1000 mount only the low-id shard range plus
    # the matching tier dispatch variant, so experimental rollouts are bounded.
    # InvokeFull deliberately uses the base dispatch plus every shard.
    if ($InvokeFull -and $InvokeTier -gt 0) {
        throw "-InvokeFull cannot be combined with -InvokeTier > 0"
    }
    $mountGeneratedInvokeBundle = $InvokeFull -or $InvokeTier -gt 0
    $vibeInvokeBundle = Join-Path $vibeKernelRoot "generated\$MapName"
    if (-not (Test-Path -LiteralPath $vibeInvokeBundle)) {
        $vibeInvokeBundle = Join-Path $WorkspaceRoot "tools\galaxy-vibe\kernel\generated\$MapName"
    }
    # A previous tiered run can leave generated shards and include lines in the
    # common staging directory. Clear those artifacts before selecting exactly
    # one implementation for libVibeInvoke_gf_Dispatch.
    Get-ChildItem -LiteralPath $baseData -Filter "LibVibeInvoke*.galaxy" -File -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction Stop
    if ($mountGeneratedInvokeBundle -and (Test-Path -LiteralPath $vibeInvokeBundle)) {
        $bundleFiles = @()
        foreach ($bundleFile in Get-ChildItem -LiteralPath $vibeInvokeBundle -Filter "*.galaxy") {
            $sourceName = $bundleFile.Name
            if ($sourceName -match '^LibVibeInvoke_(\d{2})(_h)?\.galaxy$') {
                if (-not $InvokeFull -and ((([int]$Matches[1] - 1) * 400) + 1) -gt $InvokeTier) { continue }
            } elseif ($sourceName -eq "LibVibeInvokeDispatch.galaxy") {
                if (-not $InvokeFull) {
                    $tierSource = Join-Path $vibeInvokeBundle ("LibVibeInvokeDispatch_tier" + $InvokeTier + ".galaxy")
                    if (-not (Test-Path -LiteralPath $tierSource)) {
                        throw "Invoke tier $InvokeTier dispatch variant missing: $tierSource"
                    }
                    $bundleFiles += @{ Source = $tierSource; Name = "LibVibeInvokeDispatch.galaxy" }
                    continue
                }
            } elseif ($sourceName -like "LibVibeInvokeDispatch_tier*.galaxy") {
                continue
            }
            $bundleFiles += @{ Source = $bundleFile.FullName; Name = $sourceName }
        }
        Copy-CmreOverlayFiles -Files $bundleFiles -DestinationRoot $baseData
        $bundleKind = if ($InvokeFull) { "full" } else { "tier $InvokeTier" }
        Write-Host "Project Vibe kernel overlay: copied generated invoke bundle ($($bundleFiles.Count) files, $bundleKind) for $MapName"
    } elseif ($mountGeneratedInvokeBundle) {
        Write-Host "Project Vibe kernel overlay: no generated invoke bundle for $MapName"
    } else {
        Copy-CmreOverlayFiles -Files @(
            @{ Source = Join-Path (Get-CmreOverlayRoot) "startup\invoke-disabled.galaxy"; Name = "LibVibeInvokeDisabled.galaxy" }
        ) -DestinationRoot $baseData
        Write-Host "Project Vibe kernel overlay: generated invoke bundle disabled (InvokeTier=0)"
    }
    Install-CmreTriggerCustomScriptOverlay -MapPath $MapPath

    $efaPath = Join-Path $baseData "LibEFA54406.galaxy"
    $efa = Read-CmreUtf8 -Path $efaPath
    $efa = Add-CmreLinesAfter -Content $efa -Anchor 'include "LibEFA54406_h"' -Lines @('include "LibPortingObserver_h"')
    $actionAnchor = '    libEFA54406_gf_create_action_1_arg("chat_message", true, "Post a message into the game chat", "string", -1);' + [Environment]::NewLine + '    return true;'
    $actionPatch = '    libEFA54406_gf_create_action_1_arg("chat_message", true, "Post a message into the game chat", "string", -1);' + [Environment]::NewLine + '    libEFA54406_gf_BootstrapPortingObserver();' + [Environment]::NewLine + '    return true;'
    if ($efa.Contains($actionAnchor)) { $efa = $efa.Replace($actionAnchor, $actionPatch) }
    $legacyColorCall = '            libEFA54406_gv_displayNameText = TextWithColor(libEFA54406_gv_displayNameText, Color(100.00, 50.20, 75.29));'
    if ($efa.Contains($legacyColorCall)) { $efa = $efa.Replace($legacyColorCall, '            // CMRE adapter: display text retained without incompatible color conversion.') }
    $execMapAnchor = '    BankSave(BankLastCreated());' + [Environment]::NewLine + '    Wait(0.1, c_timeReal);' + [Environment]::NewLine + '    TriggerSendEvent("execute_actions_map");' + [Environment]::NewLine + '    return true;'
    $execMapPatch = '    BankSave(BankLastCreated());' + [Environment]::NewLine + '    Wait(0.1, c_timeReal);' + [Environment]::NewLine + '    TriggerSendEvent("execute_actions_map");' + [Environment]::NewLine + '    libEFA54406_gv_bankwriteallowed = true;' + [Environment]::NewLine + '    return true;'
    if ($efa.Contains($execMapAnchor)) { $efa = $efa.Replace($execMapAnchor, $execMapPatch) }
    Write-CmreUtf8NoBom -Path $efaPath -Content $efa

    $mapScriptPath = Join-Path $MapPath "MapScript.galaxy"
    $mapScript = Read-CmreUtf8 -Path $mapScriptPath
    $isRebornZChar01 = $EnableReborn -and ($MapName -match '(?i)^zchar01_reborn_port(?:\.SC2Map)?$')
    # The ally economy fragment is mission-owned CMRE behavior. Reborn and
    # Revolution maps use their own campaign/mission startup and must only get
    # the shared listener/initialization bridge from this overlay.
    $cmreMapSource = Join-Path $WorkspaceRoot "src\projects\cmre-porting\packages\Maps\$MapName"
    # Reborn campaign startup already owns the Computer-slot melee opening.
    # Running CMRE's fallback MeleeInitUnitsForPlayer(2) as well creates a
    # second P2 base/worker set. Keep the fallback for native CMRE maps only.
    $enableCmreComputerAllyEconomy = (-not $EnableReborn) -and
        (Test-Path -LiteralPath $cmreMapSource -PathType Container)
    # The map-owned Vibe kernel is a source library, not an external TriggerLib
    # dependency. The header-only include leaves the generated compilation unit
    # with declarations but no implementations, so InitMap never links.
    if ($mapScript.Contains('include "LibVibeKernel_h"')) {
        $mapScript = $mapScript.Replace('include "LibVibeKernel_h"', 'include "LibVibeKernel"')
    } elseif (-not $mapScript.Contains('include "LibVibeKernel"')) {
        $mapIncludeAnchor = Select-CmreExistingAnchor -Content $mapScript -Candidates @(
            'include "LibCOUI"',
            'include "LibCOOC"',
            'include "LibCOMI"',
            'include "Lib48DF4533"',
            'include "Lib281DEC45"',
            'include "Lib114935F5"',
            'include "TriggerLibs/NativeLib"'
        ) -Name 'map library include'
        $mapScript = Add-CmreLinesAfter -Content $mapScript -Anchor $mapIncludeAnchor -Lines @('include "LibVibeKernel"')
    }
    $mapIncludeAnchor = Select-CmreExistingAnchor -Content $mapScript -Candidates @(
        'include "LibCOUI"',
        'include "LibCOOC"',
        'include "LibCOMI"',
        'include "Lib48DF4533"',
        'include "Lib281DEC45"',
        'include "Lib114935F5"',
        'include "TriggerLibs/NativeLib"'
    ) -Name 'map library include'
    # Stage 26 is opt-in. The default WebUI launcher must not compile the
    # experimental generated shards merely because they are present on disk.
    # Always replace old generated include lines before adding the selected
    # implementation. Otherwise a prior tiered launch leaves MapScript with
    # references to files removed by the cleanup above.
    $mapScript = [regex]::Replace($mapScript, '(?m)^[ \t]*include "LibVibe(?:Handles|Invoke(?:Common|_[^"]*|Dispatch|Disabled))"\r?\n', '')
    $vibeInvokeBundleDir = Join-Path $baseData "LibVibeInvokeDispatch.galaxy"
    if ($mountGeneratedInvokeBundle -and (Test-Path -LiteralPath $vibeInvokeBundleDir)) {
        $vibeInvokeIncludes = @('include "LibVibeHandles"', 'include "LibVibeInvokeCommon"')
        $vibeInvokeShards = Get-ChildItem -LiteralPath $baseData -Filter "LibVibeInvoke_*.galaxy" |
            Where-Object { $_.Name -notlike "*_h.galaxy" } |
            Sort-Object Name |
            ForEach-Object { 'include "' + $_.BaseName + '"' }
        $vibeInvokeIncludes += $vibeInvokeShards
        $vibeInvokeIncludes += 'include "LibVibeInvokeDispatch"'
        $mapScript = Add-CmreLinesAfter -Content $mapScript -Anchor 'include "LibVibeKernel"' -Lines $vibeInvokeIncludes
    } elseif (-not $mountGeneratedInvokeBundle) {
        $disabledInvokeStub = Join-Path $baseData "LibVibeInvokeDisabled.galaxy"
        if (-not (Test-Path -LiteralPath $disabledInvokeStub -PathType Leaf)) {
            throw "Stable invoke dispatch stub missing: $disabledInvokeStub"
        }
        $mapScript = Add-CmreLinesAfter -Content $mapScript -Anchor 'include "LibVibeKernel"' -Lines @('include "LibVibeInvokeDisabled"')
    }
    $includeLines = @('include "LibEFA54406"', 'include "LibNeuroCommandBridge"', 'include "LibPortingObserver"', 'include "LibDeadOfNightObserver"', 'include "LibMapModBridge"')
    if ($IsAlengerCommander -and $AdapterLibPrefix -ne "") { $includeLines += ('include "Lib' + $AdapterLibPrefix + '"') }
    $mapScript = Add-CmreLinesAfter -Content $mapScript -Anchor $mapIncludeAnchor -Lines $includeLines
    $mapInitAnchor = Select-CmreExistingAnchor -Content $mapScript -Candidates @(
        '    libCOUI_InitLib();',
        '    libCOOC_InitLib();',
        '    libCOMI_InitLib();',
        '    lib48DF4533_InitLib();',
        '    lib281DEC45_InitLib();',
        '    lib114935F5_InitLib();',
        '    libNtve_InitLib();'
    ) -Name 'map library init'
    $initLibLines = @('    libEFA54406_InitLib();', '    libNeuroCommandBridge_InitLib();', '    libPortingObserver_InitLib();', '    libMapModBridge_InitLib();')
    if ($IsAlengerCommander -and $AdapterLibPrefix -ne "") { $initLibLines += ('    lib' + $AdapterLibPrefix + '_InitLib();') }
    $mapScript = Add-CmreLinesAfter -Content $mapScript -Anchor $mapInitAnchor -Lines $initLibLines
    # Windows PowerShell can decode this UTF-8-no-BOM script with the active
    # code page, so a Chinese MapName comparison is not stable. Dead of Night
    # has an ASCII-only MapScript signature that survives staging and avoids
    # silently selecting the generic glue.
    $isDeadOfNight = $mapScript.Contains("gv_day_Duration_First")
    $fragmentName = if ($isDeadOfNight) { "map-glue.dead-of-night.galaxy" } else { "map-glue.generic.galaxy" }
    $fragment = Read-CmreUtf8 -Path (Join-Path (Get-CmreOverlayRoot) $fragmentName)
    if ($isRebornZChar01) {
        $zcharGlue = Read-CmreUtf8 -Path (Join-Path (Get-CmreOverlayRoot) "map-glue.reborn-zchar01.galaxy")
        $fragment = $fragment.TrimEnd() + [Environment]::NewLine + [Environment]::NewLine + $zcharGlue.Trim()
    }
    $initializationGate = Read-CmreUtf8 -Path (Join-Path (Get-CmreOverlayRoot) "startup\initialization-gate.galaxy")
    $fragment = $fragment.TrimEnd() + [Environment]::NewLine + [Environment]::NewLine + $initializationGate.Trim()
    $mapInitAnchor = "//--------------------------------------------------------------------------------------------------" + [Environment]::NewLine + "// Map Initialization"
    $mapGlueMarker = "// CMRE_ON_DEMAND_MAP_GLUE"
    $mapGlueEndMarker = "// CMRE_ON_DEMAND_INITMAP_ENTERED_STATE"
    if ($mapScript.Contains($mapGlueMarker)) {
        # A staged map may come from an earlier launcher run. Replace the
        # generated block so changed project-owned glue is not silently
        # masked by Add-CmreBlockBefore's idempotence shortcut.
        $mapScript = Replace-CmreBlockBetweenMarkers -Content $mapScript -StartMarker $mapGlueMarker -EndMarker $mapGlueEndMarker -Block $fragment -Name "CMRE map glue"
    } else {
        $mapScript = Add-CmreBlockBefore -Content $mapScript -Anchor $mapInitAnchor -Marker "CMRE_ON_DEMAND_MAP_GLUE" -Block $fragment
    }
    if ($isRebornZChar01) {
        $zcharMarker = "// CMRE_REBORN_ZCHAR01_ALLY_GUARD"
        if ($mapScript.Contains($zcharMarker)) {
            $mapScript = Replace-CmreBlockBetweenMarkers -Content $mapScript -StartMarker $zcharMarker -EndMarker $mapInitAnchor -Block $zcharGlue -Name "ZChar01 ally glue"
        } else {
            $mapScript = Add-CmreBlockBefore -Content $mapScript -Anchor $mapInitAnchor -Marker "CMRE_REBORN_ZCHAR01_ALLY_GUARD" -Block $zcharGlue
        }
    }
    # Register Vibe after the generated map initialization graph. Trigger
    # objects created before InitLibs/InitTriggers are not reliable in SC2.
    $mapScript = [regex]::Replace($mapScript, '(?m)^[ \t]*libVibeKernel_gf_RegisterEntryPoints\(\);\r?\n', '')
    $initMapStateMarker = "CMRE_ON_DEMAND_INITMAP_ENTERED_STATE"
    $mapScript = Add-CmreBlockBefore -Content $mapScript -Anchor $mapInitAnchor -Marker $initMapStateMarker -Block @'
// CMRE_ON_DEMAND_INITMAP_ENTERED_STATE
// Protect only the generated map bootstrap from accidental re-entry. The
// Vibe kernel has its own lifecycle and must not control whether InitMap runs.
bool gv_CmreOnDemandInitMapEntered = false;
'@
    $initMapFunctionAnchor = "void InitMap () " + [char]123
    $mapScript = Add-CmreBlockAfter -Content $mapScript -Anchor $initMapFunctionAnchor -Marker "CMRE_ON_DEMAND_TRIGGER_CUSTOM_SCRIPT_INITMAP_GUARD" -Block @'
    // CMRE_ON_DEMAND_TRIGGER_CUSTOM_SCRIPT_INITMAP_GUARD
    if (gv_CmreOnDemandInitMapEntered) { return; }
    gv_CmreOnDemandInitMapEntered = true;
'@
    $mapScript = Add-CmreLinesAfter -Content $mapScript -Anchor $initMapFunctionAnchor -Lines @('    libMapModBridge_gf_WriteDebugBank("stage16_before_vibe", 1);', '    libVibeKernel_gf_WriteBankInt("index", "stage16_before_vibe", 160801);')
    # CMRE_ON_DEMAND_MAP_INIT_ENTERED_REASSERT（2026-08-09 真机取证）：
    # InitMap 首行的 map_init_entered 写入经常**静默丢失**——此时
    # BankLoad("CMRERebornDebug", 1) 仍返回 null（bank 异步加载未完成），
    # libMapModBridge_gf_WriteDebugBank 会 early-return 而不写任何东西。
    # 证据：SC2 自存的 CMRERebornDebug.SC2Bank 里有 stage16_before_vibe /
    # stage16_after_vibe = 1，唯独没有 map_init_entered（首行那次被丢）。
    # 后果致命：gf_CmreOnDemandInitializationReady() 第一句就是
    #   if (gf_CmreOnDemandDebugInt("map_init_entered") == 0) { return false; }
    # → initialization_complete 永远为 0 → Wait-CmreRuntimeListener 必然超时。
    # 修复：InitTriggers() 之后 bank 已就绪，无条件补写一次。
    # 注意：Add-CmreLinesAfter 以整行文本判重，故此行必须与首行那句**文本不同**
    #（保留尾部 // CMRE_REASSERT 注释），否则会被当成已存在而被过滤掉。
    $initTriggerLines = @('    libVibeKernel_gf_WriteBankInt("index", "stage16_after_vibe", 160801);', '    libVibeKernel_gf_RegisterEntryPoints();', '    libMapModBridge_gf_WriteDebugBank("stage16_after_vibe", 1);', '    libMapModBridge_gf_WriteDebugBank("map_init_entered", 1); // CMRE_REASSERT', '    libDeadOfNightObserver_InitLib();', '    gt_CmreOnDemandRuntimeListener_Init();', '    gt_CmreOnDemandDeadOfNightPoll_Init();', '    gt_CmreOnDemandCommanderStartingUnits_Init();', '    gt_CmreOnDemandAllyChat_Init();')
    if ($enableCmreComputerAllyEconomy) {
        $initTriggerLines += '    gt_CmreOnDemandComputerAllyReady_Init();'
        Write-Host "CMRE computer ally economy: enabled for owned CMRE map $MapName"
    } else {
        Write-Host "CMRE computer ally economy: skipped for non-CMRE map $MapName"
    }
    if ($EnableReborn) {
        # Reborn campaign maps may load Lib48DF4533 without dispatching its
        # native Initialization event. InitMap is the reliable post-bootstrap owner.
        # The trigger was created by InitLibs. Probe it before the gate below;
        # the gate waits for reborn_adapter_initialized.
        $initTriggerLines += '    TriggerExecute(gt_CmreRebornDeferredStartup, false, true);'
    }
    $initTriggerLines += '    gt_CmreOnDemandInitializationGate_Init();'
    $mapScript = Add-CmreLinesAfter -Content $mapScript -Anchor '    InitTriggers();' -Lines $initTriggerLines
    if ($isRebornZChar01) {
        $mapScript = Add-CmreLinesAfter -Content $mapScript -Anchor '    gt_CmreOnDemandComputerAllyReady_Init();' -Lines @('    gt_CmreRebornZChar01AllyGuard_Init();')
        $zcharTargetMarker = "CMRE_REBORN_ZCHAR01_SCRIPTED_TARGET_PATCH_V1"
        if (-not $mapScript.Contains($zcharTargetMarker)) {
            $mapScript = Add-CmreLinesAfter -Content $mapScript -Anchor 'include "TriggerLibs/NativeLib"' -Lines @(
                "// $zcharTargetMarker",
                'playergroup gv_CmreRebornZChar01CoopTargets;'
            )
            $zcharTargetReplacements = @(
                @{ Anchor = 'AIAttackWaveSetTargetPlayer(gv_pLAYER_02_ZERG, gv_fren);'; Replacement = 'AIAttackWaveSetTargetPlayer(gv_pLAYER_02_ZERG, gv_CmreRebornZChar01CoopTargets);' },
                @{ Anchor = 'AIAttackWaveSetTargetPlayer(gv_pLAYER_02_ZERG, PlayerGroupSingle(gv_pLAYER_01_USER));'; Replacement = 'AIAttackWaveSetTargetPlayer(gv_pLAYER_02_ZERG, gv_CmreRebornZChar01CoopTargets);' },
                @{ Anchor = 'AIAttackWaveSetTargetPlayer(gv_pLAYER_02_ZERG2223, PlayerGroupSingle(gv_pLAYER_02_ZERG));'; Replacement = 'AIAttackWaveSetTargetPlayer(gv_pLAYER_02_ZERG2223, gv_CmreRebornZChar01CoopTargets);' }
            )
            foreach ($replacement in $zcharTargetReplacements) {
                if (-not $mapScript.Contains($replacement.Anchor)) {
                    throw "ZChar01 scripted target anchor not found: $($replacement.Anchor)"
                }
                $mapScript = $mapScript.Replace($replacement.Anchor, $replacement.Replacement)
            }
        }
        $zcharForwardDeclMarker = "CMRE_REBORN_ZCHAR01_FORWARD_DECLS_V1"
        if (-not $mapScript.Contains($zcharForwardDeclMarker)) {
            $mapScript = Add-CmreLinesAfter -Content $mapScript -Anchor 'include "TriggerLibs/NativeLib"' -Lines @(
                "// $zcharForwardDeclMarker",
                'void gf_CmreRebornZChar01StartAI();',
                'void gf_CmreRebornZChar01StartEnemyWaves();'
            )
        }
        $startAiPattern = '(?m)^([ \t]*)cai_startall\(\);\r?(?=\n[ \t]*AISetAPM\(gv_pLAYER_02_ZERG2223, 10000\);)'
        if ([regex]::Matches($mapScript, $startAiPattern).Count -ne 1 -and -not $mapScript.Contains('CMRE_REBORN_ZCHAR01_START_AI_PATCH')) {
            throw 'ZChar01 StartAI anchor count is not exactly one'
        }
        $mapScript = Replace-CmreFirstRegex -Content $mapScript -Pattern $startAiPattern -Replacement ('$1// CMRE_REBORN_ZCHAR01_START_AI_PATCH' + [Environment]::NewLine + '$1gf_CmreRebornZChar01StartAI();') -AlreadyMarker 'CMRE_REBORN_ZCHAR01_START_AI_PATCH' -Label 'ZChar01 StartAI'
        $wavePattern = '(?m)^([ \t]*)TriggerExecute\(gt_ZergAttackWaves, true, false\);\r?(?=\n[ \t]*if \(\(libHots_gf_DifficultyValueInt2\(0, 0, 1\) == 1\)\))'
        if ([regex]::Matches($mapScript, $wavePattern).Count -ne 1 -and -not $mapScript.Contains('CMRE_REBORN_ZCHAR01_WAVE_PATCH')) {
            throw 'ZChar01 enemy-wave anchor count is not exactly one'
        }
        $mapScript = Replace-CmreFirstRegex -Content $mapScript -Pattern $wavePattern -Replacement ('$1// CMRE_REBORN_ZCHAR01_WAVE_PATCH' + [Environment]::NewLine + '$1gf_CmreRebornZChar01StartEnemyWaves();') -AlreadyMarker 'CMRE_REBORN_ZCHAR01_WAVE_PATCH' -Label 'ZChar01 enemy waves'
    }
    $mapScript = Add-CmreLinesAfter -Content $mapScript -Anchor $initMapFunctionAnchor -Lines @(
        '    libVibeKernel_gf_RegisterEntryPoints();',
        '    libMapModBridge_gf_WriteDebugBank("map_init_entered", 1);'
    )
    # 形态E / VIBE_GEN_009：必须排在**所有** include / glue 注入之后、写盘之前。
    # invoke 层挂在文件头部，而地图本体的原型区和定义都在其后，不补前置原型 =>
    # 编译错误 => SC2 静默丢弃整个 MapScript（真机 2026-08-09 亡者之夜取证）。
    $mapScript = Add-CmreForwardProtos -Content $mapScript -Anchor 'include "LibVibeKernel"'
    Write-CmreUtf8NoBom -Path $mapScriptPath -Content $mapScript

    # 形态 M / VIBE_GEN_010：生成闭包 != 挂载闭包。
    #
    # Stage 26 的 LibVibeInvokeCommon.galaxy 里 libVibeInvoke_gf_ResolveFuncref 是一张
    # 400+ 行静态表（`if (name == "X") { return X; }`），按**生成时那份地图包**的符号集
    # 产出；而实际挂载闭包由本 overlay 按指挥官/依赖动态决定。两者不一致时表里就会留下
    # 指向闭包外的符号（真机取证：官方指挥官局既不拷 adapter 文件也不 include，表里却仍有
    # `return libA3ADAPTER_gf_UnlockAllAbilities;`）=> 未定义标识符 => SC2 **静默丢弃整个
    # MapScript** => 门禁全绿但 Kernel 永不注册、每个 RPC 都 INTERNAL_ERROR。
    # 2026-08-09 N2 tier100 的 53/53 INTERNAL_ERROR 即此（离线双向对照：原包 BROKEN /
    # 未定义标识符 1，仅删该行转 CLEAN，差集恰为该行）。
    #
    # 【为什么净化不放在这里 —— 实测负结论，勿重蹈】
    # 曾在此处用 PS 实现「符号 libP_* 的前缀 P 必须能在 MapScript 的 include 里找到 LibP...」
    # 的行级剔除。实测在 404 行表上摘掉 28 行，**其中 27 行是误伤**：LibCOTF / LibCMFE /
    # LibCOMU 等是被别的 lib **间接 include** 的，只扫 MapScript 顶层 include 根本看不见；
    # 且 `TriggerLibs/LibertyLib` 还会被 Substring(3) 切成 `ertyLib` 这种垃圾前缀。
    # 结论：判定符号可用性需要**完整递归 include 闭包 + 依赖 mod 符号表**，那正是
    # compile_unit.resolve() 的活，在 PS 里重写必然出错。
    #
    # 正确做法：净化交给离线门禁（python，吃完整符号表，零误伤）——
    #     python tools/galaxy-vibe/mpq/staged_map_doctor.py "<暂存 .SC2Map 目录>" --fix
    # 放量取证前必跑。日常真人局不挂 Stage 26 gen bundle，不受此形态影响，
    # 因此这里不做任何净化，避免为低频路径给每次启动增加 pack+resolve 的十几秒开销。

    Install-CmreStartupDebugMarkersOverlay -MapPath $MapPath

    $bankListPath = Join-Path $MapPath "BankList.xml"
    [xml]$bankList = Read-CmreUtf8 -Path $bankListPath
    $bankChanged = $false
    foreach ($entry in @(
        @{ Name = "NeuroIntegration"; Player = "1" },
        # GalaxyVibe is the typed Vibe RPC bank. SC2 rejects writes to an
        # undeclared bank during map initialization, which would stop InitMap
        # before the kernel can register its transports.
        @{ Name = "GalaxyVibe"; Player = "1" },
        @{ Name = "CMRERebornDebug"; Player = "1" },
        @{ Name = "CMRERebornDebug"; Player = "2" },
        @{ Name = "CMRERebornDebug"; Player = "14" }
    )) {
        if (@($bankList.BankList.Bank | Where-Object { $_.Name -eq $entry.Name -and $_.Player -eq $entry.Player }).Count -eq 0) {
            $bank = $bankList.CreateElement("Bank")
            $bank.SetAttribute("Name", $entry.Name)
            $bank.SetAttribute("Player", $entry.Player)
            $bankList.BankList.AppendChild($bank) | Out-Null
            $bankChanged = $true
        }
    }
    if ($bankChanged) {
        $settings = [System.Xml.XmlWriterSettings]::new()
        $settings.Indent = $true
        $settings.Encoding = [System.Text.UTF8Encoding]::new($false)
        $writer = [System.Xml.XmlWriter]::Create($bankListPath, $settings)
        try { $bankList.Save($writer) } finally { $writer.Dispose() }
    }
    Initialize-CmreRuntimeListenerBank
    Write-Host "CMRE observer/runtime overlay applied on demand"
}
