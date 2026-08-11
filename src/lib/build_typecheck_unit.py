"""把 CMLib + selftest + MapScript 合并为单一 Galaxy 编译单元，喂给 sc2-galaxy-lang 全量 checker。

目的：绕开 checker 的 funcref typedef 崩溃（G901），换取对其余全部代码（含 selftest）
的真实类型检查——正是这一关能抓出 `int x = Round(fixed)` 这类 fixed→int 隐式转换错误。

funcref 处理策略：剔除 2 个 typedef 及所有以其为参数类型的声明/实现函数。
被剔除的是 CMLib_UGForEach* / CMLib_ForEach* 家族，selftest 未使用，不影响本次检查覆盖面。
"""
import re
import sys
from pathlib import Path

_LIB = Path(r"E:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\lib")
# 库源码只认这一个真源；_testmap_build 是构建产物，读它会检查到过期副本。
SRC = _LIB / "scripts" / "cmlib"
# selftest 只存在于构建目录（不进库）。
SELFTEST = _LIB / "_testmap_build" / "Base.SC2Data" / "scripts" / "cmlib" / "cmlib_selftest.galaxy"
MAPSCRIPT = _LIB / "_testmap_build" / "MapScript.galaxy"
OUT = Path(r"E:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\.cache\cmlib-typecheck\cmlib_unit_all.galaxy")

FUNCREF_TYPES = ["CMLib_PlayerVisitor", "CMLib_UnitVisitor"]

AGGREGATE = SRC / "cmlib.galaxy"


def discover_modules():
    """从聚合入口 cmlib.galaxy 的 include 列表推导模块清单。

    绝不手抄这张表——手抄必漂移：trig 模块被加进 cmlib.galaxy 却漏在硬编码表里，
    结果静态检查全绿、真机却因函数重定义静默丢弃整个 MapScript，白查了几小时。
    """
    mods = []
    for m in re.finditer(r'include\s+"scripts/cmlib/cmlib_([a-z0-9]+)"\s*$',
                         AGGREGATE.read_text(encoding="utf-8"), re.M):
        name = m.group(1)
        if name not in mods:
            mods.append(name)
    if not mods:
        raise RuntimeError(f"没从 {AGGREGATE} 解析出任何模块，检查 include 写法")
    return mods


MODULES = discover_modules()


def strip_block(lines, i):
    """从函数签名行 i 开始，吃掉整个函数体（大括号配平），返回下一行索引。"""
    depth = 0
    started = False
    while i < len(lines):
        depth += lines[i].count("{") - lines[i].count("}")
        if "{" in lines[i]:
            started = True
        i += 1
        if started and depth <= 0:
            break
    return i


def clean(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        stripped = ln.strip()
        # 去掉 include（合并单元不需要）
        if stripped.startswith("include "):
            i += 1
            continue
        # 去掉 funcref typedef
        if "typedef funcref" in stripped:
            i += 1
            continue
        # 去掉引用 funcref 类型的声明 / 实现
        if any(t in ln for t in FUNCREF_TYPES):
            if stripped.endswith(";"):          # 纯声明
                i += 1
                continue
            i = strip_block(lines, i)           # 带函数体
            continue
        out.append(ln)
        i += 1
    return "\n".join(out)


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    parts = [
        "// AUTO-GENERATED type-check compilation unit — DO NOT EDIT",
        "// 由 build_typecheck_unit.py 生成；natives 由 galaxy-lint 自动挂载",
        "",
        "// ---- GameData 常量桩（lint 只加载 GameData/Game.galaxy，其余目录常量需补）----",
        "const int c_gameCatalogUnit_stub_unused = 0;",
        "",
    ]

    missing = []
    # 1) 全部头文件（声明先行）
    for m in MODULES:
        p = SRC / f"cmlib_{m}_h.galaxy"
        if not p.exists():
            missing.append(p.name)
            continue
        parts.append(f"// ===== {p.name} =====")
        parts.append(clean(p))
        parts.append("")

    # 2) 全部实现
    for m in MODULES:
        p = SRC / f"cmlib_{m}.galaxy"
        if not p.exists():
            missing.append(p.name)
            continue
        parts.append(f"// ===== {p.name} =====")
        parts.append(clean(p))
        parts.append("")

    # 3) 自测
    p = SELFTEST
    parts.append(f"// ===== {p.name} =====")
    parts.append(clean(p))
    parts.append("")

    # 4) MapScript 主体
    parts.append("// ===== MapScript.galaxy =====")
    parts.append(clean(MAPSCRIPT))

    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {OUT} ({len(OUT.read_text(encoding='utf-8').splitlines())} lines)")
    if missing:
        print("MISSING:", missing)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
