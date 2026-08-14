# Stage 26 Log: Full Function Invoke Expansion

## Archived History

Earlier Stage 26 entries, including the 2026-08-06 through 2026-08-12
function-invoke, launcher, and WebUI evidence, are retained in
`archive/log-2026-08-13.md`. This active log keeps the latest evidence after
the rotation required by the stage evidence policy.

## 2026-08-13

### WebUI 指挥官/地图分组与 Mod 按需加载 PASS

- `static`：`tools/cmre-webui/webui/app.js` 将指挥官按 `official`、`alenger`、
  `reborn`、`revolution-overdrive` 分组，将地图按 `cmre`、`reborn`、
  `revolution-overdrive` 分组；中文分组标题和数量由 API 数据渲染，内部 ID 只用于
  选择与启动。高级选项关闭时不请求 `/api/extra-mods`；只有展开高级选项或点击
  `读取列表` 后，才按当前指挥官 bank 请求可选 Mod，切换指挥官时清空旧选择并用请求
  ID 防止旧响应覆盖新指挥官。
- `static`：`python -m pytest -q tools/cmre-webui` -> 27 passed；
  `node --check tools/cmre-webui/webui/app.js` 和 `git diff --check` 通过。
- `runtime/browser`：重启 `http://127.0.0.1:8767/` 后使用独立 Edge CDP 实际导航和点击。
  初始 DOM 显示 4 个指挥官分组、50 个指挥官卡片和 3 个地图分组、66 个地图卡片，
  高级选项初始隐藏；初始化 `/api/extra-mods` 请求 0 次。点击高级选项后请求
  `/api/extra-mods?commander=Raynor` 并渲染 34 个 Mod 项，`onDemandVerified=true`。
- `runtime/browser evidence`：
  `artifacts/projects/cmre-porting/stage26-full-function-invoke/runtime/webui-grouped-mod-on-demand-20260813/grouped-mod-on-demand.json`；
  `.../grouped-mod-on-demand.png`；验证脚本为同目录 `verify-webui-grouped-mods.mjs`。
- `runtime`：重启后的 WebUI PID 为 19976，首页 HTTP 200，SC2 进程数为 0；脚本和样式
  缓存版本为 `v13`。

### WebUI map preview images PASS

- `static`：三个地图源共 66 张地图均有真实图片资产：CMRE 15 张继续使用已有预览图；
  虫心 20 张和起义狂潮 31 张改用从本机 SC2 CASC 提取的官方宽幅加载画面 DDS。
  外部地图源保持只读，WebUI 资源路由对 `Minimap.tga` 路径 fail-closed 拒绝。
- `runtime/browser`：重启用户指定的 `http://127.0.0.1:8767/` 后，真实 Edge/Chromium
  CDP 交互点击地图标签并滚动地图列表，66/66 图片 `complete` 且
  `naturalWidth>0`，占位 0，Minimap 路径 0；虫心和起义狂潮宽幅加载画面 51/51。
  三个实际滚动视口截图显示任务场景/星球/战役加载画面，不再是地形缩略图。证据位于
  `artifacts/projects/cmre-porting/stage26-full-function-invoke/runtime/webui-map-preview-wide-20260813/`，
  CASC 白名单位于 `src/projects/cmre-porting/stages/26-full-function-invoke/map-preview-casc-files.txt`。

### Reborn Abathur Larva card parity gate

- `static`：`generate_reborn_abathur_baseline.py` 从原版 Reborn `Larva/CardLayouts` 和
  `CAbilTrain/InfoArray` 生成 28 条唯一的卡牌命令及精确产物；合并 Swarm campaign 继承层后，
  `LarvaTrainSwarm,Train4 -> Devourer` 被保留。基线还包含原版 roster，并将
  `Hatchery`、`SpawningPool` 和 `LurkerDen` 识别为建筑。
- `static`：`reborn_abathur_check.py` 对缺 Larva、P1/P2 census 缺失、缺期望 ability、
  未执行、action 拒绝、错/漏/额外产物均失败关闭。检测到多个本地 Reborn 解包源的关键文件
  SHA-256 不同时，基线生成器拒绝猜选；使用已归档哈希显式定位 source 后稳定得到
  `LarvaTrain=4`、`LarvaTrainSwarm=3`、`LarvaTrainSwarm2=21`。
- `runtime/inconclusive`：首次 `005800` 运行未启用 `RequestDebug(tech_tree)`，只能作为
  前置条件诊断，不能用于判断 parity。
- `runtime`：有效运行通过 approved `launch-cmre-alenger.ps1` 启动 CMRE `亡者之夜` 地图的
  Reborn Abathur，会话执行 `RequestDebug(all_resources, tech_tree, fast_build)` 后完成
  CreateGame/JoinGame。P1/P2 raw census 分别为
  `Drone=24,Hatchery=2,Larva=6,Overlord=1,CoopCasterAbathur=1,ACHeroSpawnPlacement=1`
  与 `Drone=12,Hatchery=2,Larva=6,Overlord=1,ACHeroSpawnPlacement=1`。
- `runtime`：79 次 loop `19..974` readiness sample 中，P1 Larva 从 `6` 增至 `17`，却只
  公开 `LarvaTrain,2`（ability id 1344），与 28 条原版 command 的交集为 0。fresh
  controlled Larva 对全部 28 条同样不可用，比较器报告 `EXPECTED_ABILITY_MISSING=28`
  （LarvaTrain 4、LarvaTrainSwarm 3、LarvaTrainSwarm2 21）；同窗口无新增非空 ScriptError，
  所以结论为真实 `FAIL`，不是地图加载或脚本崩溃。
- `runtime evidence`：
  `artifacts/projects/cmre-porting/stage26-full-function-invoke/runtime/reborn-abathur-larva-runtime-20260813-011000-final.json`；
  packed map SHA-256=`5F4DBEE969D23F4A39DB2808F374879BDF131EEE6AF26806F3E7E37FF356801E`；
  launcher transcript=`artifacts/projects/cmre-porting/stage26-full-function-invoke/runtime/reborn-abathur-cardcheck-20260813-011000.launcher.stdout.txt`。
- `validation`：`python -m pytest -q
  src/projects/cmre-porting/stages/26-full-function-invoke/test_reborn_abathur_check.py` -> 9 passed；
  三脚本 `python -m py_compile`、JSON parse 和 `git diff --check` 通过。将 `011000` artifact
  再送入比较器仍得 `FAIL / 28`，P1 正确分类为单位 `Drone/Larva/Overlord`、建筑 `Hatchery`。
  验证完成后仅停止本轮 launcher 所有的 SC2 PID 30372；launcher PID 30268 和 API 5098 已释放。
