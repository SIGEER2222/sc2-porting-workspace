"""CMLib :: Round26 —— 把台账门禁扫出的 74 个「幽灵符号」逐族封装落库。

round25 建立了原生符号台账门禁（check_native_ledger.py），判据是：

    引擎声明全集(自动) == 库内实际调用(自动) ∪ 登记拒绝(人写)   且两者不相交

round26 把它从 `aifilter` 单族扩到 14 族，一扩就炸出 **74 个 ghost**
（族内有符号既没被调用、也没被登记拒绝 —— 也就是"漏了还不知道漏了"）。

## 为什么是"全部封装"而不是"部分登记拒绝"

round25 拒绝 `AISetFilterCanAttackEnemy` 是有硬证据的：阈值 0→1→5 拿到
空→空→非空，**非单调 = 语义不可预测**，封了就是骗调用方。

这 74 个不一样。逐个抽了权威签名（`sig_round26.py` → `out/ledger_sigs_round26.json`，
decl 74 / flag 65 / no_signature 0），全部是同构、可预测的
getter / setter / 构造器族，没有一个出现"参数名与语义不符"的迹象。
所以本轮判定：**全部封装，零 @ledger-reject**。

## 抽签名时踩到的坑（必须写下来）

`NativeLib.TriggerLib` 的 ParamDef 元数据**不权威**，和 `.galaxy` 源码会打架：

  · AISetStockAlias   元数据 `gamelink unitType` / 源码 `string makeType`
  · TransmissionSendForPlayerSelect 元数据返回 `transmission` / 源码返回 `int`
  · CatalogEntryParent 元数据返回 `catalogentry` / 源码返回 `string`
  · CatalogFieldGet    元数据返回 `catalogfieldname` / 源码返回 `string`

一律以 `.galaxy` 源码为准，元数据只当"存在性证据"。这正是 round25 §12.2
那类事故的同款诱因：照参数名理解，在最常见取值上拿到静默错误结果。

另外确认：`AISetStockAlias` / `AISetStockFree` 是 `core.sc2mod/TriggerLibs/AI.galaxy`
里的**普通 Galaxy 库函数**（内部转调 AISetStock + AITechCount），不是 native。
同族的 `AISetStockTechNextUnCap` 才是 native。库里都只调用、不自声明。

## 落点

    cmlib_ai      1   AISetFilterEnergy
    cmlib_stock   3   AISetStockAlias / Free / TechNextUnCap
    cmlib_catalog 12  Catalog 反射 / 引用读取族
    cmlib_fx      4   Cinematic*
    cmlib_unit    12  Order* 11 + StringToAbilCmd
    cmlib_geo     15  Point* 8 + Region* 7
    cmlib_core    9   String*
    cmlib_panel   10  TimerWindow*
    cmlib_trig    1   TimerLastStarted
    cmlib_conv    5   Transmission*
    cmlib_board   2   VictoryPanelSetCustomStatistic*
                 ---
                  74
"""
import sys
from pathlib import Path

CM = Path(__file__).resolve().parent / "scripts" / "cmlib"
MARK = "CMLib :: Round26"

BLOCKS: dict[str, str] = {}

# ------------------------------------------------------------------- ai ------
BLOCKS["cmlib_ai_h.galaxy"] = r"""

// =============================================================================
// CMLib :: Round26 —— AIFilter 能量档
//
// 与 Life / Shields 完全同构的区间过滤，之前纯粹是漏了。守门逻辑复用
// CMLib_AIFilterRangeOk（filter 为 null、或 min > max 时空操作并告警）。
// =============================================================================

void CMLib_AIFilterEnergy(aifilter lp_filter, fixed lp_min, fixed lp_max);
"""

