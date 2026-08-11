"""从源码重建可分发的 CMLib.SC2Mod（目录形态）并打包为 CMLib_out.SC2Mod（MPQ）。

布局必须与库内 include 路径一致：
    CMLib.SC2Mod/Base.SC2Data/scripts/cmlib/*.galaxy
因为库文件内部一律写 `include "scripts/cmlib/cmlib_xxx"`，
若把 .galaxy 平铺在 Base.SC2Data 根目录，SC2 解析 include 会失败
（旧版就是平铺的，属于历史遗留 bug）。

使用方：在自己的地图 MapScript 里
    include "scripts/cmlib/cmlib"
并把本 mod 加为地图依赖即可。
"""
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(r"E:\Code\MyMod\SC2VibeTools\sc2-porting-workspace")
LIB = REPO / "src" / "lib"
CMLIB_SRC = LIB / "scripts" / "cmlib"
MOD_DIR = LIB / "CMLib.SC2Mod"
OUT_MOD = LIB / "CMLib_out.SC2Mod"
PACKER = REPO / "tools" / "mpq" / "scripts" / "pack_stormlib.py"
STORMLIB = REPO / "artifacts" / "stormlib-v9.40" / "x64" / "StormLib.dll"

MODINFO = '''<?xml version="1.0" encoding="utf-8"?>
<ModInfo version="1">
  <Name value="CMLib - SC2 Common Galaxy Library"/>
  <Description value="\u8de8\u9879\u76ee\u901a\u7528 Galaxy \u51fd\u6570\u5e93\uff0821 \u6a21\u5757\uff1acore/ui/unit/catalog/player/ai/fx/panel/bank/geo/text/trig/game/conv/udata/stock/board/buff/path/env/stat\uff09"/>
  <Author value="sc2-porting-workspace"/>
  <Archive name="Base.SC2Data"/>
</ModInfo>
'''


def main():
    if not CMLIB_SRC.is_dir():
        print(f"[mod] \u627e\u4e0d\u5230\u5e93\u6e90\u7801: {CMLIB_SRC}")
        return 1

    if MOD_DIR.exists():
        shutil.rmtree(MOD_DIR)
    dst = MOD_DIR / "Base.SC2Data" / "scripts" / "cmlib"
    dst.mkdir(parents=True)

    n = 0
    for f in sorted(CMLIB_SRC.glob("*.galaxy")):
        shutil.copy(f, dst)
        n += 1
    readme = CMLIB_SRC / "README.md"
    if readme.exists():
        shutil.copy(readme, MOD_DIR / "README.md")

    (MOD_DIR / "modinfo.xml").write_text(MODINFO, encoding="utf-8")

    if OUT_MOD.exists():
        OUT_MOD.unlink()
    r = subprocess.run([sys.executable, str(PACKER), str(MOD_DIR), str(OUT_MOD),
                        "--stormlib", str(STORMLIB)],
                       capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        print("[mod] \u6253\u5305\u5931\u8d25:\n" + (r.stderr or r.stdout))
        return 1

    print(f"[mod] CMLib.SC2Mod/Base.SC2Data/scripts/cmlib/  <- {n} \u4e2a .galaxy")
    print(f"[mod] \u6253\u5305 -> {OUT_MOD.name} ({OUT_MOD.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
