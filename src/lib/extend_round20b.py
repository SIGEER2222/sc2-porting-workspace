"""CMLib :: Round20b —— 补齐 DataTable 强类型族缺口 + 单位→单元素组便捷构造。

来源：round20 真机断言编写时暴露的缺口（selftest 引用 CMLib_DTSetInt / CMLib_UGOf 未命中）。
签名全部取自 natives.galaxy 权威定义：
    native void  DataTableSetInt    (bool global, string name, int val);
    native int   DataTableGetInt    (bool global, string name);
    native void  DataTableSetFixed  (bool global, string name, fixed val);
    native fixed DataTableGetFixed  (bool global, string name);
    native void  DataTableSetString (bool global, string name, string val);
    native string DataTableGetString(bool global, string name);
    native void  DataTableSetUnit   (bool global, string name, unit val);
    native unit  DataTableGetUnit   (bool global, string name);
    native void  DataTableSetPoint  (bool global, string name, point val);
    native point DataTableGetPoint  (bool global, string name);
    native unitgroup UnitGroupEmpty ();
    native void  UnitGroupAdd (unitgroup inGroup, unit inUnit);
"""
import sys
from pathlib import Path

CM = Path(__file__).resolve().parent / "scripts" / "cmlib"
MARK = "CMLib :: Round20b"

BLOCKS = {}

BLOCKS["cmlib_core_h.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round20b —— DataTable 强类型族补全（带 scope 参数）
// 说明：CMLib_Store*/CMLib_Load* 是 global=true 固定的老接口；DT* 系列显式带
//       lp_global，local 表（false）用于「本触发器线程私有」的临时状态。
// -----------------------------------------------------------------------------
void   CMLib_DTSetInt(bool lp_global, string lp_key, int lp_value);
int    CMLib_DTGetInt(bool lp_global, string lp_key, int lp_fallback);
void   CMLib_DTSetFixed(bool lp_global, string lp_key, fixed lp_value);
fixed  CMLib_DTGetFixed(bool lp_global, string lp_key, fixed lp_fallback);
void   CMLib_DTSetString(bool lp_global, string lp_key, string lp_value);
string CMLib_DTGetString(bool lp_global, string lp_key, string lp_fallback);
void   CMLib_DTSetUnit(bool lp_global, string lp_key, unit lp_value);
unit   CMLib_DTGetUnit(bool lp_global, string lp_key);           // 缺键返回 null
void   CMLib_DTSetPoint(bool lp_global, string lp_key, point lp_value);
point  CMLib_DTGetPoint(bool lp_global, string lp_key);          // 缺键返回 null
"""

BLOCKS["cmlib_core.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round20b —— DataTable 强类型族补全
// -----------------------------------------------------------------------------

void CMLib_DTSetInt(bool lp_global, string lp_key, int lp_value) {
    if (lp_key == "") { return; }
    DataTableSetInt(lp_global, lp_key, lp_value);
}

int CMLib_DTGetInt(bool lp_global, string lp_key, int lp_fallback) {
    if (lp_key == "") { return lp_fallback; }
    if (DataTableValueExists(lp_global, lp_key) == false) { return lp_fallback; }
    return DataTableGetInt(lp_global, lp_key);
}

void CMLib_DTSetFixed(bool lp_global, string lp_key, fixed lp_value) {
    if (lp_key == "") { return; }
    DataTableSetFixed(lp_global, lp_key, lp_value);
}

fixed CMLib_DTGetFixed(bool lp_global, string lp_key, fixed lp_fallback) {
    if (lp_key == "") { return lp_fallback; }
    if (DataTableValueExists(lp_global, lp_key) == false) { return lp_fallback; }
    return DataTableGetFixed(lp_global, lp_key);
}

void CMLib_DTSetString(bool lp_global, string lp_key, string lp_value) {
    if (lp_key == "") { return; }
    DataTableSetString(lp_global, lp_key, lp_value);
}

string CMLib_DTGetString(bool lp_global, string lp_key, string lp_fallback) {
    if (lp_key == "") { return lp_fallback; }
    if (DataTableValueExists(lp_global, lp_key) == false) { return lp_fallback; }
    return DataTableGetString(lp_global, lp_key);
}

void CMLib_DTSetUnit(bool lp_global, string lp_key, unit lp_value) {
    if (lp_key == "") { return; }
    DataTableSetUnit(lp_global, lp_key, lp_value);
}

unit CMLib_DTGetUnit(bool lp_global, string lp_key) {
    if (lp_key == "") { return null; }
    if (DataTableValueExists(lp_global, lp_key) == false) { return null; }
    return DataTableGetUnit(lp_global, lp_key);
}

void CMLib_DTSetPoint(bool lp_global, string lp_key, point lp_value) {
    if (lp_key == "") { return; }
    DataTableSetPoint(lp_global, lp_key, lp_value);
}

point CMLib_DTGetPoint(bool lp_global, string lp_key) {
    if (lp_key == "") { return null; }
    if (DataTableValueExists(lp_global, lp_key) == false) { return null; }
    return DataTableGetPoint(lp_global, lp_key);
}
"""

BLOCKS["cmlib_unit_h.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round20b —— 单位 → 单元素单位组
// -----------------------------------------------------------------------------
unitgroup CMLib_UGOf(unit lp_unit);          // null 单位返回空组，绝不返回 null
"""

BLOCKS["cmlib_unit.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round20b —— 单位 → 单元素单位组
// -----------------------------------------------------------------------------

unitgroup CMLib_UGOf(unit lp_unit) {
    unitgroup lv_g;

    lv_g = UnitGroupEmpty();
    if (lp_unit == null) { return lv_g; }
    UnitGroupAdd(lv_g, lp_unit);
    return lv_g;
}
"""


def main():
    changed = 0
    for name, block in BLOCKS.items():
        path = CM / name
        if not path.exists():
            print("[extend20b] 缺文件: %s" % path)
            return 1
        text = path.read_text(encoding="utf-8")
        if MARK in text:
            print("[extend20b] 已存在，跳过: %s" % name)
            continue
        if not text.endswith("\n"):
            text += "\n"
        path.write_text(text + block, encoding="utf-8", newline="\n")
        print("[extend20b] 追加: %s" % name)
        changed += 1
    print("[extend20b] 完成，改动 %d 个文件" % changed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
