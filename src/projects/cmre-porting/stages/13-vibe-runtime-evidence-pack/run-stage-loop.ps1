<#
.SYNOPSIS
  Autonomous stage loop for CMRE Vibe runtime evidence.

.DESCRIPTION
  Executes the current stage, self-reviews the produced evidence, retries
  recoverable failures, records log/result/issues, and prepares Stage 14 only
  after Stage 13 runtime evidence passes its gate.
#>
[CmdletBinding()]
param(
    [string]$RunId = "stage13-loop",
    [int]$MaxIterations = 3,
    [int]$Port = 5000,
    [string]$Map = "",
    [string]$Verify = "",
    [string]$Python = "python",
    [switch]$DryRun,
    [switch]$ReviewOnly,
    [switch]$NoAdvance
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
        return $raw -replace "\\", "/"
    }
    if ($full.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $full.Substring($rootFull.Length).TrimStart("\") -replace "\\", "/"
    }
    return $raw -replace "\\", "/"
}

function Read-JsonUtf8 {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8) | ConvertFrom-Json
}

function Write-JsonUtf8 {
    param([string]$Path, [object]$Value, [int]$Depth = 20)
    $dir = Split-Path -Parent $Path
    if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $Value | ConvertTo-Json -Depth $Depth | Set-Content -Path $Path -Encoding UTF8
}

function Add-ReviewCheck {
    param(
        [System.Collections.ArrayList]$Checks,
        [string]$Id,
        [bool]$Passed,
        [string]$Detail,
        [string]$EvidenceType = "static"
    )
    [void]$Checks.Add([ordered]@{
        id = $Id
        passed = $Passed
        detail = $Detail
        evidence_type = $EvidenceType
    })
}

function Test-ReviewChecksPassed {
    param([System.Collections.ArrayList]$Checks)
    foreach ($check in $Checks) {
        if (-not [bool]$check.passed) { return $false }
    }
    return $true
}

function Invoke-Stage13Runtime {
    param([int]$Iteration)
    $iterationRunId = "$RunId-i$Iteration"
    $stdout = Join-Path $LoopDir "stage13-$iterationRunId-stdout.txt"
    $stderr = Join-Path $LoopDir "stage13-$iterationRunId-stderr.txt"
    $exitPath = Join-Path $LoopDir "stage13-$iterationRunId-exit.json"
    $args = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $Stage13RuntimeScript,
        "-RunId", $iterationRunId,
        "-Port", "$Port",
        "-Python", $Python
    )
    if ($Map) { $args += @("-Map", $Map) }
    if ($Verify) { $args += @("-Verify", $Verify) }
    $started = Get-Date
    if ($DryRun) {
        $record = [ordered]@{
            run_id = $iterationRunId
            dry_run = $true
            command = "powershell " + ($args -join " ")
            exit_code = 0
            stdout = ConvertTo-RepoRelative $stdout
            stderr = ConvertTo-RepoRelative $stderr
            started_at = $started.ToString("o")
            finished_at = (Get-Date).ToString("o")
        }
        Write-JsonUtf8 -Path $exitPath -Value $record
        return $record
    }
    $proc = Start-Process -FilePath "powershell" -ArgumentList $args -Wait -PassThru -NoNewWindow -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $record = [ordered]@{
        run_id = $iterationRunId
        dry_run = $false
        command = "powershell " + ($args -join " ")
        exit_code = $proc.ExitCode
        stdout = ConvertTo-RepoRelative $stdout
        stderr = ConvertTo-RepoRelative $stderr
        started_at = $started.ToString("o")
        finished_at = (Get-Date).ToString("o")
    }
    Write-JsonUtf8 -Path $exitPath -Value $record
    return $record
}

