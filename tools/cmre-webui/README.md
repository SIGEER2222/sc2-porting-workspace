# SC2 Map Runtime WebUI

这个工具把地图作为只读输入，在每次会话的 `artifacts/` 下生成临时
`GalaxyVibeDebugRuntime.SC2Mod`。WebUI 勾选的 Mod 会写入这个 shim 的
`DocumentInfo`，由 SC2 在该次启动中按运行时依赖加载；不会修改地图或已安装 Mod。

## 启动

在工作区根目录执行：

```powershell
.\tools\cmre-webui\start-map-debug-webui.ps1 `
  -Map 'artifacts/projects/cmre-porting/stage26-full-function-invoke/input-map-original.SC2Map' `
  -Sc2Root 'E:\SC2\SC2new\StarCraft II' `
  -Port 8773
```

浏览器打开 `http://127.0.0.1:8773/`，勾选 Mod 后可以先生成 shim，或填写验证场景并启动 SC2。

也可以直接使用脚本生成 shim，不启动 WebUI：

```powershell
python tools/cmre-webui/debug_map_runtime.py `
  --map artifacts/projects/cmre-porting/stage26-full-function-invoke/input-map-original.SC2Map `
  --sc2-root 'E:\SC2\SC2new\StarCraft II' `
  --prepare `
  --mods Mods/Commanders/EmpireAlenger.SC2Mod,Mods/Commanders/EmpireAlengerAdapter.SC2Mod
```

Mod ID 必须是 SC2 安装目录下的 `Mods/` 相对路径。地图原始压缩包会自动解包到
`artifacts/projects/cmre-porting/stage26-full-function-invoke/map-debug-runtime/extracted/`。
启动证据、shim 和 launcher 日志都保存在同一 artifacts 区域。

## API

- `GET /api/manifest`：地图哈希、解包位置和声明依赖。
- `GET /api/mods`：当前 SC2 安装可映射的 Mod 清单。
- `POST /api/prepare`：请求体 `{ "mods": ["Mods/Example.SC2Mod"] }`。
- `POST /api/launch`：在上述请求体基础上增加 `port` 和可选 `verify`。
- `GET /api/status`：最近一次 launcher 的状态和日志尾部。

斗蛐蛐运行时 VM 的启动、调用、日志和静态/runtime 证据边界见
[`DOUQUQU_RUNTIME.md`](DOUQUQU_RUNTIME.md)。
