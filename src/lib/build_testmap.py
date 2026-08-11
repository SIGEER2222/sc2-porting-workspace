"""从源码重建 CMLib 运行时自测地图 test_cmlib.SC2Map。

组装规则：
  _testmap_src/**                      骨架（DocumentHeader / GameData / 地形…）
  + scripts/cmlib/*.galaxy             CMLib 库源码（唯一真源）
  + selftest/cmlib_selftest.galaxy     自测脚本（唯一真源，不进库、不进 mod）
  + MapScript.galaxy                   入口，调用 CMLib_SelfTest()

之所以要有这个脚本：手工 cp 极易漏同步，出现"改了库但测的还是旧包"的假结果。

历史坑：自测脚本以前唯一存放在 _testmap_build/ 里，而本脚本第一步就 rmtree
该目录 —— 靠"先读到内存再写回"续命，一旦中途异常就永久丢失。现已迁到
src/lib/selftest/ 独立目录，build 目录彻底变成纯产物。
"""
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(r"E:\Code\MyMod\SC2VibeTools\sc2-porting-workspace")
LIB = REPO / "src" / "lib"
SRC_MAP = LIB / "_testmap_src"
BUILD = LIB / "_testmap_build"
OUT_MAP = LIB / "test_cmlib.SC2Map"
CMLIB_SRC = LIB / "scripts" / "cmlib"
SELFTEST_SRC = LIB / "selftest" / "cmlib_selftest.galaxy"
PACKER = REPO / "tools" / "mpq" / "scripts" / "pack_stormlib.py"
STORMLIB = REPO / "artifacts" / "stormlib-v9.40" / "x64" / "StormLib.dll"

MAPSCRIPT = '''//==================================================================================================
// CMLib 运行时自测地图入口（由 build_testmap.py 生成，勿手改）
//==================================================================================================
include "TriggerLibs/natives"
include "scripts/cmlib/cmlib"
include "scripts/cmlib/cmlib_selftest"

//--------------------------------------------------------------------------------------------------
void InitMap () {
    CMLib_SelfTest();
}
'''


def main():
    if not SELFTEST_SRC.exists():
        print(f"[build] 找不到自测脚本: {SELFTEST_SRC}")
        return 1

    if BUILD.exists():
        shutil.rmtree(BUILD)
    shutil.copytree(SRC_MAP, BUILD)
    dst = BUILD / "Base.SC2Data" / "scripts" / "cmlib"
    dst.mkdir(parents=True, exist_ok=True)

    n = 0
    for f in sorted(CMLIB_SRC.glob("*.galaxy")):
        shutil.copy(f, dst)
        n += 1
    shutil.copy(SELFTEST_SRC, dst / "cmlib_selftest.galaxy")
    (BUILD / "MapScript.galaxy").write_text(MAPSCRIPT, encoding="utf-8")

    r = subprocess.run([sys.executable, str(PACKER), str(BUILD), str(OUT_MAP),
                        "--stormlib", str(STORMLIB)],
                       capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        print("[build] 打包失败:\n" + (r.stderr or r.stdout))
        return 1
    print(f"[build] 同步 {n} 个 CMLib 源文件 + selftest -> "
          f"{OUT_MAP.name} ({OUT_MAP.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