function Invoke-Stage13SelfReview {
    param([int]$Iteration, [object]$RuntimeRecord)
    $checks = [System.Collections.ArrayList]::new()
    $summaryPath = Join-Path $StageArtifacts "runtime-summary.json"
    $summary = Read-JsonUtf8 -Path $summaryPath

    Add-ReviewCheck $checks "runtime_summary_exists" ($null -ne $summary) "runtime-summary.json exists after stage execution" "runtime"
    if ($null -eq $summary) {
        return Write-ReviewResult -Iteration $Iteration -RuntimeRecord $RuntimeRecord -Checks $checks -Status "failed" -Reason "runtime-summary.json missing"
    }

    $summaryStatus = [string]$summary.status
    $isPass = $summaryStatus -eq "PASS"
    $isBlocked = $summaryStatus -eq "blocked-runtime-unavailable"
    Add-ReviewCheck $checks "terminal_status" ($isPass -or $isBlocked) "summary status is $summaryStatus" "runtime"

    if ($isPass) {
        Add-ReviewCheck $checks "runtime_evidence_type" ([string]$summary.evidence_type -eq "runtime") "PASS must be classified as runtime evidence" "runtime"
        Add-ReviewCheck $checks "launcher_exit_zero" ([int]$summary.launcher.exit_code -eq 0) "launcher exit code is $($summary.launcher.exit_code)" "runtime"
        Add-ReviewCheck $checks "assertions_current_and_passed" ($summary.assert -and [int]$summary.assert.total -gt 0 -and [bool]$summary.assert.all_passed) "assert-results total=$($summary.assert.total), all_passed=$($summary.assert.all_passed)" "runtime"
        Add-ReviewCheck $checks "script_error_clean" ($summary.script_error -and -not [bool]$summary.script_error.has_new_errors) "script_error.has_new_errors=$($summary.script_error.has_new_errors)" "runtime"
        $bundlePath = Join-Path $RepoRoot ([string]$summary.evidence_bundle.evidence_bundle)
        Add-ReviewCheck $checks "evidence_bundle_exists" (Test-Path -LiteralPath $bundlePath) "evidence bundle path: $($summary.evidence_bundle.evidence_bundle)" "runtime"
        Add-ReviewCheck $checks "stage12_inputs_copied" (($summary.copied_evidence | Where-Object { [string]$_.category -eq "static-input" }).Count -ge 4) "Stage 12 static inputs copied into Stage 13 artifacts" "static"
    } elseif ($isBlocked) {
        Add-ReviewCheck $checks "blocked_reason_recorded" (-not [string]::IsNullOrWhiteSpace([string]$summary.reason)) "blocked reason: $($summary.reason)" "blocked"
        Add-ReviewCheck $checks "blocked_not_mislabeled_runtime_pass" ([string]$summary.evidence_type -eq "blocked") "blocked evidence type is $($summary.evidence_type)" "blocked"
    }

    $reviewPassed = Test-ReviewChecksPassed -Checks $checks
    $reviewStatus = if ($reviewPassed -and $isPass) { "PASS" } elseif ($reviewPassed -and $isBlocked) { "BLOCKED" } else { "FAILED" }
    $reason = if ($reviewStatus -eq "PASS") { "Stage 13 runtime evidence passed self-review" } elseif ($reviewStatus -eq "BLOCKED") { "Runtime unavailable but blocker is recorded" } else { "Self-review checks failed" }
    return Write-ReviewResult -Iteration $Iteration -RuntimeRecord $RuntimeRecord -Checks $checks -Status $reviewStatus -Reason $reason -Summary $summary
}

function Write-ReviewResult {
    param(
        [int]$Iteration,
        [object]$RuntimeRecord,
        [System.Collections.ArrayList]$Checks,
        [string]$Status,
        [string]$Reason,
        [object]$Summary = $null
    )
    $review = [ordered]@{
        schemaVersion = 1
        run_id = $RunId
        iteration = $Iteration
        status = $Status
        reason = $Reason
        reviewed_at = (Get-Date).ToString("o")
        runtime_record = $RuntimeRecord
        runtime_summary = if ($Summary) { ConvertTo-RepoRelative (Join-Path $StageArtifacts "runtime-summary.json") } else { "" }
        checks = @($Checks)
    }
    $path = Join-Path $LoopDir "self-review-i$Iteration.json"
    Write-JsonUtf8 -Path $path -Value $review
    return $review
}

