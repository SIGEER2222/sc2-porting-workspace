# 离线 SC2 M3 资产制作执行工作流

> **状态：** 可执行的资产生产工作流。它不是“给 AI 看的参考说明”或单次转换教程：每个模板都必须经过相同的输入、自动 gate、图形界面 gate、导出回导 gate 与未来 runtime gate，并输出可追溯证据。
>
> **核心目的：** 不让 AI 从零“猜出”一套 SC2 骨骼、动作和引擎资产，而是让 AI 专注生成可控的**网格与贴图**，再把它接入已经验证的 SC2 单位模板骨架、动作、挂点和材质结构。最终目标是形成可以重复生产、回导检查、并在具备 SC2 后完成运行时验收的资产流水线。
>
> **本工作流的完成定义：** 不是生成了一个 GLB，也不是写完了文档；而是某个模板或 AI 资产按本文 Gate 顺序走完，并保留 manifest、自动报告、authoring 版本、导出物、回导比较和相应证据。
>
> **证据边界：** 当前工作站没有 SC2。本文中 Blender、GLB 与 M3Studio 的结果仅代表 `static` / 离线证据；它们不能替代 SC2 Previewer、Data Editor、Actor 或游戏内运行时验证。


## 1. 为什么需要这条工作流

图片生成三维模型已经能解决“外形从哪里来”的问题，但一个可用的 SC2 单位还同时依赖：

```text
可识别的 M3 模型结构
+ 模板骨架与正确绑定权重
+ 可播放的 Stand / Walk / Attack 等动作
+ Animation Group / M3A 对应关系
+ Attachment Points、Hit Test Volumes、材质层
+ DDS 贴图与资产路径
+ 将来的 SC2 引擎、Actor 和游戏内验证
```

若让 AI 同时生成所有内容，最常见的结果是模型能看但无法稳定复用动作、无法回写 M3，或在 SC2 中缺贴图、缺挂点、动作不匹配。

因此本工作流把责任拆开：

| 责任 | 产物 | 原则 |
|---|---|---|
| SC2 模板资产 | M3、必要时的 M3A、DDS、骨架、动作组、挂点 | 只读基线；是 SC2 专有信息的来源 |
| AI 建模 | 静态网格、PBR 贴图、概念变化 | 不要求 AI 生成最终 SC2 骨架和动作 |
| Blender 制作 | 网格整合、初始权重、局部 Weight Paint、动作视觉检查 | 小步修改；每轮可回退 |
| M3Studio | M3/M3A 导入导出、M3 专有属性维护 | 使用图形界面进行导入导出与回导检查 |
| 离线质量门 | 清单、哈希、动作/姿势截图、回导对比报告 | 不把静态结果误称为运行时结果 |
| 未来 SC2 验收 | Previewer、Actor、游戏内效果 | 只在有 SC2 运行条件后执行 |

## 2. 资产真源与三个工作副本

不要让单一格式承担所有角色。每个模板单位必须保留三类独立副本：

```text
A. source/     原始只读 SC2 资产：M3 + 可选 M3A + DDS
B. authoring/  M3Studio 导入的 Blender 制作副本：可导出 M3
C. preview/    M3 转 GLB 后的 Blender 预览副本：快速播放、渲染、供 AI 参考
```

### 2.1 真源规则

```text
M3 / M3A / DDS
  是 SC2 专有资产数据的真源

M3Studio authoring .blend
  是人为制作与导出过程的工作真源

GLB preview .blend
  是快速查看、截图、渲染和 AI 参考副本
  不是可无损回写 M3 的唯一源文件
```

禁止用 GLB 预览副本覆盖原始 M3。GLB 导出可能不完整表达 M3 的 Animation Group、材质层、Attachment Point、Hit Test、粒子、Ribbon、Projection 或其他 SC2 专用数据。

## 3. 端到端工作流

```text
[1. 选择模板与建立基线]
M3 + 可选 M3A + DDS
        |
        +--> [2A. M3Studio 制作支线]
        |     图形界面导入 -> authoring .blend -> 整合 AI Mesh/贴图/权重
        |     -> 导出 M3/M3A -> 回导对比
        |
        +--> [2B. GLB 预览支线]
              M3 -> GLB -> preview .blend -> 动作视频/截图/AI 参考

[3. AI 生成]
概念图 + 模板预览 + 约束 -> 静态 Mesh GLB + PBR 贴图
        |
[4. 整合与绑定]
AI Mesh -> 模板 Armature -> 初始权重 -> 局部 Weight Paint
        |
[5. 离线质量门]
Stand / Walk / Attack -> 导出 M3 -> M3Studio 回导
        |
[6. 将来 SC2 运行时质量门]
Previewer -> Actor -> 游戏内验证
```

