<#
.SYNOPSIS
  SC2 Simulator-First Vibe Platform 统一入口。
.DESCRIPTION
  本入口仅调用本地 Python + sc2_simulator（headless），绝不启动 SC2。
  真实-SC2 backend (sc2) 是 P9 可选适配器，本地不实现。
.PARAMETER Action
  probe    - 离线 P1 闸门自测（SimulatorTransport 协议层 + 确定性 trace 哈希）
  run-task - 执行一个 task.json，产出证据包到 artifacts/galaxy-vibe/<task_id>/
.EXAMPLE
  .\tools\launchers\vibe.ps1 probe
  .\tools\launchers\vibe.ps1 run-task -Task artifacts/galaxy-vibe/tasks/p1-smoke.json
#>
param(
  [Parameter(Position=0, Mandatory=$true)]
  [ValidateSet("probe","run-task")]
  [string]$Action,

  [Parameter()]
  [string]$Task,

  [Parameter()]
  [string]$Project = "cmre-porting",

  [Parameter()]
  [ValidateSet("simulator","sc2")]
  [string]$Backend = "simulator"
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path "$PSScriptRoot\..\.."
$py = "python"

if ($Backend -eq "sc2") {
  Write-Error "Backend 'sc2' 是 P9 可选真实-SC2 适配器，本地不实现。用 -Backend simulator。"
  exit 2
}

# 把 src/projects/cmre-porting 加入 PYTHONPATH 使 vibe 包可 import
$env:PYTHONPATH = "$repoRoot\src\projects\cmre-porting;$env:PYTHONPATH"

switch ($Action) {
  "probe" {
    & $py -c "from vibe.simulator_transport import p1_selftest; import json; r=p1_selftest(); print(json.dumps(r,indent=2,ensure_ascii=False)); import sys; sys.exit(0 if r['passed'] else 1)"
    exit $LASTEXITCODE
  }
  "run-task" {
    if (-not $Task) { Write-Error "run-task 需要 -Task <task.json>"; exit 2 }
    & $py -c "from vibe.task_runner import run_task; import json,sys; r=run_task(r'$Task'); print(json.dumps(r,indent=2,ensure_ascii=False)); sys.exit(0 if r['verdict']=='PASS' else 1)"
    exit $LASTEXITCODE
  }
}