function Write-Stage13State {
    param([object]$Review)
    $summary = Read-JsonUtf8 -Path (Join-Path $StageArtifacts "runtime-summary.json")
    $now = (Get-Date).ToString("o")
    $status = if ($Review.status -eq "PASS") { "PASS" } elseif ($Review.status -eq "BLOCKED") { "BLOCKED_RUNTIME_UNAVAILABLE" } else { "FAILED" }
    $result = [ordered]@{
        stage_id = "13-vibe-runtime-evidence-pack"
        schemaVersion = 1
        status = $status
        current_phase = if ($status -eq "PASS") { "runtime evidence verified and self-reviewed" } elseif ($status -like "BLOCKED*") { "runtime unavailable; blocker recorded" } else { "self-review failed" }
        opened_at = "2026-07-31T22:24:46+08:00"
        updated_at = $now
        closed_at = if ($status -eq "PASS") { $now } else { $null }
        direction = "Consume Stage 12 live runtime contract through the compliant launcher and advance only after self-review."
        verification_results = [ordered]@{
            stage_loop = [ordered]@{
                result = $Review.status
                evidence_type = if ($status -eq "PASS") { "runtime" } elseif ($status -like "BLOCKED*") { "blocked" } else { "static+runtime" }
                self_review = ConvertTo-RepoRelative (Join-Path $LoopDir "self-review-i$($Review.iteration).json")
            }
            runtime_summary = [ordered]@{
                result = if ($summary) { $summary.status } else { "missing" }
                evidence_type = if ($summary) { $summary.evidence_type } else { "missing" }
                artifact = ConvertTo-RepoRelative (Join-Path $StageArtifacts "runtime-summary.json")
            }
        }
        changed_paths = @(
            "src/projects/cmre-porting/stages/13-vibe-runtime-evidence-pack/run-stage-loop.ps1",
            "src/projects/cmre-porting/stages/13-vibe-runtime-evidence-pack/result.json",
            "src/projects/cmre-porting/stages/13-vibe-runtime-evidence-pack/issues.json",
            "src/projects/cmre-porting/stages/13-vibe-runtime-evidence-pack/log.md",
            "artifacts/projects/cmre-porting/stage13-vibe-runtime-evidence-pack/**"
        )
        open_followups = @()
        note = "Stage loop result is generated by run-stage-loop.ps1 after execution and self-review."
    }
    if ($status -eq "PASS") {
        $result.open_followups += "Proceed to Stage 14 AI ally strategy upgrade with replay/minimap review outputs."
    } elseif ($status -like "BLOCKED*") {
        $result.open_followups += "Resolve runtime availability before Stage 14 live claims."
    } else {
        $result.open_followups += "Inspect self-review failure and rerun stage loop."
    }
    Write-JsonUtf8 -Path (Join-Path $StageDir "result.json") -Value $result

    $issues = [ordered]@{
        stage_id = "13-vibe-runtime-evidence-pack"
        schemaVersion = 1
        issues = @(
            [ordered]@{
                id = "VIBE-RUNTIME-EVIDENCE-001"
                severity = "high"
                status = if ($status -eq "PASS") { "resolved" } elseif ($status -like "BLOCKED*") { "blocked-runtime-unavailable" } else { "open-failed-self-review" }
                title = "Stage 12 live runtime contract converted to Stage 13 runtime evidence"
                detail = if ($status -eq "PASS") { "Compliant launcher, assertions, ScriptError gate, and evidence bundle passed self-review." } elseif ($status -like "BLOCKED*") { "Runtime is unavailable or launcher did not produce PASS; blocker reason is recorded in runtime-summary.json." } else { "Stage loop self-review failed; next stage must not be advanced." }
                evidence_type = if ($status -eq "PASS") { "runtime" } elseif ($status -like "BLOCKED*") { "blocked" } else { "static+runtime" }
                evidence = ConvertTo-RepoRelative (Join-Path $LoopDir "self-review-i$($Review.iteration).json")
            },
            [ordered]@{
                id = "AI-ALLY-STRATEGY-PLAN-001"
                severity = "medium"
                status = if ($status -eq "PASS") { "ready-for-stage14" } else { "planned" }
                title = "AI ally x Dead of Night next milestone plan is defined"
                detail = "Stage 14 targets defensive co-op AI MVP+ with decision tree, economy, dynamic composition, tactics, synthetic/simulator/live gates, and replay/minimap review pack."
                evidence_type = "static"
                plan = "src/projects/cmre-porting/stages/13-vibe-runtime-evidence-pack/ai-ally-dead-of-night-plan.md"
            }
        )
    }
    Write-JsonUtf8 -Path (Join-Path $StageDir "issues.json") -Value $issues
    Add-StageLog -Review $Review -StageStatus $status
}

