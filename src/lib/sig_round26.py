# -*- coding: utf-8 -*-
"""
sig_round26.py — 把 check_native_ledger.py 报出的幽灵项，逐个抽出权威引擎签名。

为什么要单独一步：round26 的判据只回答「谁没交代」，不回答「它长什么样」。
封装一个 native 之前必须拿到**权威签名**（参数个数、类型、返回值），
靠名字猜参数正是 round25 §12.2 那种「语义与参数名不符」事故的温床。

两个来源，优先级从高到低：
  1. 官方 .galaxy 的 `native` 声明行（最直接）
  2. NativeLib.TriggerLib 的 FunctionDef + ParamDef（有些符号只有这个）

输出 UTF-8 JSON，避免 GBK 控制台把结论烤糊。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
GAMEDATA = (REPO / "reference" / "sc2mapster" / "SC2GameData" / "mods"
            / "core.sc2mod" / "base.sc2data")
TRIG = GAMEDATA / "TriggerLibs"

GHOSTS = """
AISetFilterEnergy
AISetStockAlias AISetStockFree AISetStockTechNextUnCap
CatalogEntryClass CatalogEntryParent CatalogFieldCount CatalogFieldGet
CatalogFieldIsArray CatalogFieldIsScope CatalogFieldType CatalogFieldTypeCategory
CatalogFieldValueGetFlagsAsInt CatalogReferenceCount CatalogReferenceGet
CatalogReferenceGetAsInt
CinematicDataRun CinematicDataStop CinematicMode CinematicOverlay
OrderGetPlayer OrderGetTargetItem OrderSetAbilityCommand OrderSetFlag
OrderSetPlayer OrderSetTargetItem OrderSetTargetPassenger OrderSetTargetPlacement
OrderTargetingItem OrderTargetingRelativePoint OrderTargetingUnitGroup
PointFromId PointFromName PointInterpolate PointPathingCliffLevel PointReflect
PointSet PointSetHeight PointsInRange
RegionAttachToUnit RegionFromId RegionFromName RegionGetAttachUnit
RegionGetOffset RegionSetCenter RegionSetOffset
StringCase StringCompare StringContains StringExternalAsset StringExternalHotkey
StringReplace StringReplaceWord StringToAbilCmd StringToDateTime StringWord
TimerLastStarted TimerWindowResetPosition TimerWindowSetFixedHeight
TimerWindowSetGapWidth TimerWindowSetPosition TimerWindowSetProgressColor
TimerWindowSetStyle TimerWindowSetTimer TimerWindowShowBorder
TimerWindowShowProgressBar TimerWindowVisible
TransmissionSendForPlayerSelect TransmissionSetOption
TransmissionSourceSetBypassMessageLog TransmissionSourceSetPauseAllowed
TransmissionSourceSetStreamingAllowed
VictoryPanelSetCustomStatisticText VictoryPanelSetCustomStatisticValue
""".split()


def decl_signatures() -> dict[str, dict]:
    """来源一：.galaxy 里的 `native` 声明 **以及** 普通函数定义。

    两个坑，都是这一版才踩出来的：

    1. **多行声明**。`natives_missing.galaxy:135` 的 AISetFilterEnergy 参数换行写，
       单行正则匹配不到 -> 回落到 ParamDef 元数据。而元数据是**不权威**的：
       它给 TransmissionSendForPlayerSelect 的返回类型是 `transmission`，
       真实声明是 `int`。错得毫无征兆，因为「transmission 类型的发送函数返回
       transmission」听起来天经地义。
    2. **不是所有 <FlagNative/> 都真是 native**。AISetStockAlias / AISetStockFree
       在 `AI.galaxy:574/581` 是**普通 Galaxy 函数**，签名 `(int, int, string
       makeType, string aliasType)`；ParamDef 却写 `gamelink unitType`。
       信元数据就会把 string 参数当 gamelink 传。

    结论：签名一律以 .galaxy 源码为准，ParamDef 只当「有这么个符号」的存在性证据。
    """
    out: dict[str, dict] = {}
    want = set(GHOSTS)
    # 跨行匹配：native 声明以 `;` 收尾，普通函数定义以 `{` 收尾。
    rx_native = re.compile(
        r"\bnative\s+([\w\[\]<>]+)\s+(\w+)\s*\(([^;{]*?)\)\s*;", re.S)
    # 注意这里**不能**开 re.S：`(?!...)` 里的 `.` 一旦能跨行，负向先行断言就会
    # 一路看到文件末尾，只要文件里任何地方出现过 `native` 就整体失配 ——
    # 表现为「一个普通函数都抓不到」，而它不报错，只是安静地少给你两个符号。
    rx_func = re.compile(
        r"^(?!.*\bnative\b)[ \t]*([\w\[\]<>]+)[ \t]+(\w+)[ \t]*\(([^;{]*?)\)[ \t]*\{",
        re.M)
    for p in sorted(TRIG.rglob("*.galaxy")):
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for kind, rx in (("native", rx_native), ("libfunc", rx_func)):
            for m in rx.finditer(txt):
                name = m.group(2)
                if name not in want or name in out:
                    continue
                params = " ".join(m.group(3).split())
                line_no = txt.count("\n", 0, m.start()) + 1
                out[name] = {
                    "kind": kind,
                    "ret": m.group(1),
                    "params": params,
                    "src": f"{p.relative_to(TRIG)}:{line_no}",
                    "raw": f"{'native ' if kind == 'native' else ''}"
                           f"{m.group(1)} {name}({params});",
                }
    return out


def flag_signatures() -> dict[str, dict]:
    """来源二：NativeLib.TriggerLib FunctionDef + ParamDef 反查。"""
    p = TRIG / "NativeLib.TriggerLib"
    if not p.exists():
        return {}
    txt = p.read_text(encoding="utf-8", errors="replace")

    # ParamDef: id -> (identifier, type)
    params: dict[str, tuple[str, str]] = {}
    for block in re.findall(
            r'<Element\s+Type="ParamDef"\s+Id="(\w+)">(.*?)</Element>', txt, re.S):
        pid, body = block
        ident = re.search(r"<Identifier>(\w+)</Identifier>", body)
        ptype = re.search(r'<ParameterType>\s*<Type\s+Value="(\w+)"', body)
        params[pid] = (ident.group(1) if ident else "?",
                       ptype.group(1) if ptype else "?")

    want = set(GHOSTS)
    out: dict[str, dict] = {}
    for block in re.findall(
            r'<Element\s+Type="FunctionDef"\s+Id="(\w+)">(.*?)</Element>', txt, re.S):
        fid, body = block
        ident = re.search(r"<Identifier>(\w+)</Identifier>", body)
        if not ident or ident.group(1) not in want:
            continue
        name = ident.group(1)
        plist = []
        # 注意 <Parameter Type="ParamDef" Library="Ntve" Id="..."/> 中间还夹着
        # Library 属性 —— 早一版正则写死了属性相邻顺序，于是所有 FLAG-ONLY 符号
        # 都被解析成「零参数」。零参数看上去像个正常结论，不会报错，
        # 正是那种「判据静默给出错误答案」的形态。
        for pid in re.findall(r'<Parameter\s+Type="ParamDef"[^>]*?\sId="(\w+)"', body):
            ident2, t2 = params.get(pid, ("?", "?"))
            plist.append(f"{t2} {ident2}")
        rt = re.search(r'<ReturnType>\s*<Type\s+Value="(\w+)"', body)
        out[name] = {
            "ret": rt.group(1) if rt else "void",
            "params": ", ".join(plist),
            "flagnative": "<FlagNative" in body,
            "src": "NativeLib.TriggerLib#" + fid,
        }
    return out


def main() -> int:
    d = decl_signatures()
    f = flag_signatures()
    result = {}
    for s in GHOSTS:
        result[s] = {"decl": d.get(s), "flag": f.get(s)}
    missing = [s for s in GHOSTS if not d.get(s) and not f.get(s)]
    # 元数据与源码打架的，一律以源码为准，但必须报出来 —— 这类分歧是
    # 「照参数名理解、拿到静默错误结果」的直接前兆。
    conflicts = []
    for s in GHOSTS:
        dd, ff = d.get(s), f.get(s)
        if not dd or not ff:
            continue
        if dd["ret"] != ff["ret"]:
            conflicts.append(f"{s}: ret decl={dd['ret']} vs flag={ff['ret']}")
        n_d = len([x for x in dd["params"].split(",") if x.strip()])
        n_f = len([x for x in ff["params"].split(",") if x.strip()])
        if n_d != n_f:
            conflicts.append(f"{s}: argc decl={n_d} vs flag={n_f}")
    result["_conflicts"] = conflicts

    outp = REPO.parent / "out" / "ledger_sigs_round26.json"
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                    encoding="utf-8")

    print(f"ghosts={len(GHOSTS)} decl={len(d)} flag={len(f)} "
          f"no_signature={len(missing)}")
    if missing:
        print("NO-SIG: " + ", ".join(missing))
    print("wrote " + str(outp))
    return 0


if __name__ == "__main__":
    sys.exit(main())
