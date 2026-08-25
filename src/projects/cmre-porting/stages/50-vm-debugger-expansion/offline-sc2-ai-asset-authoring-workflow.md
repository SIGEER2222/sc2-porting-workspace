# 离线 SC2 M3 资产制作工作流与 AI 参考规范

> **状态：** 制作路线与验收合同。本文记录当前可复用的离线工作流、每一阶段的目的、已验证能力、未完成缺口和下一里程碑。
>
> **核心目的：** 不让 AI 从零“猜出”一套 SC2 骨骼、动作和引擎资产，而是让 AI 专注生成可控的**网格与贴图**，再把它接入已经验证的 SC2 单位模板骨架、动作、挂点和材质结构。最终目标是形成可以重复生产、回导检查、并在具备 SC2 后完成运行时验收的资产流水线。
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

### 尚未完成

```text
M3Studio 图形界面导入跳虫主 M3
M3Studio 不修改数据的 M3 -> export -> re-import round-trip
跳虫 DDS 到 Blender preview 材质映射
跳虫 authoring .blend
模板 manifest.json 与文件哈希基线
AI 静态 Mesh 输入/输出合同的可执行样例
AI Mesh -> 模板骨架 -> 权重 -> M3 导出的完整 PoC
SC2 Previewer / Actor / 游戏内运行时验收
```

### 已知工具限制

- M3Studio 导入时会初始化 GPU 绘制模块，因此 Blender 后台模式不能替代图形界面验证。
- 本地 `star-tools-three-m3-loader` 的实际 M3-to-GLB 转换可用，但 `npm test` 目前因 Node 24 环境缺少原生 `canvas.node` 而失败。未修复该依赖前，不可声称该工具的自动测试通过。
- 当前跳虫 GLB/Blend 预览具有动作和材质槽，但没有已载入的 DDS 图像；必须完成阶段 3 才是贴图完整的参考资产。

## 8. 最小可行里程碑：跳虫 Round-Trip PoC

不要先建设整套资产平台。先交付一个可复核的跳虫闭环：

```text
1. 在 M3Studio 图形界面导入 ZerglingSCBW.m3。
2. 保存未修改的 authoring 基线 Blend。
3. 关联跳虫 DDS，输出带贴图的 Stand / Walk / Attack 预览。
4. 做一处小而可见、容易回退的修改：例如尾尖局部网格或颜色微调。
5. 导出 candidate M3。
6. 新场景回导 candidate M3。
7. 对比骨骼、网格、动作、材质层、关键挂点和三组姿势。
8. 输出 manifest、比较报告、截图/视频与结论。
```

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