function Add-StageLog {
    param([object]$Review, [string]$StageStatus)
    $logPath = Join-Path $StageDir "log.md"
    $lines = @(
        "",
        "## Stage loop self-review - $((Get-Date).ToString("o"))",
        "",
        "- loop_run_id: $RunId",
        "- iteration: $($Review.iteration)",
        "- review_status: $($Review.status)",
        "- stage_status: $StageStatus",
        "- reason: $($Review.reason)",
        "- self_review: $(ConvertTo-RepoRelative (Join-Path $LoopDir "self-review-i$($Review.iteration).json"))",
        "- runtime_summary: $(ConvertTo-RepoRelative (Join-Path $StageArtifacts "runtime-summary.json"))"
    )
    Add-Content -Path $logPath -Value $lines -Encoding UTF8
}

function Initialize-Stage14AfterPass {
    param([object]$Review)
    if ($NoAdvance) { return }
    $stage14Dir = Join-Path (Split-Path -Parent $StageDir) "14-ai-ally-strategy-upgrade"
    New-Item -ItemType Directory -Force -Path $stage14Dir | Out-Null
    $stage14Plan = Join-Path $stage14Dir "plan.md"
    if (-not (Test-Path -LiteralPath $stage14Plan)) {
        @(
            "# Stage Plan: AI ally strategy upgrade",
            "",
            "> Created by Stage 13 self-review loop after runtime evidence PASS.",
            "> Goal: deliver Dead of Night defensive co-op AI MVP+ with replay/minimap human review.",
            "",
            "## Scope",
            "",
            "1. Upgrade DefendBasePolicy into an inspectable decision tree.",
            "2. Add macro scheduler lanes for workers, supply, combat production, recovery, and fallback.",
            "3. Add phase-aware composition profiles and tactical squad behavior.",
            "4. Produce simulator and live replay review packs: replay.jsonl, timeline.json, minimap frames, and review.html or review.md.",
            "5. Validate through synthetic policy tests, simulator 1500/3500, live launcher/API 1500/3500, and ScriptError gate.",
            "",
            "## Acceptance",
            "",
            "- policy tests PASS.",
            "- simulator 1500/3500 PASS with replay review pack.",
            "- live 1500/3500 PASS with launcher ready signal, no new ScriptError, and replay review pack.",
            "- Human review artifact answers whether defense timing, retreats, economy fallback, and target choices are reasonable.",
            "- result.json, issues.json, and log.md are updated before the stage closes."
        ) | Set-Content -Path $stage14Plan -Encoding UTF8
    }
    $stage14Log = Join-Path $stage14Dir "log.md"
    if (-not (Test-Path -LiteralPath $stage14Log)) {
        @(
            "# Stage 14 Log: AI ally strategy upgrade",
            "",
            "> Status: PLANNED",
            "> Created automatically after Stage 13 self-review PASS."
        ) | Set-Content -Path $stage14Log -Encoding UTF8
    }
    $stage14Issues = Join-Path $stage14Dir "issues.json"
    if (-not (Test-Path -LiteralPath $stage14Issues)) {
        Write-JsonUtf8 -Path $stage14Issues -Value ([ordered]@{
            stage_id = "14-ai-ally-strategy-upgrade"
            schemaVersion = 1
            issues = @(
                [ordered]@{
                    id = "AI-ALLY-STRATEGY-001"
                    severity = "high"
                    status = "open"
                    title = "Defensive AI MVP+ not yet implemented"
                    detail = "Implement decision tree, macro scheduler, dynamic composition, squad tactics, and replay/minimap review outputs."
                    evidence_type = "static"
                }
            )
        })
    }
    $stage14Result = Join-Path $stage14Dir "result.json"
    if (-not (Test-Path -LiteralPath $stage14Result)) {
        Write-JsonUtf8 -Path $stage14Result -Value ([ordered]@{
            stage_id = "14-ai-ally-strategy-upgrade"
            schemaVersion = 1
            status = "PLANNED"
            current_phase = "ready to implement after Stage 13 PASS"
            opened_at = (Get-Date).ToString("o")
            prerequisites = @(
                "Stage 13 runtime evidence PASS",
                "Stage 13 self-review PASS"
            )
        })
    }
    $project = Read-JsonUtf8 -Path $ProjectJson
    if ($project) {
        $project.currentStage = "14-ai-ally-strategy-upgrade"
        $project.writeScope = @(
            "src/projects/cmre-porting/project.json",
            "src/projects/cmre-porting/stages/14-ai-ally-strategy-upgrade/**",
            "src/projects/cmre-porting/vibe/defend_policy.py",
            "src/projects/cmre-porting/vibe/run_dead_of_night.py",
            "src/projects/cmre-porting/vibe/run_dead_of_night_live.py",
            "artifacts/projects/cmre-porting/stage14-ai-ally-strategy-upgrade/**"
        )
        Write-JsonUtf8 -Path $ProjectJson -Value $project
    }
    Add-Content -Path (Join-Path $StageDir "log.md") -Value @(
        "",
        "## Stage 14 prepared",
        "",
        "- stage14_plan: $(ConvertTo-RepoRelative $stage14Plan)",
        "- project_currentStage: 14-ai-ally-strategy-upgrade",
        "- prepared_at: $((Get-Date).ToString("o"))"
    ) -Encoding UTF8
}

