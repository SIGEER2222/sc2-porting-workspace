[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$Map = $env:DOU_QUQU_MAP,

    [ValidateRange(1, 65535)]
    [int]$WebPort = 8773,

    [ValidateRange(1024, 65535)]
    [int]$ApiPort = 5869,

    [string]$Python = "python",
    [switch]$NoBrowser,
    [switch]$AutoLaunch
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if ([string]::IsNullOrWhiteSpace($Map)) {
    throw "请用 -Map 指定斗蛐蛐 .SC2Map 原图或解包目录，或设置 DOU_QUQU_MAP"
}
$mapPath = (Resolve-Path -LiteralPath $Map -ErrorAction Stop).Path
$server = Join-Path $PSScriptRoot "server.py"
$pythonCommand = Get-Command $Python -ErrorAction Stop
$url = "http://127.0.0.1:$WebPort"
$logRoot = Join-Path $repo "artifacts\projects\cmre-porting\stage27-dou-ququ-behavior-plugin\runtime"
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null

$args = @(
    $server,
    "--host", "127.0.0.1",
    "--port", "$WebPort",
    "--dou-ququ-map", $mapPath,
    "--no-browser"
)

if (-not $AutoLaunch) {
    Write-Host "斗蛐蛐 runtime WebUI: $url"
    Write-Host "地图只读输入: $mapPath"
    Write-Host "浏览器进入运行时调试页后，启动 API 模式并连接 Vibe。"
    Push-Location $repo
    try { & $pythonCommand.Source @args; exit $LASTEXITCODE } finally { Pop-Location }
}

$stdoutPath = Join-Path $logRoot "webui-runtime.stdout.log"
$stderrPath = Join-Path $logRoot "webui-runtime.stderr.log"
$serverProcess = Start-Process -FilePath $pythonCommand.Source -ArgumentList $args -WorkingDirectory $repo -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru
try {
    $ready = $false
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    while ([DateTime]::UtcNow -lt $deadline) {
        $tcp = New-Object System.Net.Sockets.TcpClient
        try {
            $task = $tcp.ConnectAsync("127.0.0.1", $WebPort)
            if ($task.Wait(250) -and $tcp.Connected) { $ready = $true; break }
        } finally { $tcp.Dispose() }
        if ($serverProcess.HasExited) { throw "WebUI server exited: $($serverProcess.ExitCode)" }
    }
    if (-not $ready) { throw "WebUI did not open port $WebPort within 30 seconds" }
    $body = @{
        commander = "ProtossAlarak"
        mapName = (Split-Path -Leaf $mapPath)
        mapPackage = "dou-ququ"
        apiMode = $true
        listenPort = $ApiPort
         apiMinimal = $true
         enableDouQuquBehavior = $false
         enableDouQuquRuntime = $true
     } | ConvertTo-Json -Depth 6
    $response = Invoke-RestMethod -Uri "$url/api/launch-async" -Method Post -ContentType "application/json" -Body $body
    Write-Host "斗蛐蛐 runtime WebUI: $url"
    Write-Host "SC2 API 端口: $ApiPort"
    Write-Host "launcher 请求: $($response.success)"
    Write-Host "服务 PID: $($serverProcess.Id)；日志: $stdoutPath"
    Start-Process $url
} catch {
    if (-not $serverProcess.HasExited) { Stop-Process -Id $serverProcess.Id -Force }
    throw
}
