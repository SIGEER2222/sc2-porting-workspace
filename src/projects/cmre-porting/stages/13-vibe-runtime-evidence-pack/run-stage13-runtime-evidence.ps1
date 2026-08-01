<#
.SYNOPSIS
  Stage 13 runtime evidence harness for the SC2 Vibe workflow.

.DESCRIPTION
  Wraps the approved Galaxy Vibe launcher, captures stdout/stderr, copies runtime
  verdict artifacts into the Stage 13 artifact directory, and writes a compact
  runtime-summary.json. This script does not launch SC2 directly; it delegates to
  tools/galaxy-vibe/launch-galaxy-vibe.ps1.
#>
[CmdletBinding()]
param(
    [string]$RunId = "stage13-runtime",
    [int]$Port = 5000,
    [string]$Map = "",
    [string]$Verify = "",
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

function ConvertTo-RepoRelative {
    param([AllowNull()][object]$InputPath)
    if ($null -eq $InputPath) { return "" }
    $raw = [string]$InputPath
    if (-not $raw) { return "" }
    try {
        $full = [System.IO.Path]::GetFullPath($raw)
        $rootFull = [System.IO.Path]::GetFullPath($RepoRoot)
    } catch {
        return $raw -replace '\\', '/'
    }
    if ($full.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $full.Substring($rootFull.Length).TrimStart('\') -replace '\\', '/'
    }
    return $raw -replace '\\', '/'
}

function Copy-IfExists {
    param(
        [string]$Source,
        [string]$DestinationName,
        [string]$Category
    )
    if (-not (Test-Path -LiteralPath $Source)) {
        return $null
    }
    $dest = Join-Path $StageArtifacts $DestinationName
    if ([System.IO.Path]::GetFullPath($Source) -ne [System.IO.Path]::GetFullPath($dest)) {
        Copy-Item -LiteralPath $Source -Destination $dest -Force
    }
    $item = Get-Item -LiteralPath $dest
    return @{
        category = $Category
        source = (ConvertTo-RepoRelative -InputPath $Source)
        copied_to = (ConvertTo-RepoRelative -InputPath $dest)
        size_bytes = $item.Length
        last_write_time = $item.LastWriteTime.ToString("o")
    }
}

function Read-JsonUtf8 {
    param([string]$Path)
    $text = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
    return $text | ConvertFrom-Json
}

$ScriptPath = $MyInvocation.MyCommand.Path
$StageDir = Split-Path -Parent $ScriptPath
$RepoRoot = (Resolve-Path (Join-Path $StageDir "..\..\..\..\..")).Path
$StageArtifacts = Join-Path $RepoRoot "artifacts\projects\cmre-porting\stage13-vibe-runtime-evidence-pack"
$GalaxyArtifacts = Join-Path $RepoRoot "artifacts\galaxy-vibe"
$RunArtifacts = Join-Path $GalaxyArtifacts "run-$RunId"
$Stage12Artifacts = Join-Path $RepoRoot "artifacts\projects\cmre-porting\stage12-vibe-task-manifest"
$Stage12Manifest = Join-Path $Stage12Artifacts "manifest.json"
$Launcher = Join-Path $RepoRoot "tools\galaxy-vibe\launch-galaxy-vibe.ps1"
$ScriptErrorCheck = Join-Path $RepoRoot "tools\galaxy-vibe\script_error_check.py"
$Bundler = Join-Path $RepoRoot "tools\galaxy-vibe\evidence_bundle.py"
$PackSc2Map = Join-Path $RepoRoot "tools\mpq\scripts\pack-sc2map.ps1"
$PackSc2MapPy = Join-Path $RepoRoot "tools\mpq\scripts\pack_stormlib.py"

if (-not $Map) {
    $manifest = Read-JsonUtf8 -Path $Stage12Manifest
    $Map = Join-Path $RepoRoot ([string]$manifest.source.map_path)
}
if (-not $Verify) {
    $Verify = Join-Path $Stage12Artifacts "scenario.vtest"
}
$SourceVerify = $Verify

New-Item -ItemType Directory -Force -Path $StageArtifacts, $RunArtifacts | Out-Null

$LauncherMap = $Map
$StagedMap = ""
$PackedMap = ""
$PackStdout = Join-Path $StageArtifacts "pack-sc2map-stdout.txt"
$PackStderr = Join-Path $StageArtifacts "pack-sc2map-stderr.txt"
$PackExitJson = Join-Path $StageArtifacts "pack-sc2map-exit.json"
if ($Map -match "[^\x00-\x7F]") {
    $StagedMapRoot = Join-Path $StageArtifacts "runtime-map"
    $StagedMap = Join-Path $StagedMapRoot "DeadOfNight.unpacked.SC2Map"
    $PackedMap = Join-Path $StagedMapRoot "DeadOfNight.packed.SC2Map"
    if (Test-Path -LiteralPath $StagedMap) {
        Remove-Item -LiteralPath $StagedMap -Recurse -Force
    }
    if (Test-Path -LiteralPath $PackedMap) {
        Remove-Item -LiteralPath $PackedMap -Force
    }
    New-Item -ItemType Directory -Force -Path $StagedMapRoot | Out-Null
    Copy-Item -LiteralPath $Map -Destination $StagedMapRoot -Recurse -Force
    $copiedOriginal = Join-Path $StagedMapRoot (Split-Path -Leaf $Map)
    if ((Test-Path -LiteralPath $copiedOriginal) -and ($copiedOriginal -ne $StagedMap)) {
        Rename-Item -LiteralPath $copiedOriginal -NewName "DeadOfNight.unpacked.SC2Map" -Force
    }
    $workspaceParent = Split-Path -Parent $RepoRoot
    $stormlibCandidates = @(
        (Join-Path $RepoRoot "artifacts\stormlib-v9.40\x64\StormLib.dll"),
        (Join-Path $RepoRoot "artifacts\stormlib-v9.40\Win32\StormLib.dll"),
        (Join-Path $workspaceParent "artifacts\stormlib-v9.40\x64\StormLib.dll"),
        (Join-Path $workspaceParent "artifacts\stormlib-v9.40\Win32\StormLib.dll")
    )
    $StormLibDll = ""
    foreach ($candidate in $stormlibCandidates) {
        if (Test-Path -LiteralPath $candidate) {
            $StormLibDll = $candidate
            break
        }
    }
    if (-not (Test-Path -LiteralPath $PackSc2MapPy) -or -not $StormLibDll) {
        $summary = @{
            schemaVersion = 1
            run_id = $RunId
            status = "blocked-runtime-unavailable"
            evidence_type = "blocked"
            reason = "SC2 map packer dependency missing"
            packer = (ConvertTo-RepoRelative -InputPath $PackSc2MapPy)
            stormlib_candidates = $stormlibCandidates | ForEach-Object { ConvertTo-RepoRelative -InputPath $_ }
            generated_at = (Get-Date).ToString("o")
        }
        $summary | ConvertTo-Json -Depth 8 | Set-Content -Path (Join-Path $StageArtifacts "runtime-summary.json") -Encoding UTF8
        Write-Host "BLOCKED: missing map packer dependency"
        exit 2
    }
    $packArgs = @(
        $PackSc2MapPy,
        $StagedMap,
        $PackedMap,
        "--stormlib",
        $StormLibDll
    )
    $packStart = Get-Date
    $packProc = Start-Process -FilePath $Python -ArgumentList $packArgs -Wait -PassThru -NoNewWindow -RedirectStandardOutput $PackStdout -RedirectStandardError $PackStderr
    $packExit = $packProc.ExitCode
    @{
        schemaVersion = 1
        run_id = $RunId
        started_at = $packStart.ToString("o")
        finished_at = (Get-Date).ToString("o")
        command = "$Python " + ($packArgs -join " ")
        exit_code = $packExit
        input_dir = (ConvertTo-RepoRelative -InputPath $StagedMap)
        output_map = (ConvertTo-RepoRelative -InputPath $PackedMap)
        packer = (ConvertTo-RepoRelative -InputPath $PackSc2MapPy)
        stormlib = (ConvertTo-RepoRelative -InputPath $StormLibDll)
        stdout = (ConvertTo-RepoRelative -InputPath $PackStdout)
        stderr = (ConvertTo-RepoRelative -InputPath $PackStderr)
    } | ConvertTo-Json -Depth 8 | Set-Content -Path $PackExitJson -Encoding UTF8
    if ($packExit -ne 0 -or -not (Test-Path -LiteralPath $PackedMap)) {
        $summary = @{
            schemaVersion = 1
            run_id = $RunId
            status = "blocked-runtime-unavailable"
            evidence_type = "blocked"
            reason = "SC2 map packing failed"
            pack_exit_code = $packExit
            pack_stdout = (ConvertTo-RepoRelative -InputPath $PackStdout)
            pack_stderr = (ConvertTo-RepoRelative -InputPath $PackStderr)
            generated_at = (Get-Date).ToString("o")
        }
        $summary | ConvertTo-Json -Depth 8 | Set-Content -Path (Join-Path $StageArtifacts "runtime-summary.json") -Encoding UTF8
        Write-Host "BLOCKED: pack failed for $StagedMap -> $PackedMap"
        exit 2
    }
    $LauncherMap = $PackedMap
}

$start = Get-Date
$startEpoch = [int][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$launcherStdout = Join-Path $StageArtifacts "launcher-stdout.txt"
$launcherStderr = Join-Path $StageArtifacts "launcher-stderr.txt"
$launcherExitJson = Join-Path $StageArtifacts "launcher-exit.json"

$required = @($Launcher, $ScriptErrorCheck, $Bundler, $LauncherMap, $Verify)
foreach ($path in $required) {
    if (-not (Test-Path -LiteralPath $path)) {
        $summary = @{
            schemaVersion = 1
            run_id = $RunId
            status = "blocked-runtime-unavailable"
            evidence_type = "blocked"
            reason = "required path missing"
            missing_path = (ConvertTo-RepoRelative -InputPath $path)
            generated_at = (Get-Date).ToString("o")
        }
        $summary | ConvertTo-Json -Depth 8 | Set-Content -Path (Join-Path $StageArtifacts "runtime-summary.json") -Encoding UTF8
        Write-Host "BLOCKED: missing $path"
        exit 2
    }
}

# Avoid stale generic verdicts from previous launches.
$cleared = @()
foreach ($name in @("assert-results.json", "script-error-verdict.json", "vibe-verdict.json", "visual-verdict.json")) {
    $p = Join-Path $GalaxyArtifacts $name
    if (Test-Path -LiteralPath $p) {
        Remove-Item -LiteralPath $p -Force
        $cleared += (ConvertTo-RepoRelative -InputPath $p)
    }
    $stageP = Join-Path $StageArtifacts $name
    if (Test-Path -LiteralPath $stageP) {
        Remove-Item -LiteralPath $stageP -Force
        $cleared += (ConvertTo-RepoRelative -InputPath $stageP)
    }
}

# Preserve Stage 12 inputs next to runtime evidence.
$copied = @()
foreach ($name in @("manifest.json", "summary.json", "task.live.json", "runtime-recipe.json", "scenario.vtest")) {
    $src = Join-Path $Stage12Artifacts $name
    $entry = Copy-IfExists -Source $src -DestinationName "stage12-$name" -Category "static-input"
    if ($entry) { $copied += $entry }
}

$RuntimeVerify = Join-Path $StageArtifacts "runtime-scenario.vtest"
$verifyText = [System.IO.File]::ReadAllText($Verify, [System.Text.Encoding]::UTF8)
$runtimeVerifyText = $verifyText
if (
    $verifyText -match "(?m)^spawn\s+marine\s+1\s+1\s*$" -and
    $verifyText -match "(?m)^assert\s+count\s+marine\s+==\s+1\s+--player\s+1\s*$" -and
    $verifyText -notmatch "stage13-preclean"
) {
    $insertion = "# stage13-preclean: live mission maps can contain baseline marines; normalize before exact-count smoke." + [Environment]::NewLine + "kill marine --player 1" + [Environment]::NewLine + '$1'
    $runtimeVerifyText = $verifyText -replace "(?m)^(spawn\s+marine\s+1\s+1\s*)$", $insertion
}
[System.IO.File]::WriteAllText($RuntimeVerify, $runtimeVerifyText, [System.Text.Encoding]::UTF8)
$runtimeVerifyItem = Get-Item -LiteralPath $RuntimeVerify
$copied += @{
    category = "runtime-input"
    source = (ConvertTo-RepoRelative -InputPath $SourceVerify)
    copied_to = (ConvertTo-RepoRelative -InputPath $RuntimeVerify)
    size_bytes = $runtimeVerifyItem.Length
    last_write_time = $runtimeVerifyItem.LastWriteTime.ToString("o")
}
$Verify = $RuntimeVerify

$argsList = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $Launcher,
    "-Port", "$Port",
    "-Map", $LauncherMap,
    "-Verify", $Verify,
    "-Python", $Python
)

$proc = Start-Process -FilePath "powershell" -ArgumentList $argsList -Wait -PassThru -NoNewWindow -RedirectStandardOutput $launcherStdout -RedirectStandardError $launcherStderr
$launcherExit = $proc.ExitCode

@{
    schemaVersion = 1
    run_id = $RunId
    started_at = $start.ToString("o")
    started_at_epoch = $startEpoch
    finished_at = (Get-Date).ToString("o")
    command = "powershell " + ($argsList -join " ")
    exit_code = $launcherExit
    map = (ConvertTo-RepoRelative -InputPath $LauncherMap)
    source_map = (ConvertTo-RepoRelative -InputPath $Map)
    verify = (ConvertTo-RepoRelative -InputPath $Verify)
    source_verify = (ConvertTo-RepoRelative -InputPath $SourceVerify)
    stdout = (ConvertTo-RepoRelative -InputPath $launcherStdout)
    stderr = (ConvertTo-RepoRelative -InputPath $launcherStderr)
} | ConvertTo-Json -Depth 8 | Set-Content -Path $launcherExitJson -Encoding UTF8

# If the launcher failed before writing the normal ScriptError verdict, still run a same-window scan.
$genericScriptError = Join-Path $GalaxyArtifacts "script-error-verdict.json"
if (-not (Test-Path -LiteralPath $genericScriptError)) {
    $stageScriptError = Join-Path $StageArtifacts "script-error-verdict.json"
    & $Python $ScriptErrorCheck --since $startEpoch --out $stageScriptError | Tee-Object -FilePath (Join-Path $StageArtifacts "script-error-check-stdout.txt")
}

foreach ($pair in @(
    @("assert-results.json", "assert-results.json", "runtime"),
    @("script-error-verdict.json", "script-error-verdict.json", "runtime"),
    @("vibe-verdict.json", "vibe-verdict.json", "runtime"),
    @("visual-verdict.json", "visual-verdict.json", "visual")
)) {
    $src = Join-Path $GalaxyArtifacts $pair[0]
    $entry = Copy-IfExists -Source $src -DestinationName $pair[1] -Category $pair[2]
    if ($entry) { $copied += $entry }
}

$stageScriptErrorExisting = Join-Path $StageArtifacts "script-error-verdict.json"
if (Test-Path -LiteralPath $stageScriptErrorExisting) {
    $entry = Copy-IfExists -Source $stageScriptErrorExisting -DestinationName "script-error-verdict-stage13.json" -Category "runtime"
    if ($entry) { $copied += $entry }
}

$entry = Copy-IfExists -Source $launcherStdout -DestinationName "launcher-stdout.txt" -Category "runtime"
if ($entry) { $copied += $entry }
$entry = Copy-IfExists -Source $launcherStderr -DestinationName "launcher-stderr.txt" -Category "runtime"
if ($entry) { $copied += $entry }
$entry = Copy-IfExists -Source $launcherExitJson -DestinationName "launcher-exit.json" -Category "runtime"
if ($entry) { $copied += $entry }
$entry = Copy-IfExists -Source $PackStdout -DestinationName "pack-sc2map-stdout.txt" -Category "static"
if ($entry) { $copied += $entry }
$entry = Copy-IfExists -Source $PackStderr -DestinationName "pack-sc2map-stderr.txt" -Category "static"
if ($entry) { $copied += $entry }
$entry = Copy-IfExists -Source $PackExitJson -DestinationName "pack-sc2map-exit.json" -Category "static"
if ($entry) { $copied += $entry }

$marker = Join-Path $env:USERPROFILE "Documents\StarCraft II\galaxy-vibe-launch.json"
$entry = Copy-IfExists -Source $marker -DestinationName "galaxy-vibe-launch.json" -Category "runtime"
if ($entry) { $copied += $entry }

$vibeVerdictPath = Join-Path $StageArtifacts "vibe-verdict.json"
$assertPath = Join-Path $StageArtifacts "assert-results.json"
$scriptErrorPath = Join-Path $StageArtifacts "script-error-verdict.json"
if (-not (Test-Path -LiteralPath $scriptErrorPath)) {
    $alternate = Join-Path $StageArtifacts "script-error-verdict-stage13.json"
    if (Test-Path -LiteralPath $alternate) { $scriptErrorPath = $alternate }
}

$vibeVerdict = $null
$assertVerdict = $null
$scriptErrorVerdict = $null
if (Test-Path -LiteralPath $vibeVerdictPath) { $vibeVerdict = Read-JsonUtf8 -Path $vibeVerdictPath }
if (Test-Path -LiteralPath $assertPath) { $assertVerdict = Read-JsonUtf8 -Path $assertPath }
if (Test-Path -LiteralPath $scriptErrorPath) { $scriptErrorVerdict = Read-JsonUtf8 -Path $scriptErrorPath }

$stdoutText = ""
if (Test-Path -LiteralPath $launcherStdout) { $stdoutText = Get-Content -Raw -LiteralPath $launcherStdout }
$stderrText = ""
if (Test-Path -LiteralPath $launcherStderr) { $stderrText = Get-Content -Raw -LiteralPath $launcherStderr }

$status = "failed"
$evidenceType = "runtime"
$reason = ""
$assertHasCurrentResults = $assertVerdict -and ([int]$assertVerdict.total -gt 0) -and [bool]$assertVerdict.all_passed
if ($launcherExit -eq 0 -and $vibeVerdict -and [bool]$vibeVerdict.passed -and $assertHasCurrentResults) {
    $status = "PASS"
} elseif ($stdoutText -match "never opened|never started|Could not locate|Map not found|Debug mod not found" -or $stderrText -match "never opened|never started|Could not locate|Map not found|Debug mod not found") {
    $status = "blocked-runtime-unavailable"
    $evidenceType = "blocked"
    $reason = "launcher could not reach a ready SC2 runtime"
} elseif ($launcherExit -ne 0 -and -not $vibeVerdict) {
    $status = "blocked-runtime-unavailable"
    $evidenceType = "blocked"
    $reason = "launcher exited nonzero before producing vibe-verdict.json"
} else {
    $reason = "launcher or runtime assertions failed or no current assert-results.json was produced"
}

$summary = @{
    schemaVersion = 1
    run_id = $RunId
    status = $status
    evidence_type = $evidenceType
    reason = $reason
    started_at = $start.ToString("o")
    started_at_epoch = $startEpoch
    finished_at = (Get-Date).ToString("o")
    launcher = @{
        command = "powershell " + ($argsList -join " ")
        exit_code = $launcherExit
        stdout = (ConvertTo-RepoRelative -InputPath $launcherStdout)
        stderr = (ConvertTo-RepoRelative -InputPath $launcherStderr)
    }
    inputs = @{
        manifest = "artifacts/projects/cmre-porting/stage12-vibe-task-manifest/manifest.json"
        live_task = "artifacts/projects/cmre-porting/stage12-vibe-task-manifest/task.live.json"
        runtime_recipe = "artifacts/projects/cmre-porting/stage12-vibe-task-manifest/runtime-recipe.json"
        vtest = (ConvertTo-RepoRelative -InputPath $Verify)
        source_vtest = (ConvertTo-RepoRelative -InputPath $SourceVerify)
        map = (ConvertTo-RepoRelative -InputPath $LauncherMap)
        source_map = (ConvertTo-RepoRelative -InputPath $Map)
        staged_map = (ConvertTo-RepoRelative -InputPath $StagedMap)
        packed_map = (ConvertTo-RepoRelative -InputPath $PackedMap)
    }
    assert = $assertVerdict
    script_error = $scriptErrorVerdict
    vibe_verdict = $vibeVerdict
    cleared_stale_outputs = $cleared
    copied_evidence = $copied
}

$summaryPath = Join-Path $StageArtifacts "runtime-summary.json"
$summary | ConvertTo-Json -Depth 20 | Set-Content -Path $summaryPath -Encoding UTF8

$bundleStdout = Join-Path $StageArtifacts "evidence-bundle-stdout.txt"
$bundleStderr = Join-Path $StageArtifacts "evidence-bundle-stderr.txt"
$bundleExitJson = Join-Path $StageArtifacts "evidence-bundle-exit.json"
$phaseStatus = @{
    runtime = $(if ($status -eq "PASS") { "passed" } elseif ($status -eq "blocked-runtime-unavailable") { "blocked" } else { "failed" })
    assertions = $(if ($assertHasCurrentResults) { "passed" } else { "failed" })
    script_error = $(if ($scriptErrorVerdict -and -not [bool]$scriptErrorVerdict.has_new_errors) { "passed" } elseif ($scriptErrorVerdict) { "failed" } else { "missing" })
}
$phaseStatusJson = $phaseStatus | ConvertTo-Json -Compress
$bundleArgs = @(
    $Bundler,
    "--run-id", $RunId,
    "--out-dir", $StageArtifacts,
    "--artifacts-dir", $StageArtifacts,
    "--phase-status", $phaseStatusJson
)
$bundleStart = Get-Date
$bundleExit = -1
if (Test-Path -LiteralPath $Bundler) {
    $bundleProc = Start-Process -FilePath $Python -ArgumentList $bundleArgs -Wait -PassThru -NoNewWindow -RedirectStandardOutput $bundleStdout -RedirectStandardError $bundleStderr
    $bundleExit = $bundleProc.ExitCode
} else {
    "missing bundler: $Bundler" | Set-Content -Path $bundleStderr -Encoding UTF8
}
$bundleDir = Join-Path $StageArtifacts "bundle-$RunId"
$bundleInfo = @{
    command = "$Python " + ($bundleArgs -join " ")
    exit_code = $bundleExit
    started_at = $bundleStart.ToString("o")
    finished_at = (Get-Date).ToString("o")
    bundle_dir = (ConvertTo-RepoRelative -InputPath $bundleDir)
    evidence_bundle = (ConvertTo-RepoRelative -InputPath (Join-Path $bundleDir "evidence-bundle.json"))
    manifest = (ConvertTo-RepoRelative -InputPath (Join-Path $bundleDir "manifest.json"))
    stdout = (ConvertTo-RepoRelative -InputPath $bundleStdout)
    stderr = (ConvertTo-RepoRelative -InputPath $bundleStderr)
}
$bundleInfo | ConvertTo-Json -Depth 8 | Set-Content -Path $bundleExitJson -Encoding UTF8
$summary["evidence_bundle"] = $bundleInfo
$summary | ConvertTo-Json -Depth 20 | Set-Content -Path $summaryPath -Encoding UTF8
Write-Host "Stage 13 runtime summary: $summaryPath"
Write-Host "Stage 13 status: $status"

if ($status -eq "PASS") { exit 0 }
if ($status -eq "blocked-runtime-unavailable") { exit 2 }
exit 1