### 3.1 每个资产必须实际执行的 Workflow

每个资产只允许按下面顺序推进；某个 Gate 未通过时，修复后重新从该 Gate 执行，不跳到导出或运行时阶段。

| 顺序 | 输入 | 执行者与动作 | 强制输出 | 放行条件 |
|---|---|---|---|---|
| W1 静态基线 | W0 manifest | 运行 `run_static_template_baseline.py` | source hash、GLB、动作 probe JSON | M3 转 GLB 成功，Stand/Walk/Attack 有 F-Curve 且网格姿势变化；重复运行时源摘要和语义动作 probe 一致 |
| W2 制作基线 | W1 PASS | 在 Blender 图形界面用 M3Studio 导入 M3/M3A | `authoring/<template>-source.blend`、UI 截图/记录 | 骨骼、网格、动作、材质层、挂点均存在 |
| W3 视觉模板 | W2 PASS、DDS | 映射 DDS，并输出三组关键动作预览 | Stand/Walk/Attack 图像或视频 | 贴图来源可追溯，动作可视觉审查 |
| W4 AI 网格整合 | W3 预览、AI 静态 Mesh/PBR 贴图 | 对齐比例/轴向/原点，绑定既有 Rig，局部修权重 | 新 authoring 版本与变更说明 | 三组动作无明显飞散、断裂或不可接受拉伸 |
| W5 M3 回导 | W4 candidate | M3Studio 导出 M3/M3A，在新场景回导并比较 | candidate M3/M3A、round-trip 报告 | 结构合同、动作和关键挂点未丢失 |
| W6 SC2 runtime | W5 PASS、SC2 可用 | Previewer、Data、Actor、游戏内及 GameLogs 验收 | runtime evidence bundle | 取得真实引擎证据 |

当前已实现自动化的是 **W0/W1**，并已提供可实际启动 Blender 图形界面的 W2/W3 执行入口；W4/W5 现在有可重复的 Blender/M3Studio runner，但 W4 仍必须通过人工视觉审查。当前 PoC 已完成：44 根模板骨骼、28 个可传递皮肤骨骼组、50,000 三角形 AI 网格、Stand/Walk/Attack、candidate M3 导出和新场景回导结构检查；不过 deform-bone overlay 显示模板骨骼与该 AI 网格的体型/尾部并未充分贴合。随后对有界 rest-bone retarget、skin-group 仿射拟合和 BVH/地标表面拟合进行了离线探针：它们分别产生骨骼脱离网格、长条拉伸或局部几何塌缩，因此均未提升为候选版本，W4 runner 已恢复为保守的 v5 绑定结果。下一步必须是人工重拓扑/Weight Paint，或重新生成更接近模板比例的 AI 网格；不能把自动权重迁移或结构回导 PASS 当作体型兼容。W4 视觉 gate 仍为 **REVIEW_REQUIRED**，不能把当前结果称为 W4_PASS。W5 的 `status=PASS` 只表示 candidate M3 能被 M3Studio 新场景回导并保留 44 根骨骼、单网格、UV 和三项动作；W6 因本机无 SC2 处于 `BLOCKED_NO_SC2`。任何自动化 PASS 只意味着当前 Gate 放行，绝不代表整个流程完成。


### 3.2 W1 的可执行入口

模板和 Runner 由仓库管理，不依赖聊天上下文：

```text
src/projects/cmre-porting/stages/50-vm-debugger-expansion/asset-workflow/
  templates/zergling-scbw.template.json
  run_static_template_baseline.py
  run_gui_authoring.py
  run_binding_reference_audit.py
  references/zergling-scbw-ai-reference.json
```

`references/zergling-scbw-ai-reference.json` is the machine-readable AI input/output and rig/action contract. It keeps the 44-bone template, canonical Stand/Walk/Attack actions, non-skin groups, weight completeness rule, negative binding examples, and the offline evidence boundary together.

`run_binding_reference_audit.py` is a separate diagnostic runner. It builds isolated rigid, automatic, envelope, and template-weight-transfer candidates, samples action start/mid/end frames, and writes a report. Its `COMPLETED_WITH_REJECTED_CANDIDATES` status means the audit completed; it does not mean every candidate passed.

