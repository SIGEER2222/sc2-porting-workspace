# SC2 MPQ 打包/解包工具

SC2Map/SC2Mod 文件是 MPQ (MoPaQ) 格式归档。本目录提供解包和打包工具，供 AI 自动化处理 SC2 地图/mod 文件。

## 工具清单

| 文件 | 用途 | 来源 |
|------|------|------|
| `MPQEditor.exe` | MPQEditor (Ladybug) 解包工具，1.8 MB 闭源免费工具 | [zezula.net](https://www.zezula.net/en/mpq/download.html) |
| `scripts/extract-sc2map.ps1` | 解包脚本 (MPQEditor + mpyq 备选) | 自研 |
| `scripts/extract_mpq.py` | Python mpyq 解包脚本 (备选方案) | 自研 |
| `scripts/pack-sc2map.ps1` | 打包包装脚本 | 自研 |
| `scripts/pack_mpq.py` | Python MPQ 打包脚本 (Blizzard 原始 hash) | 自研 |
| `scripts/verify_mpq.py` | MPQ 完整性验证脚本 | 自研 |

## 依赖

- Python 3.x
- mpyq 库: `pip install mpyq`（备选方案，路径含特殊字符或 MPQEditor 失败时使用）

## 路径约定

脚本使用 `$scriptDir` / `$skillDir` 自推算路径，无硬编码绝对路径：

```
tools/mpq/
├── MPQEditor.exe              # 解包工具
├── README.md                  # 本文件
└── scripts/
    ├── extract-sc2map.ps1     # 解包入口（优先 MPQEditor，回退 mpyq）
    ├── extract_mpq.py         # mpyq 解包
    ├── pack-sc2map.ps1        # 打包入口
    ├── pack_mpq.py            # mpyq 打包
    └── verify_mpq.py          # 完整性验证
```

调用时通过 `$PSScriptRoot` 自动定位 exe 和 py，无需修改脚本。

## 解包地图

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "tools/mpq/scripts/extract-sc2map.ps1" "<map_path>" "<output_dir>" "<filter>"
```

参数:
- `map_path`: SC2Map 或 SC2Mod 文件路径
- `output_dir`: 解包输出目录
- `filter`: 可选，文件过滤（默认 `*`，如 `*.xml` 只解包 XML）
- `-UseMpyq`: 强制使用 mpyq（路径含特殊字符时使用）

示例:
```powershell
# 解包所有文件
powershell -NoProfile -ExecutionPolicy Bypass -File "tools/mpq/scripts/extract-sc2map.ps1" "map.SC2Map" "extracted"

# 只解包 XML
powershell -NoProfile -ExecutionPolicy Bypass -File "tools/mpq/scripts/extract-sc2map.ps1" "map.SC2Map" "extracted" "*.xml"

# 路径含特殊字符时强制使用 mpyq
powershell -NoProfile -ExecutionPolicy Bypass -File "tools/mpq/scripts/extract-sc2map.ps1" "map~~.SC2Map" "extracted" "*" -UseMpyq
```

也可直接调用 Python:
```powershell
python tools/mpq/scripts/extract_mpq.py "map.SC2Map" "extracted" "*.xml"
```

## 打包地图

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "tools/mpq/scripts/pack-sc2map.ps1" "<input_dir>" "<output_path>"
```

参数:
- `input_dir`: 解包后的目录（包含所有文件）
- `output_path`: 输出的 SC2Map/SC2Mod 文件路径

内部使用 Python 脚本 `pack_mpq.py` 直接构建 MPQ 文件，兼容 Blizzard 原始 hash 函数。

也可以直接调用 Python:
```powershell
python tools/mpq/scripts/pack_mpq.py "<input_dir>" "<output_path>"
```

示例:
```powershell
# 打包回地图
powershell -NoProfile -ExecutionPolicy Bypass -File "tools/mpq/scripts/pack-sc2map.ps1" "extracted" "new_map.SC2Map"
```

## 验证 MPQ 完整性

打包后建议验证文件完整性:
```powershell
python tools/mpq/scripts/verify_mpq.py "<mpq_path>"
```

输出所有文件是否可读，以及 MPQ header 信息。

## 典型工作流

1. 解包: `extract-sc2map.ps1 "map.SC2Map" "work" "*"`
2. 修改 `work/Base.SC2Data/GameData/` 下的 XML 数据文件
3. 打包: `pack-sc2map.ps1 "work" "map.SC2Map"`
4. 验证: `python scripts/verify_mpq.py "map.SC2Map"`
5. 进图测试

## 复制 SC2Map 文件

**重要**: MPQEditor Shell Extension 会拦截 `.SC2Map` 文件操作，导致 PowerShell 的 `Copy-Item` 失败。复制 `.SC2Map` 文件时必须使用 Python:

```python
import shutil
shutil.copyfile(src, dst)
```

## MPQEditor.exe 版本更新

MPQEditor.exe 是 Ladislav Zezula 的闭源免费工具，当前版本来自 [zezula.net](https://www.zezula.net/en/mpq/download.html)。

更新步骤:
1. 从 https://www.zezula.net/en/mpq/download.html 下载 MPQEditor.zip
2. 解压出 MPQEditor.exe
3. 替换 `tools/mpq/MPQEditor.exe`
4. 提交时注明新版本号

## 技术细节

### MPQ 格式

MPQ 文件结构:
- Header (32 字节): magic `MPQ\x1a` + 元数据
- Hash Table: 16 字节/条目，加密存储，文件名 hash 索引
- Block Table: 16 字节/条目，加密存储，文件数据描述
- File Data: 按 sector 存储

### pack_mpq.py 实现要点

1. **Hash 函数**: 使用 Blizzard 原始加密表（256 行 × 5 列），mpyq 兼容
2. **Hash Table 字段顺序**: `name_a=HASH_A(type=1), name_b=HASH_B(type=2)` (不是 TABLE_OFFSET)
3. **加密/解密**: XOR 对称加密，seed2 更新必须使用原始值 (plaintext)，不能使用加密后的值
4. **文件存储**: 使用标准 sector-based 存储 (flags=0x80000000)，不用 SINGLE_UNIT (0x81000000)
5. **Sector Offset Table**: 文件数据前有 (num_sectors + 1) 个 uint32 条目
6. **(listfile)**: 第一个 block entry，包含所有文件名列表

### MPQEditor 的限制

- `add` 命令只能合并 MPQ 文件，不能添加普通文件
- Shell Extension 会拦截 `.SC2Map` 路径操作
- 路径含特殊字符（如 `~~`）时可能失败

## 注意事项

- 打包前确保目标输出路径不存在，或脚本会自动删除旧文件
- 路径包含中文时，`Resolve-Path` 可能无法正确解析，脚本中使用 `.NET FileInfo` 获取完整路径
- 打包后的 MPQ 文件可直接被 SC2 游戏读取（已验证 halo_v3.SC2Map 进图无 ScriptError）
- 不要用 `git add .` 暂存，只暂存明确指定的文件
