r"""暂存地图编译闭包预检门禁 —— 烧真机档期之前的最后一道 fail-closed 关卡。

【为什么必须有它】
`closure_doctor.py` 只能吃**打包后的 MPQ**（走 StormLib `SFileOpenArchive`），
而 launcher 交付的是 `Maps\<地图>.SC2Map` **目录**形态的暂存产物。于是实际工作流里
体检这一步长期被跳过——直到真机上表现为「所有门禁全绿、Kernel 永不注册、
每个 RPC 都 INTERNAL_ERROR」，再花一整个档期二分定位。

本模块把「打包 → 体检 →（可选）净化 → 复检」收成一条命令，预检成本 ~15s，可无脑前置。

【形态 M：生成闭包 ≠ 挂载闭包】
`LibVibeInvokeCommon.galaxy` 的 funcref 解析表（400+ 行 `if (name=="X"){return X;}`）
是按**生成时那份地图包**的符号集产出的，而实际挂载闭包由 launcher 按指挥官/依赖动态
决定。两者不一致 ⇒ 表里留下指向闭包外的符号 ⇒ 未定义标识符 ⇒ SC2 静默丢弃整个
MapScript。它有两个子形态，**都要能指认**：

  M1 文件在、没 include：`LibXxx.galaxy` 被拷进 Base.SC2Data 却没进 MapScript 的
     include 闭包。⇒ 去查 launcher 的 include 门控。
  M2 文件根本不在：官方指挥官局里 adapter 既不拷文件也不 include，可生成的 bundle
     仍引用它。⇒ 去净化 bundle（`--fix`），不是去改 launcher，更不是去改生成器。

【勿删的反向清点】
早期版本只实现了 M1（「文件存在才报 HINT」），M2 走到这里**静默无输出**——正是
「匹配到才检查」的经典漏报：2026-08-09 真机事故里实际发生的恰恰是 M2，裸看
closure_doctor 的「未定义标识符 libA3ADAPTER_gf_...」极易误判成「生成器造了假符号」
而去改生成器，方向完全错。所以未命中 M1 的未定义符号必须被显式清点为 M2。

用法:
    python staged_map_doctor.py "E:\SC2\SC2new\StarCraft II\Maps\亡者之夜.SC2Map"
    python staged_map_doctor.py <暂存目录> --fix          # 体检失败则净化 bundle 后复检
    python staged_map_doctor.py <暂存目录> --keep --out D:\tmp\probe.SC2Map
退出码: 0=CLEAN（可以启真机），1=BROKEN（别浪费档期），2=用法/环境错误
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import closure_doctor  # noqa: E402
import compile_unit  # noqa: E402
import sanitize_adapters  # noqa: E402

# 仓库根（sc2-porting-workspace）与其外层（SC2VibeTools）都可能放 artifacts/，
# 按层数硬编码上级目录是历史上 pack-sc2map.ps1 踩过的坑，这里改成候选根探测。
_REPO_ROOT = _HERE.parents[2]
_OUTER_ROOT = _REPO_ROOT.parent
_PACK_SCRIPT = _REPO_ROOT / "tools" / "mpq" / "scripts" / "pack_stormlib.py"

RE_LIB_PREFIX = re.compile(r"^lib([A-Za-z0-9]+)_")

# 只净化**生成产物**，绝不碰手写库：手写库里的未定义符号是真 bug，必须炸出来修，
# 静悄悄降级成 FUNCTION_NOT_IN_MAP 只会把问题埋到运行时。
SANITIZE_GLOBS = ("LibVibeInvoke*.galaxy",)


def find_stormlib() -> Path:
    for root in (_REPO_ROOT, _OUTER_ROOT):
        for arch in ("x64", "Win32"):
            cand = root / "artifacts" / "stormlib-v9.40" / arch / "StormLib.dll"
            if cand.is_file():
                return cand
    raise SystemExit(
        "[FAIL] 找不到 StormLib.dll；期望位置: "
        rf"{_REPO_ROOT}\artifacts\stormlib-v9.40\x64\StormLib.dll")


def pack(staged_dir: Path, out_mpq: Path) -> None:
    out_mpq.parent.mkdir(parents=True, exist_ok=True)
    if out_mpq.exists():
        out_mpq.unlink()
    proc = subprocess.run(
        [sys.executable, str(_PACK_SCRIPT), str(staged_dir), str(out_mpq),
         "--stormlib", str(find_stormlib())],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0 or not out_mpq.is_file():
        sys.stdout.write(proc.stdout or "")
        sys.stderr.write(proc.stderr or "")
        raise SystemExit(f"[FAIL] 打包失败: {staged_dir} -> {out_mpq}")
    print(f"[pack ] {out_mpq.name}  {out_mpq.stat().st_size:,} bytes")


def diagnose_mount_gap(staged_dir: Path, d: closure_doctor.Diagnosis) -> None:
    """指认形态 M 的两个子形态；未命中 M1 的一律显式清点为 M2，不留静默分支。"""
    map_script = staged_dir / "MapScript.galaxy"
    if not map_script.is_file():
        return
    script_text = map_script.read_text(encoding="utf-8", errors="replace")
    base_data = staged_dir / "Base.SC2Data"
    present = {p.stem.lower(): p.stem for p in base_data.glob("*.galaxy")} \
        if base_data.is_dir() else {}

    m1: dict[str, set[str]] = {}
    m2: dict[str, set[str]] = {}
    for sym in list(d.undefined_idents) + list(d.undefined_calls):
        m = RE_LIB_PREFIX.match(sym)
        if not m:
            continue
        stem = present.get(("lib" + m.group(1)).lower())
        if stem is None:
            m2.setdefault("Lib" + m.group(1), set()).add(sym)
        elif f'include "{stem}"' not in script_text:
            m1.setdefault(stem, set()).add(sym)
        # else: 已挂载且已定义，undefined 另有原因（交给 closure_doctor 的其他形态）

    for stem, syms in sorted(m1.items()):
        print(f"[HINT ] 形态 M1 挂载缺口: {stem}.galaxy 物理存在但 MapScript 未 include"
              f"（{len(syms)} 个符号，如 {sorted(syms)[0]}）")
        print("        ⇒ 查 launcher 的 include 门控"
              "（cmre-on-demand-overlay.ps1 的 $IsAlengerCommander 分支）。")
    for stem, syms in sorted(m2.items()):
        print(f"[HINT ] 形态 M2 生成闭包溢出: {stem}.galaxy 在暂存目录里**根本不存在**，"
              f"生成的 bundle 却引用了它（{len(syms)} 个符号，如 {sorted(syms)[0]}）")
        print("        ⇒ 这不是生成器造假符号，是 bundle 按别的闭包生成的。"
              "跑 `--fix` 净化 bundle，别去改生成器、也别去 launcher 硬塞 include。")


def sanitize(staged_dir: Path, mpq_path: Path) -> int:
    """按目标图真实符号表净化生成 bundle，返回改动的文件数。"""
    unit = compile_unit.resolve(mpq_path)
    available = set(unit.symbols)
    base_data = staged_dir / "Base.SC2Data"
    changed = 0
    for pattern in SANITIZE_GLOBS:
        for path in sorted(base_data.glob(pattern)):
            # 【勿改回 read_text()】默认 universal-newlines 会把 CRLF 悄悄读成 \n，
            # 于是「原文是 CRLF 就写回 CRLF」的判据永远不成立，一次净化把**整个文件**
            # 的行尾全换成 LF：diff 显示 1,510c1,510，真正的 1 行改动彻底淹没在噪声里，
            # 评审根本没法确认净化只动了该动的地方。newline="" 才是原样读。
            with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
                text = fh.read()
            crlf = "\r\n" in text
            new_text, records = sanitize_adapters.sanitize_text(
                text.replace("\r\n", "\n") if crlf else text, available)
            if crlf:
                new_text = new_text.replace("\n", "\r\n")
            if new_text == text:
                continue
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(new_text)
            changed += 1
            # 两类改动严重性差一个量级，混报会掩盖真问题：
            #   表行剔除 = 少一个 funcref 候选（解析返回 null，可恢复）
            #   函数降级 = 整个 gen.* 调用变 FUNCTION_NOT_IN_MAP（能力真的没了）
            pruned = sorted({s for r in records if r.get("kind") == "table-prune"
                             for s in r["missing"]})
            degraded = [r["name"] for r in records if r["start"] >= 0]
            bits = []
            if pruned:
                bits.append(f"funcref 表剔除 {len(pruned)} 项（{pruned[0]}"
                            f"{' 等' if len(pruned) > 1 else ''}）")
            if degraded:
                bits.append(f"函数降级 {len(degraded)} 个（{', '.join(degraded[:3])}"
                            f"{' 等' if len(degraded) > 3 else ''}）")
            print(f"[fix  ] {path.name}: " + "；".join(bits or ["无记录改动"]))
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description="暂存地图编译闭包预检门禁")
    ap.add_argument("staged_dir", type=Path, help="launcher 暂存出的 .SC2Map 目录")
    ap.add_argument("--out", type=Path, default=None, help="打包落地路径（默认临时目录）")
    ap.add_argument("--keep", action="store_true", help="保留打包产物便于复查")
    ap.add_argument("--fix", action="store_true",
                    help="体检失败时按真实符号表净化生成 bundle（原地改暂存目录）后复检")
    a = ap.parse_args()

    staged = a.staged_dir.resolve()
    if not staged.is_dir():
        print(f"[FAIL] 不是目录（本门禁只吃 launcher 暂存的目录形态）: {staged}")
        return 2

    tmp_dir = None
    if a.out:
        out_mpq = a.out.resolve()
    else:
        tmp_dir = tempfile.mkdtemp(prefix="staged-doctor-")
        out_mpq = Path(tmp_dir) / (staged.stem + ".SC2Map")

    try:
        pack(staged, out_mpq)
        d = closure_doctor.diagnose(out_mpq)
        code = closure_doctor.report(d, staged.name)
        diagnose_mount_gap(staged, d)
        if code == 0 or not a.fix:
            return code

        print("[fix  ] 体检未过且指定了 --fix，按目标图真实符号表净化生成 bundle …")
        if sanitize(staged, out_mpq) == 0:
            print("[FAIL] --fix 没有产生任何改动：问题不在生成 bundle 里，"
                  "别指望净化能救，回去看上面的形态指认。")
            return 1

        pack(staged, out_mpq)
        d2 = closure_doctor.diagnose(out_mpq)
        code2 = closure_doctor.report(d2, staged.name + " (fixed)")
        diagnose_mount_gap(staged, d2)
        return code2
    finally:
        if tmp_dir and not a.keep:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