### 3.2.1 AI binding reference audit

Run it against a saved M3Studio source Blend and a static AI GLB:

```powershell
& '<Blender executable>' --background `
  --python src/projects/cmre-porting/stages/50-vm-debugger-expansion/asset-workflow/run_binding_reference_audit.py -- `
  --source-blend artifacts/projects/cmre-porting/stage50-vm-debugger-expansion/ai-mesh-output/zergling-ai-50k-v5/zergling-ai-w4-source.blend `
  --candidate-glb artifacts/projects/cmre-porting/stage50-vm-debugger-expansion/ai-mesh-input/852191c4dad0ecc0b984c28fb848e7fa/compression-2k/zergling-ai-lowpoly-50k-2k.glb `
  --out-report artifacts/projects/cmre-porting/stage50-vm-debugger-expansion/ai-mesh-output/zergling-ai-50k-v5/binding-reference-audit.json
```

The audit is static Blender evidence. The current selected example has 36,578 vertices, 50,000 triangles, 28 transferred deform groups, and zero unassigned vertices. It remains `retain-for-review`: the canonical actions drive the mesh, but body/tail visual fit still requires manual Weight Paint or a template-proportioned regeneration. Automatic and envelope candidates are retained as negative comparisons when they leave unweighted vertices or produce unstable deformation.

在 PowerShell 中为当前机器指定 Blender，再运行模板：

```powershell
$env:SC2_ASSET_BLENDER = '<Blender executable>'
py -3.13 src/projects/cmre-porting/stages/50-vm-debugger-expansion/asset-workflow/run_static_template_baseline.py `
  src/projects/cmre-porting/stages/50-vm-debugger-expansion/asset-workflow/templates/zergling-scbw.template.json `
  --out artifacts/projects/cmre-porting/stage50-vm-debugger-expansion/sc2-model-reference/workflow-runs/zergling-scbw-static-baseline.json
```

Runner 会实际执行：

```text
M3/DDS 文件存在与 SHA-256 基线
-> node convert-m3.js: M3 -> GLB
-> Blender background: 导入 GLB
-> 检查 Armature、网格、骨骼、Stand/Walk/Attack 的 F-Curve 与三帧网格姿势哈希
-> 重复运行时比较源摘要和语义动作 probe；GLB 二进制哈希只记录，不作为确定性断言
-> 写出 static-baseline.json
```

它还会把尚未完成的 W2–W6 作为 `manualGates` 写入报告，因此后续人员不会把“预览成功”误作“资产完成”。

### 3.3 W2/W3 的 Blender 图形界面入口

仓库提供 `asset-workflow/run_gui_authoring.py`。它只处理 Blender/M3Studio 离线制作，不启动 SC2，不修改地图或 Mod，也不调用 Previewer、Actor 或游戏内接口。

```powershell
$env:SC2_M3STUDIO_ADDON_DIR = '<M3Studio addon directory>'
& '<Blender executable>' --factory-startup `
  --python src/projects/cmre-porting/stages/50-vm-debugger-expansion/asset-workflow/run_gui_authoring.py -- `
  --manifest src/projects/cmre-porting/stages/50-vm-debugger-expansion/asset-workflow/templates/zergling-scbw.template.json
```

GUI runner 的强制输出为：

```text
<template>-source.blend       W2：未修改的 M3Studio authoring 基线
<template>-preview.blend      W3：DDS 预览与动作检查副本
previews/{stand,walk,attack}-{start,mid,end}.png
gui-authoring-report.json     导入、骨骼、动作、贴图、GUI 会话和边界证据
```

启动成功后 Blender 会保持打开，并在 3D View 的 `Asset Workflow` 侧栏提供 Stand、Walk、Attack 切换和交互快照按钮。侧栏不是 SC2 工具；它只操作当前离线 Blender 场景。

## 4. 阶段、目标与验收

### 阶段 0：选择模板与资产清单

**目的：** 确定 AI 将复用哪一套体型、骨架和动作，避免“生成后才发现没有合适动作”。

每个模板先记录：

```text
模型文件：model.m3
动作文件：需要时的 RequiredAnims/*.m3a
贴图文件：Diffuse / Normal / Specular / Emissive 等 DDS
骨架：骨骼名称、层级、数量
动作：Stand / Walk / Attack / Death / Burrow 等实际可用动作
挂点：Ref_Weapon、Ref_Muzzle、Target、Shield 等实际存在项
交互体：Hit Test Volumes
```