$ScriptPath = $MyInvocation.MyCommand.Path
$StageDir = Split-Path -Parent $ScriptPath
$RepoRoot = (Resolve-Path (Join-Path $StageDir "..\..\..\..\..")).Path
$StageArtifacts = Join-Path $RepoRoot "artifacts\projects\cmre-porting\stage13-vibe-runtime-evidence-pack"
$LoopDir = Join-Path $StageArtifacts "loop-$RunId"
$Stage13RuntimeScript = Join-Path $StageDir "run-stage13-runtime-evidence.ps1"
$ProjectJson = Join-Path $RepoRoot "src\projects\cmre-porting\project.json"

New-Item -ItemType Directory -Force -Path $StageArtifacts, $LoopDir | Out-Null

if ($DryRun) {
    $dryRunRecord = [ordered]@{
        schemaVersion = 1
        run_id = $RunId
        dry_run = $true
        max_iterations = $MaxIterations
        would_execute = ConvertTo-RepoRelative $Stage13RuntimeScript
        port = $Port
        map = $Map
        verify = $Verify
        python = $Python
        no_advance = [bool]$NoAdvance
        generated_at = (Get-Date).ToString("o")
        note = "DryRun validates the stage-loop entrypoint without running SC2 or mutating stage result/issues/log."
    }
    Write-JsonUtf8 -Path (Join-Path $LoopDir "stage-loop-dry-run.json") -Value $dryRunRecord
    Write-Host "Stage loop dry run written: $(ConvertTo-RepoRelative (Join-Path $LoopDir "stage-loop-dry-run.json"))"
    exit 0
}

$history = [System.Collections.ArrayList]::new()
$terminalReview = $null
for ($iteration = 1; $iteration -le $MaxIterations; $iteration++) {
    Write-Host "Stage loop iteration $iteration/$MaxIterations"
    $runtimeRecord = Invoke-Stage13Runtime -Iteration $iteration
    $review = Invoke-Stage13SelfReview -Iteration $iteration -RuntimeRecord $runtimeRecord
    [void]$history.Add($review)
    $terminalReview = $review
    if ($review.status -eq "PASS" -or $review.status -eq "BLOCKED") {
        break
    }
}

$loopSummary = [ordered]@{
    schemaVersion = 1
    run_id = $RunId
    max_iterations = $MaxIterations
    final_status = $terminalReview.status
    final_reason = $terminalReview.reason
    generated_at = (Get-Date).ToString("o")
    history = @($history)
}
Write-JsonUtf8 -Path (Join-Path $LoopDir "stage-loop-summary.json") -Value $loopSummary

Write-Stage13State -Review $terminalReview
if ($terminalReview.status -eq "PASS") {
    Initialize-Stage14AfterPass -Review $terminalReview
    Write-Host "Stage 13 self-review PASS; Stage 14 prepared unless -NoAdvance was set."
    exit 0
}
if ($terminalReview.status -eq "BLOCKED") {
    Write-Host "Stage 13 blocked with recorded runtime evidence blocker."
    exit 2
}
Write-Host "Stage 13 self-review failed after $MaxIterations iteration(s)."
exit 1
