"""构建"依赖挂载"版自测地图 test_cmlib_dep.SC2Map。

与 test_cmlib.SC2Map 的区别（这是本脚本存在的全部意义）：
    test_cmlib.SC2Map      —— 把 CMLib 25 个 .galaxy 直接塞进地图包（源码内联形态）
    test_cmlib_dep.SC2Map  —— 地图里【一行库代码都没有】，只有 selftest + MapScript，
                              CMLib 全靠 mod 依赖 file:Mods\\CMLib\\CMLib.SC2Mod 提供

前者只能证明"库源码能编译"，后者才能证明"打包出来的 .SC2Mod 分发形态可用"。
两者都跑通，CMLib 才算真的能交付给别人用。

DocumentHeader 依赖区格式（本仓库实测，单/双依赖样本对照得出）：
    0x00  "H2CS"
    0x2c  uint32 依赖计数
    0x30  连续的 null-terminated 依赖串（【注意】串与串之间没有任何元数据头，
          紧密相连；网上流传的"每依赖 20 字节头"说法在本格式版本下不成立）
    ...   uint32 字段计数 + N 个 [名长u16+名+类型标记+值长u16+值]
DocumentInfo(XML) 里另存一份依赖，必须同步改，否则编辑器打开会覆盖回去。
"""
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

REPO = Path(r"E:\Code\MyMod\SC2VibeTools\sc2-porting-workspace")
LIB = REPO / "src" / "lib"
SRC_MAP = LIB / "_testmap_src"
BUILD = LIB / "_depmap_build"
SELFTEST = LIB / "selftest" / "cmlib_selftest.galaxy"
OUT_MAP = LIB / "test_cmlib_dep.SC2Map"
PACKER = REPO / "tools" / "mpq" / "scripts" / "pack_stormlib.py"
STORMLIB = REPO / "artifacts" / "stormlib-v9.40" / "x64" / "StormLib.dll"

SC2_MODS = Path(r"E:\SC2\SC2new\StarCraft II\Mods")
MOD_MPQ = LIB / "CMLib_out.SC2Mod"
MOD_DEPLOY = SC2_MODS / "CMLib" / "CMLib.SC2Mod"
DEP_STR = r"file:Mods\CMLib\CMLib.SC2Mod"

# --negative：把依赖指向一个不存在的路径，用来证明"测试确实走了 mod 依赖通路"。
# 没有这个反向对照，正向 PASS 无法排除缓存/残留导致的假阳性。
# 实测反向结果：CreateGame 后 game_loop 恒为 0、units=0，地图根本起不来。
NEG_BUILD = LIB / "_negmap_build"
NEG_OUT = LIB / "test_cmlib_neg.SC2Map"
NEG_DEP_STR = r"file:Mods\CMLib_DOES_NOT_EXIST\CMLib.SC2Mod"

DEP_COUNT_OFF = 0x2C
DEP_START_OFF = 0x30

MAPSCRIPT = '''//==================================================================================================
// CMLib 依赖挂载自测地图入口（由 build_depmap.py 生成，勿手改）
// 本地图不含任何 CMLib 源码，cmlib.* 全部来自 mod 依赖。
//==================================================================================================
include "TriggerLibs/natives"
include "scripts/cmlib/cmlib"
include "scripts/cmlib/cmlib_selftest"

//--------------------------------------------------------------------------------------------------
void InitMap () {
    CMLib_SelfTest();
}
'''


def patch_document_header(path: Path, new_dep: str) -> str:
    d = bytearray(path.read_bytes())
    if bytes(d[:4]) != b"H2CS":
        return "DocumentHeader \u9b54\u6570\u4e0d\u5bf9"

    count = struct.unpack_from("<I", d, DEP_COUNT_OFF)[0]
    if not (0 < count < 64):
        return f"\u4f9d\u8d56\u8ba1\u6570\u5f02\u5e38: {count}"

    # 逐个跳过已有依赖串，定位插入点
    pos = DEP_START_OFF
    existing = []
    for _ in range(count):
        end = d.index(0, pos)
        existing.append(d[pos:end].decode("utf-8", "replace"))
        pos = end + 1

    enc = new_dep.encode("utf-8")
    if any(new_dep in e for e in existing):
        return f"\u5df2\u5b58\u5728\u4f9d\u8d56\uff0c\u8df3\u8fc7 (deps={existing})"

    d[pos:pos] = enc + b"\x00"
    struct.pack_into("<I", d, DEP_COUNT_OFF, count + 1)
    path.write_bytes(bytes(d))
    return f"deps {count} -> {count + 1}: {existing} + [{new_dep}]"