BLOCKS["cmlib_ai.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round26 —— AIFilter 能量档
// -----------------------------------------------------------------------------

void CMLib_AIFilterEnergy(aifilter lp_filter, fixed lp_min, fixed lp_max) {
    if (CMLib_AIFilterRangeOk("AIFilterEnergy", lp_filter, lp_min, lp_max) == false) {
        return;
    }
    AISetFilterEnergy(lp_filter, lp_min, lp_max);
}
"""

# ---------------------------------------------------------------- stock ------
BLOCKS["cmlib_stock_h.galaxy"] = r"""

// =============================================================================
// CMLib :: Round26 —— 库存别名 / 免费单位 / 科技解限
//
// 注意签名来源：AISetStockAlias / AISetStockFree 是 core.sc2mod 的 AI.galaxy
// 里的**普通库函数**（内部转调 AISetStock + AITechCount），不是 native；
// 编辑器元数据把 makeType 标成 gamelink，源码里其实是 string，以源码为准。
// =============================================================================

// 「已有 aliasType 的算进 makeType 的产能」——扩建同类建筑时避免重复下单。
void CMLib_StockAlias(int lp_player, int lp_count, string lp_makeType,
                      string lp_aliasType);
// 只有当 prereq 科技已完成时才下 makeType 的库存单（免费单位/解锁兵种常用）。
void CMLib_StockFree(int lp_player, int lp_count, string lp_makeType,
                     string lp_prereq);
// 下一档科技的矿/气解限阈值；负值按 0 处理。
void CMLib_StockTechUncap(int lp_player, int lp_unCapMinerals, int lp_unCapGas);
"""

BLOCKS["cmlib_stock.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round26 —— 库存别名 / 免费单位 / 科技解限
// -----------------------------------------------------------------------------

void CMLib_StockAlias(int lp_player, int lp_count, string lp_makeType,
                      string lp_aliasType) {
    if (lp_makeType == "") { return; }
    if (lp_aliasType == "") { return; }
    if (lp_count < 0) { return; }
    AISetStockAlias(lp_player, lp_count, lp_makeType, lp_aliasType);
}

void CMLib_StockFree(int lp_player, int lp_count, string lp_makeType,
                     string lp_prereq) {
    if (lp_makeType == "") { return; }
    if (lp_prereq == "") { return; }
    if (lp_count < 0) { return; }
    AISetStockFree(lp_player, lp_count, lp_makeType, lp_prereq);
}

void CMLib_StockTechUncap(int lp_player, int lp_unCapMinerals, int lp_unCapGas) {
    int lv_min;
    int lv_gas;

    lv_min = lp_unCapMinerals;
    lv_gas = lp_unCapGas;
    if (lv_min < 0) { lv_min = 0; }
    if (lv_gas < 0) { lv_gas = 0; }
    AISetStockTechNextUnCap(lp_player, lv_min, lv_gas);
}
"""

# -------------------------------------------------------------- catalog ------
BLOCKS["cmlib_catalog_h.galaxy"] = r"""

// =============================================================================
// CMLib :: Round26 —— Catalog 反射（scope/field 元信息）与引用读取
//
// 之前只封了「按 entry+fieldPath 读写值」，缺的是**反射面**：某个 scope 里
// 到底有哪些字段、字段是不是数组、是不是子 scope、类型是什么。做数据驱动的
// 通用面板 / 调试器时这一层是刚需，否则只能把字段名硬编码进脚本。
//
// 命名避让：已有的 CMLib_CatFieldCount 是「某 entry 某字段的**值**个数」
// （4 参），本轮的 CMLib_CatScopeFieldCount 是「某 scope 的**字段**个数」
// （1 参）。Galaxy 不支持重载，名字必须分开，别混。
//
// 索引口径：CatalogFieldGet 与 CatalogEntryGet 一致，均为 **1-based**；
// 越界返回空串（本库另加守门，index < 1 直接返回 ""，不进引擎）。
// =============================================================================

// entry 的类别 id（CUnit / CAbil / ... 的内部枚举）；entry 为空返回 0。
int    CMLib_CatEntryClass(int lp_catalog, string lp_entry);
// entry 的父条目（数据继承链上一级）；无父或非法返回 ""。
string CMLib_CatEntryParent(int lp_catalog, string lp_entry);
// scope（如 "Unit"、"Abil"）里的字段总数；scope 为空返回 0。
int    CMLib_CatScopeFieldCount(string lp_scope);
// scope 的第 index 个字段名，**1-based**；越界或非法返回 ""。
string CMLib_CatScopeFieldAt(string lp_scope, int lp_index);
// 字段是否数组 / 是否子 scope；任一参数为空一律 false。
bool   CMLib_CatFieldIsArray(string lp_scope, string lp_field);
bool   CMLib_CatFieldIsScope(string lp_scope, string lp_field);
// 字段类型名（字符串形态）；非法返回 ""。
string CMLib_CatFieldType(string lp_scope, string lp_field);
// 字段类型的大类枚举；非法返回 0。
int    CMLib_CatFieldTypeCat(string lp_scope, string lp_field);
// 把 flags 型字段整体读成位掩码 int；非法返回 0。
int    CMLib_CatGetFlags(int lp_catalog, string lp_entry, string lp_fieldPath,
                         int lp_player);
// Catalog 引用（"Unit,Marine,LifeMax" 这种整串形态）的元素个数 / 读值。
int    CMLib_CatRefCount(string lp_reference, int lp_player);
string CMLib_CatRefGet(string lp_reference, int lp_player);
int    CMLib_CatRefInt(string lp_reference, int lp_player);
"""

BLOCKS["cmlib_catalog.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round26 —— Catalog 反射与引用读取
// -----------------------------------------------------------------------------

int CMLib_CatEntryClass(int lp_catalog, string lp_entry) {
    if (lp_entry == "") { return 0; }
    return CatalogEntryClass(lp_catalog, lp_entry);
}

string CMLib_CatEntryParent(int lp_catalog, string lp_entry) {
    string lv_s;

    if (lp_entry == "") { return ""; }
    lv_s = CatalogEntryParent(lp_catalog, lp_entry);
    if (lv_s == null) { return ""; }
    return lv_s;
}

int CMLib_CatScopeFieldCount(string lp_scope) {
    if (lp_scope == "") { return 0; }
    return CatalogFieldCount(lp_scope);
}

string CMLib_CatScopeFieldAt(string lp_scope, int lp_index) {
    string lv_s;

    if (lp_scope == "") { return ""; }
    // 1-based，与 CatalogEntryGet 同口径；< 1 不进引擎。
    if (lp_index < 1) { return ""; }
    if (lp_index > CatalogFieldCount(lp_scope)) { return ""; }
    lv_s = CatalogFieldGet(lp_scope, lp_index);
    if (lv_s == null) { return ""; }
    return lv_s;
}

bool CMLib_CatFieldIsArray(string lp_scope, string lp_field) {
    if (lp_scope == "") { return false; }
    if (lp_field == "") { return false; }
    return CatalogFieldIsArray(lp_scope, lp_field);
}

bool CMLib_CatFieldIsScope(string lp_scope, string lp_field) {
    if (lp_scope == "") { return false; }
    if (lp_field == "") { return false; }
    return CatalogFieldIsScope(lp_scope, lp_field);
}

string CMLib_CatFieldType(string lp_scope, string lp_field) {
    string lv_s;

    if (lp_scope == "") { return ""; }
    if (lp_field == "") { return ""; }
    lv_s = CatalogFieldType(lp_scope, lp_field);
    if (lv_s == null) { return ""; }
    return lv_s;
}

int CMLib_CatFieldTypeCat(string lp_scope, string lp_field) {
    if (lp_scope == "") { return 0; }
    if (lp_field == "") { return 0; }
    return CatalogFieldTypeCategory(lp_scope, lp_field);
}

int CMLib_CatGetFlags(int lp_catalog, string lp_entry, string lp_fieldPath,
                      int lp_player) {
    if (lp_entry == "") { return 0; }
    if (lp_fieldPath == "") { return 0; }
    return CatalogFieldValueGetFlagsAsInt(lp_catalog, lp_entry, lp_fieldPath,
                                          lp_player);
}

int CMLib_CatRefCount(string lp_reference, int lp_player) {
    if (lp_reference == "") { return 0; }
    return CatalogReferenceCount(lp_reference, lp_player);
}

string CMLib_CatRefGet(string lp_reference, int lp_player) {
    string lv_s;

    if (lp_reference == "") { return ""; }
    lv_s = CatalogReferenceGet(lp_reference, lp_player);
    if (lv_s == null) { return ""; }
    return lv_s;
}

int CMLib_CatRefInt(string lp_reference, int lp_player) {
    if (lp_reference == "") { return 0; }
    return CatalogReferenceGetAsInt(lp_reference, lp_player);
}
"""

# ------------------------------------------------------------------- fx ------
BLOCKS["cmlib_fx_h.galaxy"] = r"""

// =============================================================================
// CMLib :: Round26 —— 过场模式 / 图像叠层 / 数据驱动过场
//
// fx 模块此前只封了 CinematicFade（CMLib_FadeIn / FadeOut / FadeToColor），
// 缺「进入过场模式」这一整块 —— 而它才是战役 mod 每关开头必写的样板：
// 隐藏 UI、屏蔽输入、切黑边。
//
// 边界（不过度承诺）：CMLib_CineDataRun 需要数据层预先配好 Cinematic 条目，
// 空图里没有可用 id，本库只做**调用面覆盖 + 非法 id 守门**，不对播放效果
// 做任何真机断言。
// =============================================================================

// 进/出过场模式；players 为 null 时作用于当前活跃玩家组，duration 负值按 0。
void CMLib_CineMode(playergroup lp_players, bool lp_on, fixed lp_duration);
// 图像叠层淡入/淡出；淡入时 imagePath 不可为空（空则空操作）。
void CMLib_CineOverlay(bool lp_fadeIn, fixed lp_duration, string lp_imagePath,
                       fixed lp_transparency, bool lp_waitUntilDone);
// 播放数据层定义的过场；id < 0 直接空操作。
void CMLib_CineDataRun(int lp_id, playergroup lp_players, bool lp_waitUntilDone);
// 停止当前数据驱动过场。
void CMLib_CineDataStop();
"""

BLOCKS["cmlib_fx.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round26 —— 过场模式 / 图像叠层 / 数据驱动过场
// -----------------------------------------------------------------------------

void CMLib_CineMode(playergroup lp_players, bool lp_on, fixed lp_duration) {
    playergroup lv_to;
    fixed       lv_d;

    lv_to = lp_players;
    if (lv_to == null) { lv_to = PlayerGroupActive(); }
    lv_d = lp_duration;
    if (lv_d < 0.0) { lv_d = 0.0; }
    CinematicMode(lv_to, lp_on, lv_d);
}

void CMLib_CineOverlay(bool lp_fadeIn, fixed lp_duration, string lp_imagePath,
                       fixed lp_transparency, bool lp_waitUntilDone) {
    fixed lv_d;

    // 淡入却没给图 = 调用方写错了；引擎行为未定义，宁可空操作。
    if (lp_fadeIn == true && lp_imagePath == "") { return; }
    lv_d = lp_duration;
    if (lv_d < 0.0) { lv_d = 0.0; }
    CinematicOverlay(lp_fadeIn, lv_d, lp_imagePath, lp_transparency,
                     lp_waitUntilDone);
}

void CMLib_CineDataRun(int lp_id, playergroup lp_players, bool lp_waitUntilDone) {
    playergroup lv_to;

    if (lp_id < 0) { return; }
    lv_to = lp_players;
    if (lv_to == null) { lv_to = PlayerGroupActive(); }
    CinematicDataRun(lp_id, lv_to, lp_waitUntilDone);
}

void CMLib_CineDataStop() {
    CinematicDataStop();
}
"""

# ----------------------------------------------------------------- unit ------
BLOCKS["cmlib_unit_h.galaxy"] = r"""

// =============================================================================
// CMLib :: Round26 —— order 对象补齐（拥有者 / 物品目标 / 乘客 / 放置 / 组目标）
//
// 之前只封了「点目标 / 单位目标」两条最常见的路径，order 对象本身还有一整套
// setter 没进库：改拥有者、改能力命令、改 flag、物品目标、乘客目标、
// 建筑放置校验，以及三种额外的构造器（相对点 / 单位组 / 物品）。
//
// 口径提醒：flag 序号由数据层定义，引擎没有导出 c_orderFlag* 常量族，只能传
// 裸 int —— 这跟已有的 CMLib_OrderFlag 是同一条约定。
// =============================================================================

// order 的拥有者玩家；order 为 null 返回 0。
int   CMLib_OrderPlayer(order lp_order);
void  CMLib_OrderSetPlayer(order lp_order, int lp_player);
// 物品目标（Item 语义，与 Unit 目标是两条独立通道）。
unit  CMLib_OrderTargetItem(order lp_order);
void  CMLib_OrderSetTargetItem(order lp_order, unit lp_item);
// 换掉 order 携带的能力命令。
void  CMLib_OrderSetAbilCmd(order lp_order, abilcmd lp_cmd);
// 置 flag；flag 序号为负一律忽略（与 CMLib_OrderFlag 读侧对称）。
void  CMLib_OrderSetFlag(order lp_order, int lp_flag, bool lp_value);
// 乘客目标（装载/卸载类命令用）。传 null 表示清空，属合法用法。
void  CMLib_OrderSetPassenger(order lp_order, unit lp_unit);
// 建筑放置：返回该点是否可放置；point 为 null 直接 false。
bool  CMLib_OrderSetPlacement(order lp_order, point lp_point, unit lp_placer,
                              string lp_type);
// 构造器三件套：物品目标 / 相对点 / 单位组。
order CMLib_OrderOnItem(abilcmd lp_cmd, unit lp_item);
order CMLib_OrderAtRelative(abilcmd lp_cmd, point lp_point);
order CMLib_OrderOnGroup(abilcmd lp_cmd, unitgroup lp_group);
// "Ability,CmdIndex" 形态的字符串直转 abilcmd；空串返回 null。
abilcmd CMLib_AbilCmdFromString(string lp_s);
"""

BLOCKS["cmlib_unit.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round26 —— order 对象补齐
// -----------------------------------------------------------------------------

int CMLib_OrderPlayer(order lp_order) {
    if (lp_order == null) { return 0; }
    return OrderGetPlayer(lp_order);
}

void CMLib_OrderSetPlayer(order lp_order, int lp_player) {
    if (lp_order == null) { return; }
    OrderSetPlayer(lp_order, lp_player);
}

unit CMLib_OrderTargetItem(order lp_order) {
    if (lp_order == null) { return null; }
    return OrderGetTargetItem(lp_order);
}

void CMLib_OrderSetTargetItem(order lp_order, unit lp_item) {
    if (lp_order == null) { return; }
    OrderSetTargetItem(lp_order, lp_item);
}

void CMLib_OrderSetAbilCmd(order lp_order, abilcmd lp_cmd) {
    if (lp_order == null) { return; }
    if (lp_cmd == null) { return; }
    OrderSetAbilityCommand(lp_order, lp_cmd);
}

void CMLib_OrderSetFlag(order lp_order, int lp_flag, bool lp_value) {
    if (lp_order == null) { return; }
    if (lp_flag < 0) { return; }
    OrderSetFlag(lp_order, lp_flag, lp_value);
}

void CMLib_OrderSetPassenger(order lp_order, unit lp_unit) {
    if (lp_order == null) { return; }
    // lp_unit 允许为 null —— 那是"清空乘客目标"的合法写法。
    OrderSetTargetPassenger(lp_order, lp_unit);
}

bool CMLib_OrderSetPlacement(order lp_order, point lp_point, unit lp_placer,
                             string lp_type) {
    if (lp_order == null) { return false; }
    if (lp_point == null) { return false; }
    return OrderSetTargetPlacement(lp_order, lp_point, lp_placer, lp_type);
}

order CMLib_OrderOnItem(abilcmd lp_cmd, unit lp_item) {
    if (lp_cmd == null) { return null; }
    return OrderTargetingItem(lp_cmd, lp_item);
}

order CMLib_OrderAtRelative(abilcmd lp_cmd, point lp_point) {
    if (lp_cmd == null) { return null; }
    if (lp_point == null) { return null; }
    return OrderTargetingRelativePoint(lp_cmd, lp_point);
}

order CMLib_OrderOnGroup(abilcmd lp_cmd, unitgroup lp_group) {
    if (lp_cmd == null) { return null; }
    if (lp_group == null) { return null; }
    return OrderTargetingUnitGroup(lp_cmd, lp_group);
}

abilcmd CMLib_AbilCmdFromString(string lp_s) {
    if (lp_s == "") { return null; }
    return StringToAbilCmd(lp_s);
}
"""

# ------------------------------------------------------------------ geo ------
BLOCKS["cmlib_geo_h.galaxy"] = r"""

// =============================================================================
// CMLib :: Round26 —— 编辑器预置点/区域的按名取用 + 点区域的原地改写
//
// 补的是两类刚需：
//   1. 编辑器里摆好的 Point / Region，脚本侧只能靠 *FromName / *FromId 取，
//      之前整族没进库，各 mod 只能裸调。
//   2. point / region 是**引用型句柄**，引擎提供了原地改写（PointSet /
//      PointSetHeight / RegionSetOffset / RegionSetCenter / RegionAttachToUnit）。
//      裸调最容易踩的坑是「以为拿到副本、实际改了别人手里的同一个对象」，
//      所以这里把命名写成动词明确的形态（Copy / SetXxx / Attach）。
//
// 命名口径：CMLib_PointCopy(dst, src) 语义 = 把 src 的坐标写进 dst，
// 对应引擎 PointSet(p1, p2)（p2 拷进 p1）。参数顺序刻意写成"目标在前"，
// 跟赋值语句读起来一致，避免记反。
// =============================================================================

// 编辑器预置点：按 id / 按名取；取不到返回 null。
point  CMLib_PointById(int lp_id);
point  CMLib_PointByName(string lp_name);
// 线性插值：fraction 0 = source，1 = dest（自动夹到 [0,1]）。
point  CMLib_PointLerp(point lp_source, point lp_dest, fixed lp_fraction);
// 该点所在的悬崖层高；点为 null 返回 0。
fixed  CMLib_PointCliffLevel(point lp_p);
// 以 dest 为轴、按角度镜像 source；任一为 null 返回 null。
point  CMLib_PointReflect(point lp_source, point lp_dest, fixed lp_angle);
// 原地拷贝：把 lp_src 的坐标写进 lp_dst（**会改 lp_dst 指向的对象**）。
void   CMLib_PointCopy(point lp_dst, point lp_src);
// 原地改高度。
void   CMLib_PointSetHeight(point lp_p, fixed lp_height);
// 两点是否在给定距离内；range 负值按 0（等价于"必须重合"）。
bool   CMLib_PointsWithin(point lp_a, point lp_b, fixed lp_range);

// 区域跟随单位：offset 为 null 按零偏移；unit 传 null = 解除跟随（官方语义）。
void   CMLib_RegionAttach(region lp_region, unit lp_unit, point lp_offset);
// 当前跟随的单位；没有则 null。
unit   CMLib_RegionAttachUnit(region lp_region);
// 编辑器预置区域：按 id / 按名取；取不到返回 null。
region CMLib_RegionById(int lp_id);
region CMLib_RegionByName(string lp_name);
// 区域整体偏移量读写。
point  CMLib_RegionOffset(region lp_region);
void   CMLib_RegionSetOffset(region lp_region, point lp_offset);
// 把区域整体挪到以某点为中心（引擎内部换算成 offset）。
void   CMLib_RegionSetCenter(region lp_region, point lp_center);
"""

BLOCKS["cmlib_geo.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round26 —— 预置点/区域按名取用 + 原地改写
// -----------------------------------------------------------------------------

point CMLib_PointById(int lp_id) {
    if (lp_id < 0) { return null; }
    return PointFromId(lp_id);
}

point CMLib_PointByName(string lp_name) {
    if (lp_name == "") { return null; }
    return PointFromName(lp_name);
}

point CMLib_PointLerp(point lp_source, point lp_dest, fixed lp_fraction) {
    fixed lv_f;

    if (lp_source == null) { return null; }
    if (lp_dest == null) { return null; }
    lv_f = lp_fraction;
    if (lv_f < 0.0) { lv_f = 0.0; }
    if (lv_f > 1.0) { lv_f = 1.0; }
    return PointInterpolate(lp_source, lp_dest, lv_f);
}

fixed CMLib_PointCliffLevel(point lp_p) {
    if (lp_p == null) { return 0.0; }
    return PointPathingCliffLevel(lp_p);
}

point CMLib_PointReflect(point lp_source, point lp_dest, fixed lp_angle) {
    if (lp_source == null) { return null; }
    if (lp_dest == null) { return null; }
    return PointReflect(lp_source, lp_dest, lp_angle);
}

void CMLib_PointCopy(point lp_dst, point lp_src) {
    if (lp_dst == null) { return; }
    if (lp_src == null) { return; }
    // 引擎口径：PointSet(p1, p2) 是"把 p2 拷进 p1"。
    PointSet(lp_dst, lp_src);
}

void CMLib_PointSetHeight(point lp_p, fixed lp_height) {
    if (lp_p == null) { return; }
    PointSetHeight(lp_p, lp_height);
}

bool CMLib_PointsWithin(point lp_a, point lp_b, fixed lp_range) {
    fixed lv_r;

    if (lp_a == null) { return false; }
    if (lp_b == null) { return false; }
    lv_r = lp_range;
    if (lv_r < 0.0) { lv_r = 0.0; }
    return PointsInRange(lp_a, lp_b, lv_r);
}

void CMLib_RegionAttach(region lp_region, unit lp_unit, point lp_offset) {
    point lv_off;

    if (lp_region == null) { return; }
    lv_off = lp_offset;
    if (lv_off == null) { lv_off = Point(0.0, 0.0); }
    // lp_unit == null 是官方认可的"解除跟随"，不拦。
    RegionAttachToUnit(lp_region, lp_unit, lv_off);
}

unit CMLib_RegionAttachUnit(region lp_region) {
    if (lp_region == null) { return null; }
    return RegionGetAttachUnit(lp_region);
}

region CMLib_RegionById(int lp_id) {
    if (lp_id < 0) { return null; }
    return RegionFromId(lp_id);
}

region CMLib_RegionByName(string lp_name) {
    if (lp_name == "") { return null; }
    return RegionFromName(lp_name);
}

point CMLib_RegionOffset(region lp_region) {
    if (lp_region == null) { return null; }
    return RegionGetOffset(lp_region);
}

void CMLib_RegionSetOffset(region lp_region, point lp_offset) {
    if (lp_region == null) { return; }
    if (lp_offset == null) { return; }
    RegionSetOffset(lp_region, lp_offset);
}

void CMLib_RegionSetCenter(region lp_region, point lp_center) {
    if (lp_region == null) { return; }
    if (lp_center == null) { return; }
    RegionSetCenter(lp_region, lp_center);
}
"""

# ----------------------------------------------------------------- core ------
BLOCKS["cmlib_core_h.galaxy"] = r"""

// =============================================================================
// CMLib :: Round26 —— 字符串族补齐（大小写 / 比较 / 包含 / 分词 / 替换 / 外部串）
//
// core 之前只有 CMLib_StartsWith / SplitAt / ParseInt 这几件自研工具，引擎
// 原生的字符串族基本没进库。补的时候把三个最容易记反的口径钉死在注释里：
//
//   · StringContains 的 location：c_stringBegin=0 / c_stringEnd=1 /
//     c_stringAnywhere=2。传错就是"以为在查子串、实际在查前缀"。
//   · StringWord 是 **1-based**：官方例子 StringWord("klaatu barada nikto", 2)
//     == "barada"。
//   · StringReplaceWord 的 maxCount 用 c_stringReplaceAll(-1) 表示全替换。
//
// StringReplace 替换的是**字符下标区间**（不是子串匹配），别和
// StringReplaceWord 混用 —— 后者才是"按词替换"。
// =============================================================================

// 全大写 / 全小写（upper = true 转大写）。
string   CMLib_StrCase(string lp_s, bool lp_upper);
// 字典序比较：< 0 / 0 / > 0。caseSens 用 c_stringCase / c_stringNoCase。
int      CMLib_StrCompare(string lp_a, string lp_b, bool lp_caseSens);
// 前缀 / 后缀 / 任意位置包含，location 见上方口径说明；非法 location 按任意位置。
bool     CMLib_StrContains(string lp_s, string lp_sub, int lp_location,
                           bool lp_caseSens);
// 外部化字符串表查表：素材路径型 / 快捷键型。
text     CMLib_StrAsset(string lp_s);
text     CMLib_StrHotkey(string lp_s);
// 替换字符下标区间 [start, end]；start > end 或空串原样返回。
string   CMLib_StrReplaceRange(string lp_s, string lp_replace, int lp_start,
                               int lp_end);
// 按词替换；maxCount 传 c_stringReplaceAll 表示全部。
string   CMLib_StrReplaceWord(string lp_s, string lp_word, string lp_replace,
                              int lp_maxCount, bool lp_caseSens);
// 取第 index 个空白分隔的词，**1-based**；越界返回 ""。
string   CMLib_StrWord(string lp_s, int lp_index);
// 字符串转 datetime。注意：格式由引擎解析，本库不做格式校验，
// 空串会被替换成一个固定的合法占位串以避免解析失败中断触发器。
datetime CMLib_StrToDateTime(string lp_s);
"""

BLOCKS["cmlib_core.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round26 —— 字符串族补齐
// -----------------------------------------------------------------------------

string CMLib_StrCase(string lp_s, bool lp_upper) {
    if (lp_s == "") { return ""; }
    return StringCase(lp_s, lp_upper);
}

int CMLib_StrCompare(string lp_a, string lp_b, bool lp_caseSens) {
    return StringCompare(lp_a, lp_b, lp_caseSens);
}

bool CMLib_StrContains(string lp_s, string lp_sub, int lp_location,
                       bool lp_caseSens) {
    int lv_loc;

    if (lp_s == "") { return false; }
    if (lp_sub == "") { return false; }
    lv_loc = lp_location;
    if (lv_loc < c_stringBegin) { lv_loc = c_stringAnywhere; }
    if (lv_loc > c_stringAnywhere) { lv_loc = c_stringAnywhere; }
    return StringContains(lp_s, lp_sub, lv_loc, lp_caseSens);
}

text CMLib_StrAsset(string lp_s) {
    if (lp_s == "") { return StringToText(""); }
    return StringExternalAsset(lp_s);
}

text CMLib_StrHotkey(string lp_s) {
    if (lp_s == "") { return StringToText(""); }
    return StringExternalHotkey(lp_s);
}

string CMLib_StrReplaceRange(string lp_s, string lp_replace, int lp_start,
                             int lp_end) {
    string lv_out;

    if (lp_s == "") { return ""; }
    if (lp_start > lp_end) { return lp_s; }
    lv_out = StringReplace(lp_s, lp_replace, lp_start, lp_end);
    if (lv_out == null) { return lp_s; }
    return lv_out;
}

string CMLib_StrReplaceWord(string lp_s, string lp_word, string lp_replace,
                            int lp_maxCount, bool lp_caseSens) {
    string lv_out;

    if (lp_s == "") { return ""; }
    if (lp_word == "") { return lp_s; }
    if (lp_maxCount == 0) { return lp_s; }
    lv_out = StringReplaceWord(lp_s, lp_word, lp_replace, lp_maxCount,
                               lp_caseSens);
    if (lv_out == null) { return lp_s; }
    return lv_out;
}

string CMLib_StrWord(string lp_s, int lp_index) {
    string lv_out;

    if (lp_s == "") { return ""; }
    // 1-based：StringWord("klaatu barada nikto", 2) == "barada"。
    if (lp_index < 1) { return ""; }
    lv_out = StringWord(lp_s, lp_index);
    if (lv_out == null) { return ""; }
    return lv_out;
}

datetime CMLib_StrToDateTime(string lp_s) {
    string lv_s;

    lv_s = lp_s;
    // 空串交给引擎解析属未定义行为；给一个确定的占位串，让返回值可预期。
    if (lv_s == "") { lv_s = "1/1/2000 00:00:00"; }
    return StringToDateTime(lv_s);
}
"""

# ---------------------------------------------------------------- panel ------
BLOCKS["cmlib_panel_h.galaxy"] = r"""

// =============================================================================
// CMLib :: Round26 —— 计时器窗口外观补齐
//
// panel 之前只有 Create / Show / Anchor / Destroy / Start 五件，够"显示一个
// 倒计时"，但不够做像样的关卡 HUD：换绑计时器、改版式、开进度条、调进度条
// 颜色、查可见性，全都得裸调 TimerWindow*。
//
// 统一守门：窗口 id == c_timerWindowNone(0) 一律空操作 / 返回 false，
// 跟已有的 CMLib_TimerPanelShow / Destroy 同口径。
//
// 版式常量：c_timerWindowStyleHorizontalTitleTime(0) / HorizontalTimeTitle(1)
//          / VerticalTitleTime(2) / VerticalTimeTitle(3)。
// =============================================================================

// 换绑窗口显示的计时器；timer 为 null 时空操作。
void CMLib_TimerPanelBind(int lp_window, timer lp_timer);
// 版式 + 是否显示已用时间；style 越界回落到 HorizontalTitleTime。
void CMLib_TimerPanelStyle(int lp_window, int lp_style, bool lp_showElapsed);
// 绝对位置 / 复位到默认锚点。
void CMLib_TimerPanelMove(int lp_window, int lp_x, int lp_y);
void CMLib_TimerPanelReset(int lp_window);
// 标题与时间之间的间距 / 固定行高；负值按 0。
void CMLib_TimerPanelGap(int lp_window, int lp_width);
void CMLib_TimerPanelHeight(int lp_window, int lp_height);
// 边框 / 进度条开关，以及进度条分段颜色（step 为分段序号，负值按 0）。
void CMLib_TimerPanelBorder(int lp_window, bool lp_show);
void CMLib_TimerPanelProgressBar(int lp_window, bool lp_show);
void CMLib_TimerPanelProgressColor(int lp_window, color lp_color, int lp_step);
// 该玩家眼里这个窗口是否可见。
bool CMLib_TimerPanelVisible(int lp_window, int lp_player);
"""

BLOCKS["cmlib_panel.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round26 —— 计时器窗口外观补齐
// -----------------------------------------------------------------------------

void CMLib_TimerPanelBind(int lp_window, timer lp_timer) {
    if (lp_window == c_timerWindowNone) { return; }
    if (lp_timer == null) { return; }
    TimerWindowSetTimer(lp_window, lp_timer);
}

void CMLib_TimerPanelStyle(int lp_window, int lp_style, bool lp_showElapsed) {
    int lv_style;

    if (lp_window == c_timerWindowNone) { return; }
    lv_style = lp_style;
    if (lv_style < c_timerWindowStyleHorizontalTitleTime) {
        lv_style = c_timerWindowStyleHorizontalTitleTime;
    }
    if (lv_style > c_timerWindowStyleVerticalTimeTitle) {
        lv_style = c_timerWindowStyleHorizontalTitleTime;
    }
    TimerWindowSetStyle(lp_window, lv_style, lp_showElapsed);
}

void CMLib_TimerPanelMove(int lp_window, int lp_x, int lp_y) {
    if (lp_window == c_timerWindowNone) { return; }
    TimerWindowSetPosition(lp_window, lp_x, lp_y);
}

void CMLib_TimerPanelReset(int lp_window) {
    if (lp_window == c_timerWindowNone) { return; }
    TimerWindowResetPosition(lp_window);
}

void CMLib_TimerPanelGap(int lp_window, int lp_width) {
    int lv_w;

    if (lp_window == c_timerWindowNone) { return; }
    lv_w = lp_width;
    if (lv_w < 0) { lv_w = 0; }
    TimerWindowSetGapWidth(lp_window, lv_w);
}

void CMLib_TimerPanelHeight(int lp_window, int lp_height) {
    int lv_h;

    if (lp_window == c_timerWindowNone) { return; }
    lv_h = lp_height;
    if (lv_h < 0) { lv_h = 0; }
    TimerWindowSetFixedHeight(lp_window, lv_h);
}

void CMLib_TimerPanelBorder(int lp_window, bool lp_show) {
    if (lp_window == c_timerWindowNone) { return; }
    TimerWindowShowBorder(lp_window, lp_show);
}

void CMLib_TimerPanelProgressBar(int lp_window, bool lp_show) {
    if (lp_window == c_timerWindowNone) { return; }
    TimerWindowShowProgressBar(lp_window, lp_show);
}

void CMLib_TimerPanelProgressColor(int lp_window, color lp_color, int lp_step) {
    int lv_step;

    if (lp_window == c_timerWindowNone) { return; }
    lv_step = lp_step;
    if (lv_step < 0) { lv_step = 0; }
    // color 是值类型，不能和 null 比较，这里只能信任调用方给了合法 Color()。
    TimerWindowSetProgressColor(lp_window, lp_color, lv_step);
}

bool CMLib_TimerPanelVisible(int lp_window, int lp_player) {
    if (lp_window == c_timerWindowNone) { return false; }
    return TimerWindowVisible(lp_window, lp_player);
}
"""

# ----------------------------------------------------------------- trig ------
BLOCKS["cmlib_trig_h.galaxy"] = r"""

// =============================================================================
// CMLib :: Round26 —— 最近一次启动的计时器
//
// 配合 CMLib_TimerOnce / CMLib_TimerLoop 用：这两个封装内部会 TimerStart，
// 所以调完立刻取 CMLib_TimerLastStarted() 就能拿回同一个句柄，适合"启动后
// 立刻挂窗口 / 挂事件"的写法，省一个中间变量。
// =============================================================================

timer CMLib_TimerLastStarted();
"""

BLOCKS["cmlib_trig.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round26 —— 最近一次启动的计时器
// -----------------------------------------------------------------------------

timer CMLib_TimerLastStarted() {
    return TimerLastStarted();
}
"""

# ----------------------------------------------------------------- conv ------
BLOCKS["cmlib_conv_h.galaxy"] = r"""

// =============================================================================
// CMLib :: Round26 —— 通讯（Transmission）补齐
//
// conv 域此前只封了「发一条通讯」这条主路径，剩下四个开关族全漏了：
//   · 源级开关（能不能暂停 / 能不能被串流录进去 / 要不要写进消息日志）
//   · 全局开关（发通讯时是否藏掉右上角警报面板）
//   · Select 变体（多一个 isSelect 参数的发送入口）
//
// ⚠ TransmissionSendForPlayerSelect 的返回类型：NativeLib.TriggerLib 的
//   ParamDef 标 `transmission`，但 natives_missing.galaxy:1596 的源码写的是
//   `native int`。以源码为准 —— 元数据只当"这个符号存在"的证据，不当签名。
//
// ⚠ isSelect 语义未经证实：翻遍 reference 下全部官方 .galaxy，57 处调用
//   **一律传 false**，true 分支零观测。这里如实透传、不替调用方兜底，
//   要用 true 请自己先做真机对照。（round25 教训：可调用 ≠ 语义可预测。）
// =============================================================================

// TransmissionSetOption 的选项索引。引擎只导出了这一个。
const int CMLIB_TRANS_OPT_HIDE_ALERT_PANEL = 1;

// 发一条通讯（Select 变体）。owningPlayer 传 c_maxPlayers 表示"不归属特定玩家"。
// players 传 null 会自动回落成 PlayerGroupActive()，和 CMLib_TransSayTimed 一致。
int  CMLib_TransSendForPlayerSelect(playergroup lp_players, transmissionsource lp_source,
                                    int lp_portrait, string lp_portraitActor,
                                    string lp_portraitAnim, soundlink lp_sound,
                                    text lp_speaker, text lp_subtitle,
                                    fixed lp_duration, int lp_durationType,
                                    bool lp_waitUntilDone, int lp_owningPlayer,
                                    bool lp_isSelect);

// 全局通讯选项开关。用 CMLIB_TRANS_OPT_* 常量。
void CMLib_TransSetOption(int lp_option, bool lp_value);
// 便捷式：发通讯时藏掉右上角警报面板（过场里最常用的一个）。
void CMLib_TransHideAlertPanel(bool lp_hide);

// 源级开关。source 是值类型（transmissionsource），不能判 null，
// 传 TransmissionSource() 造出来的空源也是合法调用，引擎自己吞掉。
void CMLib_TransSourceBypassLog(transmissionsource lp_source, bool lp_bypass);
void CMLib_TransSourcePauseAllowed(transmissionsource lp_source, bool lp_allowed);
void CMLib_TransSourceStreaming(transmissionsource lp_source, bool lp_allowed);
"""

BLOCKS["cmlib_conv.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round26 —— 通讯（Transmission）补齐
// -----------------------------------------------------------------------------

int CMLib_TransSendForPlayerSelect(playergroup lp_players, transmissionsource lp_source,
                                   int lp_portrait, string lp_portraitActor,
                                   string lp_portraitAnim, soundlink lp_sound,
                                   text lp_speaker, text lp_subtitle,
                                   fixed lp_duration, int lp_durationType,
                                   bool lp_waitUntilDone, int lp_owningPlayer,
                                   bool lp_isSelect) {
    playergroup lv_to;
    int lv_owner;
    string lv_actor;
    string lv_anim;

    lv_to = lp_players;
    if (lv_to == null) {
        lv_to = PlayerGroupActive();
    }
    lv_owner = lp_owningPlayer;
    if (lv_owner < 0 || lv_owner > c_maxPlayers) {
        lv_owner = c_maxPlayers;
    }
    // 官方用例里这两个串常传 ""，null 串在 Galaxy 里等价于空串，统一成 "" 更保险。
    lv_actor = lp_portraitActor;
    if (lv_actor == null) { lv_actor = ""; }
    lv_anim = lp_portraitAnim;
    if (lv_anim == null) { lv_anim = ""; }

    return TransmissionSendForPlayerSelect(lv_to, lp_source, lp_portrait,
                                           lv_actor, lv_anim, lp_sound,
                                           lp_speaker, lp_subtitle,
                                           lp_duration, lp_durationType,
                                           lp_waitUntilDone, lv_owner,
                                           lp_isSelect);
}

void CMLib_TransSetOption(int lp_option, bool lp_value) {
    if (lp_option < 0) { return; }
    TransmissionSetOption(lp_option, lp_value);
}

void CMLib_TransHideAlertPanel(bool lp_hide) {
    TransmissionSetOption(CMLIB_TRANS_OPT_HIDE_ALERT_PANEL, lp_hide);
}

void CMLib_TransSourceBypassLog(transmissionsource lp_source, bool lp_bypass) {
    TransmissionSourceSetBypassMessageLog(lp_source, lp_bypass);
}

void CMLib_TransSourcePauseAllowed(transmissionsource lp_source, bool lp_allowed) {
    TransmissionSourceSetPauseAllowed(lp_source, lp_allowed);
}

void CMLib_TransSourceStreaming(transmissionsource lp_source, bool lp_allowed) {
    TransmissionSourceSetStreamingAllowed(lp_source, lp_allowed);
}
"""

# ---------------------------------------------------------------- board ------
BLOCKS["cmlib_board_h.galaxy"] = r"""

// =============================================================================
// CMLib :: Round26 —— 结算面板自定义统计项
//
// 和 leaderboard 不是一回事：这两个写的是**游戏结束后**弹出的胜利/失败结算
// 面板上那一行自定义统计（比如"击杀数 / 42"）。text 是本地化文本，
// 走 StringToText / StringExternal，别硬编码中文串。
//
// 引擎只给了 Text + Value 两个 setter，没有 getter、没有清除接口 ——
// 想"清掉"就传 StringToText("")。
// =============================================================================

// 统计项名称（左侧标签）。
void CMLib_VPanelCustomStatisticText(text lp_text);
// 统计项数值（右侧内容）。引擎签名就是 text，不是数字 —— 自己格式化好再传。
void CMLib_VPanelCustomStatisticValue(text lp_text);
// 便捷式：一次把标签 + 整数值写完，省掉调用方手搓 IntToText。
void CMLib_VPanelCustomStatisticInt(text lp_label, int lp_value);
"""

BLOCKS["cmlib_board.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round26 —— 结算面板自定义统计项
// -----------------------------------------------------------------------------

void CMLib_VPanelCustomStatisticText(text lp_text) {
    VictoryPanelSetCustomStatisticText(lp_text);
}

void CMLib_VPanelCustomStatisticValue(text lp_text) {
    VictoryPanelSetCustomStatisticValue(lp_text);
}

void CMLib_VPanelCustomStatisticInt(text lp_label, int lp_value) {
    VictoryPanelSetCustomStatisticText(lp_label);
    VictoryPanelSetCustomStatisticValue(IntToText(lp_value));
}
"""


# =============================================================================
# 落盘：幂等追加
# =============================================================================

def main() -> int:
    if not CM.is_dir():
        print("[FAIL] 找不到 cmlib 目录: %s" % CM)
        return 2

    written = 0
    skipped = 0
    missing = 0

    for name in sorted(BLOCKS):
        path = CM / name
        if not path.is_file():
            print("[FAIL] 缺文件: %s" % name)
            missing += 1
            continue
        cur = path.read_text(encoding="utf-8")
        if MARK in cur:
            print("[skip] %-24s 已有 %s 标记" % (name, MARK))
            skipped += 1
            continue
        body = BLOCKS[name]
        if not cur.endswith("\n"):
            cur += "\n"
        path.write_text(cur + body, encoding="utf-8")
        print("[ok]   %-24s +%d 字节" % (name, len(body.encode("utf-8"))))
        written += 1

    print("-" * 60)
    print("written=%d skipped=%d missing=%d" % (written, skipped, missing))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