**通过条件：** 文件存在、来源路径可追溯、哈希已记录；需要的动作和贴图未被假定为“会自动存在”。

### 阶段 1：M3Studio 制作基线

**目的：** 建立真正能导回 M3 的 Blender 工作副本。

在 Blender 图形界面中使用 M3Studio：

1. `File > Import > StarCraft 2 Model (.m3, .m3a)` 导入主 M3；
2. 勾选 `Mesh Data`、`Rig`、`Animations`；需要时导入 Effects；
3. 若模板有独立 M3A，在同一个 Armature 上导入该 M3A；
4. 保存为 `authoring/<template>-source.blend`，不覆盖原始资产；
5. 检查 Armature、网格、动作组、材质层、Attachment Points、Hit Test Volumes。

**通过条件：** 图形界面导入没有阻断错误，关键骨骼、网格、动作和挂点存在。

> 当前限制：M3Studio 在注册时加载 GPU 绘制模块，不能用 Blender `--background` 模式完成可靠导入/导出验证。因此本阶段必须在 Blender 图形界面操作与记录证据。

### 阶段 2：GLB 预览与参考输出

**目的：** 快速观察模型、骨架和动作，为人工审查与 AI 提供统一参考。

```text
M3 -> GLB -> Blender preview .blend
```

预览副本应输出：

```text
模型转台图
骨架可视化图
Stand、Walk、Attack 的首/中/末帧
Stand、Walk、Attack 的短视频
动作清单与帧范围
```

**通过条件：** 关键动作存在，且多帧取样显示骨骼或网格确实随动作变化。

### 阶段 3：贴图参考与材质预览

**目的：** 让 AI 和制作人员看到接近原模板的视觉信息，而不仅是灰色网格。

把模板 DDS 映射到预览材质：

```text
Diffuse   -> Base Color
Normal    -> Normal Map
Specular  -> 按 Blender PBR 预览需要转换或近似映射
Emissive  -> Emission
```

预览映射不等于 SC2 引擎材质保真；正式 M3 材质层仍应由 M3Studio authoring 副本维护。

**通过条件：** 预览能加载和显示实际 DDS，且每张贴图来源可追溯。

### 阶段 4：AI 输入与输出合同

**目的：** 让 AI 输出可被整合的内容，而不是无约束地生成另一个不兼容的角色资产。

#### 给 AI 的输入

```text
概念图 / 多视图
模板预览 Blend 或 GLB
模板尺寸、轴向、原点、轮廓参考
Stand / Walk / Attack 视频与关键帧
骨架/网格截图
允许替换与禁止修改的部位说明
```

#### AI 必须交付

```text
一个静态 Mesh GLB（不含最终 SC2 骨架与动作）
PBR 贴图：BaseColor、Normal、Roughness、Metallic、可选 Emissive
产物版本号与生成来源
```

#### AI 不应承担

```text
最终 M3 导出
最终 Animation Group 或 M3A 设计
SC2 Attachment Points / Hit Test Volumes
未经模板验证的全新骨骼层级
```

**通过条件：** 输出 Mesh 能按约定比例、轴向和原点导入模板 Blender 文件；贴图可加载；没有悄悄替换模板骨架。

### 阶段 5：网格整合与权重

**目的：** 把 AI 输出接入已验证模板的骨架和动作。

建议顺序：

```text
导入 AI 静态 Mesh
-> 对齐模板的比例、轴向、原点
-> 不改模板骨骼名称或层级
-> 生成初始权重
-> 在关节、尾巴、爪子、披挂物等区域局部 Weight Paint
-> 依次播放 Stand / Walk / Attack
```

一轮只处理一个问题，例如“尾巴在 Walk 中穿模”或“前爪在 Attack 中拉伸”；不要在同一轮同时重拓扑、重绑骨、重做动作和重做贴图。

**通过条件：** 关键动作中没有明显网格飞散、关节断裂或不可接受的拉伸；每个修改能被定位到具体工作副本版本。

### 阶段 6：动作复用、补动作与 M3A

**目的：** 先复用模板的已验证动作，只有确有必要时才创建或改动动作。

优先级：

```text
优先：复用 Stand / Walk / Attack
其次：在已有 Action 上做局部姿势修正
最后：新建动作或单独 M3A
```

新增或修改动作时，必须确认 M3 Animation Group 与子动画、Action 的对应关系；M3 与对应 M3A 的 Animation Header ID 必须保持匹配。

**通过条件：** 动作组名称、关联 Action 和关键帧在导出后仍然存在且可播放。

