# -*- coding: utf-8 -*-
"""从 `_h.galaxy` 声明自动生成 `scripts/cmlib/API_INDEX.md`（完整 API 索引）。

为什么需要它：
    README §2 是**精选速查**——按使用场景分组、带设计意图和踩坑说明，
    天然不可能覆盖全部一千多个函数；而"漏记的 API 等于不存在"，
    没人会去翻 `_h.galaxy` 找函数。
    两者分工：README 讲「为什么这么用」，本索引保证「一个都不漏」。

由 `_h` 声明单一来源生成，因此**永远不会与实现漂移**。
每轮扩库后重跑一次即可（`check_cmlib.py` 之后、提交之前）。
"""
import re
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent / "scripts" / "cmlib"
OUT = BASE / "API_INDEX.md"

# 模块顺序与 README §1 目录树保持一致，便于对照
ORDER = ["core", "ui", "unit", "catalog", "player", "ai", "fx", "panel", "bank",
         "geo", "text", "trig", "game", "conv", "udata", "stock", "board",
         "buff", "path", "env", "stat"]

DESC = {
    "core": "数值 / 字符串 / 键名 / 日志 / DataTable 存储",
    "ui": "Dialog 控件挂钩 / 创建 / 属性 / 列表 / 事件 / HUD",
    "unit": "unitfilter / 单位查询 / 生成 / 行为·武器 / 命令 / 清理",
    "catalog": "Catalog 运行时读写（单位/武器/效果/行为/技能/按钮）",
    "player": "玩家判定 / 遍历 / PlayerGroup / 资源 / 联盟 / 科技",
    "ai": "AI 波次编排 / 难度 / 脚本控制",
    "fx": "音效 / 音乐 / 镜头 / 淡入淡出 / Ping / 飘字 / Actor",
    "panel": "Dialog 容器 / 计时器窗口 / 任务目标",
    "bank": "Bank 存档（fallback / 脏标记批量落盘 / 版本 / 枚举）",
    "geo": "几何 / 寻路 / 单位自定义值 / 行为查询",
    "text": "本地化文本 / 数值格式化 / 颜色文本 / 单位名",
    "trig": "触发器编排 / 事件挂载 / 等待与计时 / 事件取参",
    "game": "游戏状态 / 胜负 / 视野迷雾 / 揭示器 / 蔓延 / 时间",
    "conv": "过场对白（Transmission / Conversation）",
    "udata": "数据编辑器 User Data 表读写",
    "stock": "电脑 AI 库存 / 科技树 / AI 用户变量",
    "board": "排行榜面板（Board）/ 任务结算面板（VictoryPanel）",
    "buff": "Behavior 增益减益 / 单位状态开关 / 玩家状态开关",
    "path": "地形寻路查询 / 路线（Route）可视化编排",
    "env": "装饰物 Doodad / 地形贴图 / 水面 / 战争迷雾外观",
    "stat": "成就 / 分数 / 难度名 / 效果历史 / 战役模式 / 时间戳",
}

# 声明形如 `bool CMLib_UnitOk(unit lp_unit);`，**参数可能跨多行**——
# 只按单行匹配会漏掉 61 个（实测 992 vs 1053），索引一旦有漏就失去意义。
# 所以先剥掉行注释再整体扫，参数里允许换行。
SIG = re.compile(r"\b([A-Za-z_][A-Za-z0-9_<>]*)\s+(CMLib_[A-Za-z0-9_]+)\s*\("
                 r"([^)]*)\)", re.S)
LINE_COMMENT = re.compile(r"//[^\n]*")


def short_params(raw):
    """把 `unit lp_unit, string lp_behavior` 压成 `unit, string`，索引更好读。"""
    raw = raw.strip()
    if not raw:
        return ""
    out = []
    for part in raw.split(","):
        toks = part.strip().split()
        out.append(toks[0] if toks else part.strip())
    return ", ".join(out)


def collect(mod):
    h = BASE / ("cmlib_%s_h.galaxy" % mod)
    if not h.exists():
        return []
    txt = LINE_COMMENT.sub("", h.read_text(encoding="utf-8"))
    rows, seen = [], set()
    for m in SIG.finditer(txt):
        ret, name, params = m.group(1), m.group(2), m.group(3)
        # `typedef funcref<X> Y;` 不带括号不会命中；这里只挡控制流误匹配
        if ret in ("return", "if", "while", "for", "else", "typedef"):
            continue
        if name in seen:
            continue
        seen.add(name)
        rows.append((name, ret, short_params(params)))
    return rows


def main():
    total = 0
    lines = [
        "# CMLib — 完整 API 索引（自动生成，勿手改）",
        "",
        "> 由 `gen_api_index.py` 从各模块 `_h.galaxy` 声明生成，"
        "**单一来源、不会与实现漂移**。",
        "> 每轮扩库后重跑：`python gen_api_index.py`。",
        ">",
        "> 这里保证**一个函数都不漏**；至于「为什么这么设计、踩过什么坑」，"
        "看 [`README.md`](README.md) §2 精选速查。",
        "",
        "| 生成时间 | 模块数 | 函数总数 |",
        "|---|---|---|",
        "| %s | %d | __TOTAL__ |" % (
            datetime.now().strftime("%Y-%m-%d %H:%M"), len(ORDER)),
        "",
        "---",
        "",
    ]
    toc = ["## 目录", ""]
    body = []
    for mod in ORDER:
        rows = collect(mod)
        total += len(rows)
        toc.append("- [`cmlib_%s`](#cmlib_%s) — %s（%d）"
                   % (mod, mod, DESC.get(mod, ""), len(rows)))
        body += ["", "## cmlib_%s" % mod, "", "> %s" % DESC.get(mod, ""), "",
                 "| 返回 | 函数 | 参数 |", "|---|---|---|"]
        for name, ret, params in rows:
            body.append("| `%s` | **`%s`** | `%s` |"
                        % (ret, name, params or "—"))
    toc.append("")
    out = "\n".join(lines + toc + body) + "\n"
    out = out.replace("__TOTAL__", str(total))
    OUT.write_text(out, encoding="utf-8")
    print("[api-index] %s  %d 模块 / %d 函数" % (OUT.name, len(ORDER), total))


main()