def patch_document_info(path: Path, new_dep: str) -> str:
    txt = path.read_text(encoding="utf-8")
    if new_dep in txt:
        return "DocumentInfo \u5df2\u542b\u4f9d\u8d56"
    m = re.search(r"(<Dependencies>)(.*?)(</Dependencies>)", txt, re.S)
    if not m:
        return "DocumentInfo \u672a\u627e\u5230 <Dependencies>"
    ins = f"{m.group(2).rstrip()}\n        <Value>{new_dep}</Value>\n    "
    path.write_text(txt[:m.start(2)] + ins + txt[m.end(2):], encoding="utf-8")
    return "DocumentInfo \u5df2\u8ffd\u52a0\u4f9d\u8d56"


def assemble(build_dir: Path, out_map: Path, dep_str: str, tag: str) -> int:
    if build_dir.exists():
        shutil.rmtree(build_dir)
    shutil.copytree(SRC_MAP, build_dir)
    dst = build_dir / "Base.SC2Data" / "scripts" / "cmlib"
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copy(SELFTEST, dst / "cmlib_selftest.galaxy")
    (build_dir / "MapScript.galaxy").write_text(MAPSCRIPT, encoding="utf-8")

    n_lib = len(list(dst.glob("cmlib_*.galaxy"))) - 1
    if n_lib != 0:
        print(f"[{tag}] \u8b66\u544a\uff1a\u5730\u56fe\u5185\u542b {n_lib} \u4e2a\u5e93\u6587\u4ef6\uff0c"
              f"\u4f1a\u7834\u574f\u4f9d\u8d56\u9a8c\u8bc1\u8bed\u4e49")

    print(f"[{tag}] " + patch_document_header(build_dir / "DocumentHeader", dep_str))
    print(f"[{tag}] " + patch_document_info(build_dir / "DocumentInfo", dep_str))

    if out_map.exists():
        out_map.unlink()
    r = subprocess.run([sys.executable, str(PACKER), str(build_dir), str(out_map),
                        "--stormlib", str(STORMLIB)],
                       capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        print(f"[{tag}] \u6253\u5305\u5931\u8d25:\n" + (r.stderr or r.stdout))
        return 1
    print(f"[{tag}] -> {out_map.name} ({out_map.stat().st_size} bytes)\uff0c"
          f"\u5730\u56fe\u5185\u5e93\u6587\u4ef6\u6570 = {n_lib}")
    return 0


def main():
    negative = "--negative" in sys.argv
    if not SELFTEST.exists():
        print(f"[dep] \u627e\u4e0d\u5230\u81ea\u6d4b\u811a\u672c: {SELFTEST}")
        return 1

    if negative:
        print("[neg] \u53cd\u5411\u5bf9\u7167\uff1a\u4f9d\u8d56\u6307\u5411\u4e0d\u5b58\u5728\u8def\u5f84\uff0c"
              "\u9884\u671f\u771f\u673a FAIL\uff08game_loop=0 / units=0\uff09")
        return assemble(NEG_BUILD, NEG_OUT, NEG_DEP_STR, "neg")

    if not MOD_MPQ.exists():
        print(f"[dep] \u627e\u4e0d\u5230 mod \u5305\uff0c\u5148\u8dd1 build_mod.py: {MOD_MPQ}")
        return 1

    MOD_DEPLOY.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy(MOD_MPQ, MOD_DEPLOY)
        print(f"[dep] \u90e8\u7f72 mod -> {MOD_DEPLOY} ({MOD_DEPLOY.stat().st_size} bytes)")
    except PermissionError:
        # SC2 正持有该文件句柄 —— 这本身就说明 mod 已被引擎加载。
        print(f"[dep] \u90e8\u7f72\u8df3\u8fc7\uff1aSC2 \u6b63\u5360\u7528 {MOD_DEPLOY}"
              f"\uff08\u8bf4\u660e\u5df2\u88ab\u5f15\u64ce\u52a0\u8f7d\uff09\uff0c\u6c99\u7bb1\u5185\u6587\u4ef6\u4fdd\u6301\u539f\u6837")

    return assemble(BUILD, OUT_MAP, DEP_STR, "dep")


if __name__ == "__main__":
    sys.exit(main())
