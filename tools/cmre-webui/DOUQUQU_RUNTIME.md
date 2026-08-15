# 斗蛐蛐 Runtime VM

斗蛐蛐插件的开发入口是实时 `function.invoke`，不是静态 Catalog/Event 注入。启动时只把 Vibe kernel 和 `LibDouQuquRuntime.galaxy` 挂到本次 staged copy；单位和效果只有收到 runtime 调用后才会在当前 SC2 会话中发生。

## 启动

使用批准的 WebUI/launcher 入口：

```powershell
.\tools\cmre-webui\start-dou-ququ-runtime.ps1 `
  -Map "<斗蛐蛐原图或解包目录>" `
  -WebPort 8777 `
  -ApiPort 5896 `
  -AutoLaunch
```

浏览器进入 `http://127.0.0.1:8777/` 的“运行时调试”页即可连接、选择函数并查看实时观测。

## 直接调用

函数目录：

```powershell
curl.exe http://127.0.0.1:8777/api/vibe/catalog
```

单个 runtime 函数：

```powershell
$body = @{
  functionId = "douququ.unit.spawn"
  args = @{ unit_type = "Reaver"; owner = 1; x = 20.0; y = 20.0 }
} | ConvertTo-Json -Depth 10

curl.exe -X POST http://127.0.0.1:8777/api/vibe/invoke `
  -H "Content-Type: application/json" `
  --data-binary $body
```

返回中的 `record.result` 是 SC2 runtime 返回值；`record.status=passed` 只表示该函数在当前 SC2 session 返回 `error_code=OK`。

## 运行时 VM 程序

VM 入口是 `POST /api/vibe/run-vm`，程序格式为 `vibe-debug/1`：

```powershell
$program = Get-Content .\tools\cmre-webui\dou_ququ_runtime_full.json -Raw | ConvertFrom-Json
$request = @{ program = $program } | ConvertTo-Json -Depth 30
curl.exe -X POST http://127.0.0.1:8777/api/vibe/run-vm `
  -H "Content-Type: application/json" `
  --data-binary $request
```

`steps` 支持 `call`、`repeat`、`assert`；`call` 的 `save` 和 `{"$ref":"vars.name.tag"}` 可用于串联单位 tag。WebUI 的 VM 编辑器提交的也是同一个接口和 schema。

## 函数执行日志

每次真实 runtime function call 都追加到：

```text
artifacts/projects/cmre-porting/stage27-dou-ququ-behavior-plugin/runtime/douququ-runtime-vm-call-log.jsonl
```

也可通过只读接口读取最近记录：

```powershell
curl.exe "http://127.0.0.1:8777/api/vibe/call-log?limit=200"
curl.exe http://127.0.0.1:8777/api/vibe/trace
```

每条 call 记录包含 `timestamp`、`session_id`、`port`、`origin`（`api`/`vm`/`connect`）、`function_id`、`args`、`result`、`error`、状态和耗时。连接握手的 `douququ.runtime.status` 也会记录，便于区分用户调用和 VM 调用。

作者弹窗清理只作用于 `artifacts/` 下的运行副本；原始 `.SC2Map` 不会被修改，也不计入 runtime 效果验证。真实效果验证必须以 `/api/vibe/invoke` 或 `/api/vibe/run-vm` 返回的 SC2 runtime 结果和对应 JSONL 记录为准。