### 阶段 7：M3 导出与回导

**目的：** 在没有 SC2 的情况下，建立最重要的离线可信度闸门。

```text
M3Studio authoring .blend
-> 导出 candidate.m3 / candidate.m3a
-> 新 Blender 场景中用 M3Studio 回导
-> 对照 source 基线和 candidate 基线
```

至少比较：

```text
Armature 与骨骼名称/层级/数量
导出网格数量与父级关系
材质、M3 Material Layers 与贴图路径
Animation Groups、动作和帧范围
关键 Attachment Points
Hit Test Volumes
Stand / Walk / Attack 三组姿势
```

**通过条件：** 回导无阻断错误；合同中规定的结构未丢失；关键动作仍可播放。通过本阶段仍只能标为 `static`。

### 阶段 8：将来的 SC2 运行时验收

**目的：** 验证离线工具无法证明的引擎行为。

在具备 SC2 和已批准 launcher 的条件后：

```text
SC2 Previewer：模型、贴图、动作、挂点
Data Editor：Model 与 Unit 绑定
Actor：动画事件、武器和效果挂点
游戏内：选择框、受击、动画切换、特效、性能
GameLogs：本次新增 ScriptError 检查
```

**通过条件：** 取得实际引擎和游戏内证据。Blender 成功、M3Studio 回导成功或 launcher 退出码为零，均不能单独取代这一阶段。

## 5. 模板资产包的建议结构

```text
<asset-library>/<rig-family>/<template-id>/
  manifest.json
  source/
    model.m3
    required-anims/
    textures/
  authoring/
    <template>-source.blend
    <template>-tweak-001.blend
  preview/
    reference.glb
    reference-preview.blend
    stand.png
    walk.mp4
    attack.mp4
  export/
    <template>-tweak-001.m3
  validation/
    source-baseline.json
    preview-motion.json
    export-roundtrip.json
    visual-review.md
```

`manifest.json` 应至少记录模板 ID、来源、文件哈希、骨架摘要、关键动作、关键挂点、贴图清单、许可/出处与最后验证时间。

## 6. 离线质量门与证据层级

| Gate | 检查内容 | 证据类型 | 当前要求 |
|---|---|---|---|
| G0 | M3/M3A/DDS 清单和哈希 | static | 每个模板必须有 |
| G1 | M3Studio 图形界面导入 | static + UI evidence | 正式制作前必须有 |
| G2 | DDS 贴图在 Blender 预览正确显示 | static | AI 参考模板必须有 |
| G3 | Stand / Walk / Attack 多帧动作检查 | static | 每轮网格/动作修改后必须有 |
| G4 | 网格、权重与视觉变形审查 | static + visual evidence | 每轮整合后必须有 |
| G5 | 导出 M3/M3A 后的 M3Studio 回导对比 | static + UI evidence | 每个候选导出必须有 |
| G6 | Previewer / Actor / 游戏内检查 | runtime | 有 SC2 后才执行 |

## 7. 当前工作站实际状态

### 已验证

- 本地 M3-to-GLB 转换器已成功转换可用样例；它支持 M3 解析、骨骼动画、挂点可视化和 GLB 导出。
- 本地 Blender 4.5.5 可导入 GLB 并播放导出的动作。
- 当前 SCBW 跳虫预览副本包含 Armature 与 16 个 Actions；`Walk` 已通过帧采样确认会驱动网格变形。
- 本地存在 SCBW 跳虫主模型以及 Diffuse、Normal、Specular、Emissive、Reflection DDS 贴图。
- 本地已安装 M3Studio v0.3.0，其文档声明支持 M3/M3A 导入、M3/M3A 导出、Animation Groups、Material Layers、Attachment Points 和 Hit Test Volumes。
- W0/W1 已从说明落地为仓库中的 Zergling 模板 manifest 与可执行 static baseline runner；该 runner 已完成一次实际跳虫基线运行。
- W2/W3 已通过 `asset-workflow/run_gui_authoring.py` 在非后台 Blender 4.5.5 进程中实际执行：M3Studio 导入得到 44 根骨骼、6 个网格和 Stand/Walk/Attack，随后保存 authoring 基线。
- GUI runner 已加载跳虫 Diffuse、Normal、Emissive DDS，生成独立 preview Blend 以及 Stand/Walk/Attack 各首帧、中帧、末帧共 9 张 PNG；报告记录 `blenderBackground=false`、`sc2Integration=false`。
- 已人工查看 Stand、Walk、Attack 中帧图像；模型可见、贴图已显示、动作姿势有差异。证据仍属于离线 `static`，不是 SC2 runtime。

