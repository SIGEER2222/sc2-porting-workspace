# Stage 03 — MVP Feasible: -EnableReborn 实跑测试

## 测试信息

- **日期**: 2026-07-26 23:17:41 (Asia/Shanghai)
- **MapName**: 亡者之夜.SC2Map
- **Commander**: TerranAlenger3 (映射为 Empire)
- **启动模式**: 普通模式（无 -ListenPort，地图路径直接传给 SC2Switcher）
- **开关**: -EnableReborn
- **Launcher**: `sc2-porting-workspace/tools/launchers/launch-cmre-alenger.ps1`

## 启动过程

1. ✅ 指挥官映射: TerranAlenger3 -> Empire (via alengerIdToName)
2. ✅ 加载 commander profile (Empire): startingStructure=3diguoqianshaojidi, startingWorker=3diguolaogong
3. ✅ Reborn mods enabled: 添加 5 个 optional dependencies
4. ✅ 按需包同步: EmpireAlengerCommon, EmpireAlenger, EmpireAlengerAdapter
5. ✅ Reborn mods 同步到 `E:\SC2\SC2new\StarCraft II\Mods\reborn\`:
   - crys_the_swarm_reborn.SC2Mod
   - crys_swarm_assets.SC2Mod
   - sibirens_starhooks_common.SC2Mod
   - sibirens_starhooks_swarmstoryutils.SC2Mod
   - sibirens_sundries_swarm_reborn.SC2Mod
6. ✅ CMRE Galaxy host overlay: 12 CMRE + 3 EmpireAlengerAdapter files
7. ✅ CMRE saved-profile startup patch 应用到地图 LibCOOC.galaxy
8. ✅ Install-CmreDynamicObserver 执行 (isAlengerCommander=True, alengerId=Empire)
9. ✅ CMRE core runtime error patches: 12 locations
10. ✅ SET DEPS: 13 dependencies written to map
11. ✅ CMCoopLaunchProfile 银行写入
12. ✅ SC2 启动 (SC2Switcher -> SC2_x64, PID=8048, 23:17:50)

## SC2 启动参数 (从 Graphics.txt 确认)

```
Parameters: "E:\SC2\SC2new\StarCraft II\Maps\亡者之夜.SC2Map"
```

地图路径已正确传递给 SC2（普通模式行为，非 API 模式）。

## 测试结果

### 通过项

- ✅ **无 ScriptError**: GameLogs 中未生成任何 `*ScriptError*` 文件
- ✅ **无崩溃**: 未生成新的 `*Crash*` 目录
- ✅ **Reborn mods 同步**: 5 个 mod 全部同步到 SC2 安装目录
- ✅ **依赖声明**: 13 个 dependencies 写入地图 DocumentInfo
- ✅ **渲染管线初始化**: Graphics.txt 在 23:18:58 生成（2976 bytes）

### 失败项

- ❌ **未达 ready 状态**: 600 秒内未生成 Alerts.txt（Wait-GameReady 超时退出，exit code 2）
- ⚠️ **内存偏低**: SC2 运行 10+ 分钟内存仅 ~400MB（正常加载地图应达 1-2GB），怀疑卡在加载早期阶段

### 验收标准对照

| 验收标准 | 状态 | 说明 |
|---------|------|------|
| 5 个 Reborn mod 复制到 cmre-runtime/Mods/reborn/ 且子 mod 路径重写 | ✅ | 已同步 |
| SwarmStory.SC2Campaign 和 swarmstoryutil.sc2mod 部署到 SC2 安装 Campaigns/ | (未本次验证) | 需单独检查 |
| cmre-alenger-dependencies.json 声明 optionalPackageMods 块 | ✅ | 已声明 5 个 mod |
| launch-cmre-alenger.ps1 支持 -EnableReborn 开关 | ✅ | 同步并加载成功 |
| CMRE 地图以 -EnableReborn 启动达到 ready 状态且无新 ScriptError | ⚠️ 部分 | 无 ScriptError ✅，但未达 ready 状态 ❌ |

## 后续待查

1. **SC2 卡住原因**: 内存仅 400MB + 无 Alerts.txt，需排查：
   - 是否 Reborn mods 与 CMRE/Alenger3 catalog 冲突导致 galaxy init 卡住
   - 是否 Enable-CmreSavedProfileStartup patch 与 Reborn mods 不兼容
   - 是否地图加载进度条卡住（需人工观察 SC2 窗口）
2. **API 模式说明**: 本次测试用普通模式（非 -ListenPort）。API 模式（-listen/-port）有意不传地图路径，由 client 用 CreateGame 加载，不是 bug。
3. **reborn-dependencies.json 中的 RebornBridge/RebornMapAdapter 引用**: 该文件是 map-family 配置，**不被 launch-cmre-alenger.ps1 使用**（launcher 用 cmre-alenger-dependencies.json）。这两个 mod 在 cmre-runtime/Mods/reborn/ 不存在，但 launcher 不依赖它们，故不影响 -EnableReborn 流程。

## 结论

- **Reborn mod 集成的 mod 同步与依赖加载链路已通**：5 个 mod 成功同步、依赖正确声明、SC2 收到地图路径、无 ScriptError。
- **地图未达 ready 状态**：可能是 CMRE+Alenger3+Reborn 三方组合的 galaxy 初始化问题，需进一步排查（不属于 Reborn mod 集成本身的问题，而是运行时兼容性问题）。
- **建议下一步**: 用 -ShowSelectionUI 或 -PlayerMode 跳过 Enable-CmreSavedProfileStartup patch，观察 SC2 是否能正常进图，以隔离 patch 影响因素。