### 当前验收状态

```text
AI 静态 Mesh 输入/输出合同的可执行样例           已完成：50,000 三角形 GLB + 2048 PBR 贴图
AI Mesh -> 模板骨架 -> 权重 -> M3 导出的结构 PoC  已完成：44 骨骼、28 皮肤组、candidate M3
W4 动作视觉贴合                                  REVIEW_REQUIRED：deform-bone overlay 仍有明显偏离
M3Studio 不修改数据的 M3 -> export -> re-import  已完成结构检查：44 骨骼、1 网格、50,000 三角形、UV、Stand/Walk/Attack
SC2 Previewer / Actor / 游戏内运行时验收         阻塞：无本地 SC2，W6
```

W4/W5 当前证据目录：`artifacts/projects/cmre-porting/stage50-vm-debugger-expansion/ai-mesh-output/zergling-ai-50k-v5/`。其中 `w4-w5-export-report.json`、`w5-reimport-report.json`、`rig-alignment-audit.json`、`deform-bones-overlay.png` 和三组动作预览必须一起阅读；结构回导 PASS 不覆盖 W4 的视觉贴合缺陷。

### 已知工具限制

- M3Studio 导入时会初始化 GPU 绘制模块，因此 Blender 后台模式不能替代可靠导入/导出验证；GUI runner 必须使用不带 `--background` 的 Blender。
- 本地 `star-tools-three-m3-loader` 的实际 M3-to-GLB 转换可用，但 `npm test` 目前因 Node 24 环境缺少原生 `canvas.node` 而失败。未修复该依赖前，不可声称该工具的自动测试通过。
- GUI W3 预览目前使用 Diffuse、Normal、Emissive DDS；Specular、Reflection 的精确 M3 材质层语义仍由 M3Studio authoring 副本维护，不能把 Blender PBR 预览当作 SC2 材质保真。

## 8. 最小可行里程碑：跳虫 Round-Trip PoC

不要先建设整套资产平台。先交付一个可复核的跳虫闭环：

0. 执行 W0/W1：运行 `zergling-scbw.template.json` 的 static baseline runner，确认源哈希和三项关键动作通过。
1. 在非后台 Blender 中运行 `run_gui_authoring.py`，由 M3Studio 图形界面导入 `ZerglingSCBW.m3`。
2. 检查 `zergling-scbw-source.blend`，确认 44 根骨骼、网格、Stand/Walk/Attack、材质层和挂点存在；确认原始 M3 未被改写。
3. 在 `Asset Workflow` 侧栏切换动作，检查 GUI runner 输出的 Stand/Walk/Attack 九张关键帧图像。
4. 确认 DDS 来源和 preview Blend 后，再接收一个静态 AI Mesh，按模板比例、轴向和原点导入。
5. 做一处小而可见、容易回退的修改：例如尾尖局部网格或颜色微调，并记录 W4 版本。
6. 导出 candidate M3。
7. 新场景回导 candidate M3。
8. 对比骨骼、网格、动作、材质层、关键挂点和三组姿势，输出 W4/W5 比较报告。
9. 输出 manifest、W1 static report、GUI W2/W3 report、W4/W5 比较报告、截图/视频与结论。

此 PoC 的成功标准：

```text
原始资产未被改写
candidate M3 可以回导
关键骨骼、网格和动作未丢失
Stand / Walk / Attack 可播放且无明显变形异常
贴图来源可追溯
所有离线结论标为 static
```

完成后再把方法推广到人形、四足、飞行和大型单位等不同 Rig 家族。

## 9. 给后续 AI 的执行约束

1. 先选择已经验证的模板 Rig，再接收 AI 生成网格；不要反过来。
2. 原始 M3/M3A/DDS 一律只读；任何修改进入新的 authoring 或 export 版本。
3. GLB 只用于预览、渲染和 AI 参考，不作为 M3 唯一源文件。
4. 每次只改变一个资产问题，并复查 Stand、Walk、Attack。
5. 新导出的 M3/M3A 必须用 M3Studio 回导，不能只看导出操作未报错。
6. 没有 SC2 时，所有结果均标注为离线/static；不得写成 Previewer 或游戏内已通过。
7. 在任何自动化之前，先让跳虫 Round-Trip PoC 跑通；它是后续 AI 建模规模化的模板验收基准。
