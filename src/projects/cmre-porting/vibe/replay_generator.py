"""把亡者之夜回放 JSONL 日志转成自包含 HTML 报告。

输入：run_dead_of_night.py 生成的 .jsonl 文件
输出：单文件 HTML（含曲线图、关键事件表、终局 SVG 顶视图、摘要卡片）

用法：
    python -m vibe.replay_generator <replay.jsonl> [--output report.html]
    python -m vibe.replay_generator --latest      # 转换最新的回放日志
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Optional


# 颜色常量（与玩家颜色一致）
PLAYER_COLORS = {
    1: "#4a90e2",   # 蓝（玩家）
    2: "#e24a4a",   # 红
    3: "#4ae24a",   # 绿
    4: "#e2c84a",   # 黄（Amon）
    5: "#c84ae2",   # 紫
    0: "#888888",   # 中立
}


def load_replay(jsonl_path: Path) -> list[dict]:
    """加载 JSONL 回放日志，返回帧列表。"""
    frames: list[dict] = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            frames.append(json.loads(line))
    return frames


def _esc(s) -> str:
    return html.escape(str(s))


def render_summary_card(frames: list[dict]) -> str:
    """摘要卡片：终局状态。"""
    if not frames:
        return "<p>无回放数据</p>"
    last = frames[-1]
    first = frames[0]

    # 判定胜负：最后一帧 P1 > 0 即存活
    verdict = "VICTORY" if last["p1_alive"] > 0 else "DEFEAT"
    verdict_color = "#4ae24a" if verdict == "VICTORY" else "#e24a4a"

    # 总时长（实际游戏秒）
    duration_sec = last.get("real_sec", last["loop"] / 22.4)
    minutes = int(duration_sec // 60)
    seconds = duration_sec - minutes * 60

    # 总死亡数（从 key_events 统计）
    total_deaths = sum(1 for f in frames for e in f.get("key_events", []) if e.get("kind") == "death")
    p1_deaths = sum(1 for f in frames for e in f.get("key_events", [])
                    if e.get("kind") == "death" and e.get("owner") == 1)
    enemy_deaths = total_deaths - p1_deaths

    # 波次总数
    waves = sum(1 for f in frames for e in f.get("key_events", []) if e.get("kind") == "wave_fired")

    # 初始 / 终局单位数
    p1_initial = first["p1_alive"]
    p1_final = last["p1_alive"]
    enemy_initial = first["enemy_alive"]
    enemy_final = last["enemy_alive"]

    return f"""
    <div class="summary-card" style="background:#1e1e1e;padding:20px;border-radius:8px;margin-bottom:20px;border-left:6px solid {verdict_color};">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
        <h2 style="margin:0;color:#fff;">亡者之夜 AI 盟友对局</h2>
        <div style="font-size:28px;font-weight:bold;color:{verdict_color};">{verdict}</div>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;">
        <div class="stat"><div class="stat-label">游戏时长</div><div class="stat-value">{minutes}分{seconds:.0f}秒</div></div>
        <div class="stat"><div class="stat-label">总 Loop</div><div class="stat-value">{last['loop']}</div></div>
        <div class="stat"><div class="stat-label">存活夜晚</div><div class="stat-value">{last['current_night']} / 6</div></div>
        <div class="stat"><div class="stat-label">波次触发</div><div class="stat-value">{waves}</div></div>
        <div class="stat"><div class="stat-label">命令执行</div><div class="stat-value">{last['total_cmds']}</div></div>
        <div class="stat"><div class="stat-label">P1 初始→终局</div><div class="stat-value">{p1_initial} → {p1_final}</div></div>
        <div class="stat"><div class="stat-label">敌方 初始→终局</div><div class="stat-value">{enemy_initial} → {enemy_final}</div></div>
        <div class="stat"><div class="stat-label">总死亡</div><div class="stat-value">{total_deaths} (P1:{p1_deaths} 敌:{enemy_deaths})</div></div>
      </div>
    </div>
    """


def render_unit_count_chart(frames: list[dict]) -> str:
    """单位数量随时间变化曲线图（SVG）。"""
    if not frames:
        return "<p>无数据</p>"

    width = 1200
    height = 400
    padding = 60
    chart_w = width - 2 * padding
    chart_h = height - 2 * padding

    loops = [f["loop"] for f in frames]
    p1_counts = [f["p1_alive"] for f in frames]
    enemy_counts = [f["enemy_alive"] for f in frames]

    max_count = max(max(p1_counts), max(enemy_counts), 10)
    max_loop = max(loops)

    def to_x(loop: int) -> float:
        return padding + (loop / max_loop) * chart_w if max_loop > 0 else padding

    def to_y(count: int) -> float:
        return padding + chart_h - (count / max_count) * chart_h

    # 标记每个夜晚的起止（背景色带）
    night_bands = []
    prev_night = 0
    for i, f in enumerate(frames):
        n = f["current_night"]
        if n != prev_night:
            if prev_night > 0 and i > 0:
                # 上一夜结束
                night_bands.append((prev_night, night_bands[-1][1] if night_bands else 0, frames[i-1]["loop"]))
            if n > 0:
                night_bands.append((n, f["loop"], f["loop"]))
            prev_night = n
    # 收尾
    if prev_night > 0 and night_bands:
        night_bands[-1] = (night_bands[-1][0], night_bands[-1][1], loops[-1])

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">']
    parts.append(f'<rect width="{width}" height="{height}" fill="#1a1a1a"/>')

    # 夜晚背景色带（深紫色调）
    for n, start, end in night_bands:
        x1 = to_x(start)
        x2 = to_x(end)
        opacity = 0.15 + 0.05 * n
        parts.append(f'<rect x="{x1:.1f}" y="{padding}" width="{x2-x1:.1f}" height="{chart_h}" fill="#6a4ae2" opacity="{opacity}"/>')
        # 标签
        mid_x = (x1 + x2) / 2
        parts.append(f'<text x="{mid_x:.1f}" y="{padding-8}" fill="#b8a8ff" font-size="11" text-anchor="middle">Night {n}</text>')

    # 网格 + Y 轴
    for i in range(0, max_count + 1, max(1, max_count // 8)):
        y = to_y(i)
        parts.append(f'<line x1="{padding}" y1="{y:.1f}" x2="{width-padding}" y2="{y:.1f}" stroke="#333" stroke-width="0.5"/>')
        parts.append(f'<text x="{padding-8}" y="{y+4:.1f}" fill="#aaa" font-size="10" text-anchor="end">{i}</text>')

    # X 轴标签
    x_ticks = 10
    for i in range(x_ticks + 1):
        loop = int(i * max_loop / x_ticks)
        x = to_x(loop)
        parts.append(f'<line x1="{x:.1f}" y1="{height-padding}" x2="{x:.1f}" y2="{height-padding+4}" stroke="#666"/>')
        parts.append(f'<text x="{x:.1f}" y="{height-padding+18}" fill="#aaa" font-size="10" text-anchor="middle">{loop}</text>')
    parts.append(f'<text x="{width/2}" y="{height-10}" fill="#aaa" font-size="12" text-anchor="middle">Loop</text>')
    parts.append(f'<text x="20" y="{height/2}" fill="#aaa" font-size="12" text-anchor="middle" transform="rotate(-90 20 {height/2})">单位数量</text>')

    # P1 曲线（蓝）
    path_p1 = " ".join(f"L{to_x(l):.1f},{to_y(c):.1f}" for l, c in zip(loops, p1_counts))
    parts.append(f'<path d="M{to_x(loops[0]):.1f},{to_y(p1_counts[0]):.1f} {path_p1[1:]}" fill="none" stroke="{PLAYER_COLORS[1]}" stroke-width="2"/>')
    # 敌方曲线（红）
    path_enemy = " ".join(f"L{to_x(l):.1f},{to_y(c):.1f}" for l, c in zip(loops, enemy_counts))
    parts.append(f'<path d="M{to_x(loops[0]):.1f},{to_y(enemy_counts[0]):.1f} {path_enemy[1:]}" fill="none" stroke="{PLAYER_COLORS[2]}" stroke-width="2"/>')

    # 图例
    parts.append(f'<rect x="{width-padding-180}" y="10" width="170" height="44" fill="#000" opacity="0.5" rx="4"/>')
    parts.append(f'<line x1="{width-padding-170}" y1="22" x2="{width-padding-145}" y2="22" stroke="{PLAYER_COLORS[1]}" stroke-width="2"/>')
    parts.append(f'<text x="{width-padding-138}" y="26" fill="#fff" font-size="12">Player 1 (AI 盟友)</text>')
    parts.append(f'<line x1="{width-padding-170}" y1="42" x2="{width-padding-145}" y2="42" stroke="{PLAYER_COLORS[2]}" stroke-width="2"/>')
    parts.append(f'<text x="{width-padding-138}" y="46" fill="#fff" font-size="12">Enemy (Amon)</text>')

    parts.append("</svg>")
    return "\n".join(parts)


def render_unit_type_breakdown(frames: list[dict]) -> str:
    """单位类型分布表（终局）。"""
    if not frames:
        return "<p>无数据</p>"
    last = frames[-1]
    p1_types = last.get("p1_units_by_type", {})
    enemy_types = last.get("enemy_units_by_type", {})

    rows = []
    rows.append("""
    <table class="type-table">
      <thead><tr><th>玩家阵营（终局）</th><th>数量</th></tr></thead>
      <tbody>
    """)
    for t, c in sorted(p1_types.items(), key=lambda x: -x[1]):
        rows.append(f'<tr><td><span class="unit-dot" style="background:{PLAYER_COLORS[1]}"></span>{_esc(t)}</td><td>{c}</td></tr>')
    if not p1_types:
        rows.append('<tr><td colspan="2" style="color:#888">无存活单位</td></tr>')
    rows.append("</tbody></table>")

    rows.append("""
    <table class="type-table">
      <thead><tr><th>敌方阵营（终局）</th><th>数量</th></tr></thead>
      <tbody>
    """)
    for t, c in sorted(enemy_types.items(), key=lambda x: -x[1]):
        rows.append(f'<tr><td><span class="unit-dot" style="background:{PLAYER_COLORS[2]}"></span>{_esc(t)}</td><td>{c}</td></tr>')
    if not enemy_types:
        rows.append('<tr><td colspan="2" style="color:#888">无存活单位</td></tr>')
    rows.append("</tbody></table>")
    return "\n".join(rows)


def render_key_events_table(frames: list[dict]) -> str:
    """关键事件表（波次 + 死亡）。

    由于每帧的 key_events 只含本帧新事件（已在 runner 端去重），
    直接合并所有帧的事件即可，无需再次去重。
    """
    events: list[dict] = []
    for f in frames:
        events.extend(f.get("key_events", []))

    # 按 loop 排序
    events.sort(key=lambda e: e.get("loop", 0))

    # 限制输出数量（避免 HTML 过大）
    if len(events) > 200:
        events = events[:100] + [{"loop": -1, "kind": "ellipsis", "text": f"... 省略 {len(events) - 200} 条 ..."}] + events[-100:]

    rows = ['<table class="events-table"><thead><tr><th>Loop</th><th>时间</th><th>类型</th><th>详情</th></tr></thead><tbody>']
    for e in events:
        loop = e.get("loop", 0)
        ts = e.get("ts_sec", 0)
        kind = e.get("kind", "")
        if kind == "ellipsis":
            rows.append(f'<tr><td colspan="4" style="text-align:center;color:#888;padding:8px;">{_esc(e.get("text",""))}</td></tr>')
            continue
        if kind == "wave_fired":
            detail = f'波次 <code>{_esc(e.get("wave_name",""))}</code> 触发，刷出 {e.get("unit_count",0)} 单位'
            kind_badge = f'<span class="badge badge-wave">WAVE</span>'
        elif kind == "death":
            owner = e.get("owner", -1)
            color = PLAYER_COLORS.get(owner, "#888") if owner >= 0 else "#888"
            unit_t = e.get("unit_type", "?")
            detail = f'<span class="unit-dot" style="background:{color}"></span>P{owner} <code>{_esc(unit_t)}</code> (id={e.get("entity_id",0)}) 阵亡'
            kind_badge = '<span class="badge badge-death">DEATH</span>'
        else:
            detail = _esc(json.dumps(e, ensure_ascii=False))
            kind_badge = f'<span class="badge">{_esc(kind)}</span>'
        rows.append(f'<tr><td>{loop}</td><td>{ts:.1f}s</td><td>{kind_badge}</td><td>{detail}</td></tr>')
    rows.append("</tbody></table>")
    return "\n".join(rows)


def render_final_snapshot_svg(frames: list[dict]) -> str:
    """终局 SVG 顶视图。"""
    if not frames:
        return "<p>无数据</p>"
    last = frames[-1]
    entities_by_player = last.get("entities_by_player", {})

    # 收集所有实体并计算包围盒
    all_entities = []
    for pid_str, ents in entities_by_player.items():
        pid = int(pid_str)
        for e in ents:
            all_entities.append((pid, e))
    if not all_entities:
        return "<p>终局无存活单位</p>"

    xs = [e["x"] for _, e in all_entities]
    ys = [e["y"] for _, e in all_entities]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    # 加 padding
    pad = max(5.0, (max_x - min_x) * 0.05)
    min_x -= pad; max_x += pad
    min_y -= pad; max_y += pad

    width = 1200
    height = 800
    sx = width / (max_x - min_x) if max_x > min_x else 1
    sy = height / (max_y - min_y) if max_y > min_y else 1
    s = min(sx, sy)

    def to_svg_x(x: float) -> float:
        return (x - min_x) * s

    def to_svg_y(y: float) -> float:
        # Y 翻转：游戏北 → 屏幕上
        return height - (y - min_y) * s

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">']
    parts.append(f'<rect width="{width}" height="{height}" fill="#0a0a0a"/>')

    # 网格
    grid_step = 10
    grid_pixels = grid_step * s
    if grid_pixels > 20:
        for gx in range(0, width, int(grid_pixels)):
            parts.append(f'<line x1="{gx}" y1="0" x2="{gx}" y2="{height}" stroke="#1a1a1a" stroke-width="0.5"/>')
        for gy in range(0, height, int(grid_pixels)):
            parts.append(f'<line x1="0" y1="{gy}" x2="{width}" y2="{gy}" stroke="#1a1a1a" stroke-width="0.5"/>')

    # 实体
    for pid, e in all_entities:
        ex = to_svg_x(e["x"])
        ey = to_svg_y(e["y"])
        color = PLAYER_COLORS.get(pid, "#888")
        radius = 6 if pid == 1 else 4
        parts.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="{radius}" fill="{color}" opacity="0.85"/>')

    # 图例
    legend_x = 20
    legend_y = 20
    parts.append(f'<rect x="{legend_x-10}" y="{legend_y-15}" width="180" height="{30 + 25 * len(PLAYER_COLORS)}" fill="#000" opacity="0.7" rx="4"/>')
    parts.append(f'<text x="{legend_x}" y="{legend_y}" fill="#fff" font-size="13" font-weight="bold">终局单位分布</text>')
    for i, (pid, color) in enumerate(sorted(PLAYER_COLORS.items())):
        count = len(entities_by_player.get(str(pid), []))
        if count == 0:
            continue
        y = legend_y + 20 + i * 20
        parts.append(f'<circle cx="{legend_x+8}" cy="{y}" r="5" fill="{color}"/>')
        parts.append(f'<text x="{legend_x+20}" y="{y+4}" fill="#fff" font-size="12">Player {pid}: {count} 单位</text>')

    parts.append(f'<text x="{width-10}" y="20" fill="#aaa" font-size="12" text-anchor="end">Loop {last["loop"]} | 总计 {len(all_entities)} 单位</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def render_html_report(frames: list[dict], jsonl_path: Path, output_path: Path) -> None:
    """生成自包含 HTML 报告。"""
    summary = render_summary_card(frames)
    chart = render_unit_count_chart(frames)
    breakdown = render_unit_type_breakdown(frames)
    events_table = render_key_events_table(frames)
    snapshot_svg = render_final_snapshot_svg(frames)

    css = """
    <style>
      body { background: #141414; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 24px; }
      h1 { color: #fff; border-bottom: 2px solid #333; padding-bottom: 8px; }
      h2 { color: #fff; margin-top: 32px; border-bottom: 1px solid #333; padding-bottom: 6px; }
      .stat { background: #2a2a2a; padding: 10px 14px; border-radius: 6px; }
      .stat-label { color: #aaa; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
      .stat-value { color: #fff; font-size: 18px; font-weight: bold; margin-top: 4px; }
      table { border-collapse: collapse; width: 100%; margin: 12px 0; background: #1a1a1a; }
      th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid #2a2a2a; }
      th { background: #2a2a2a; color: #aaa; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
      td { color: #ddd; font-size: 13px; }
      tr:hover { background: #222; }
      .type-table { display: inline-block; vertical-align: top; width: 48%; margin-right: 2%; }
      .unit-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }
      .badge { padding: 2px 8px; border-radius: 3px; font-size: 11px; font-weight: bold; background: #444; color: #fff; }
      .badge-wave { background: #6a4ae2; }
      .badge-death { background: #c44; }
      code { background: #2a2a2a; padding: 1px 6px; border-radius: 3px; color: #ffd180; font-family: "Consolas", monospace; }
      .meta { color: #888; font-size: 12px; margin-top: 24px; padding: 12px; background: #1a1a1a; border-radius: 4px; }
      svg { max-width: 100%; height: auto; border: 1px solid #333; border-radius: 4px; }
    </style>
    """

    html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>亡者之夜 AI 盟友对局回放</title>
  {css}
</head>
<body>
  <h1>亡者之夜 AI 盟友对局回放报告</h1>

  {summary}

  <h2>单位数量随时间变化</h2>
  <p style="color:#888;font-size:13px;">紫色背景带表示夜晚（敌方进攻期）；曲线展示双方存活单位数。</p>
  {chart}

  <h2>终局单位分布（顶视图）</h2>
  <p style="color:#888;font-size:13px;">每个圆点代表一个存活单位，颜色对应玩家阵营。</p>
  {snapshot_svg}

  <h2>终局单位类型分布</h2>
  {breakdown}

  <h2>关键事件时间线</h2>
  <p style="color:#888;font-size:13px;">按 loop 排序的波次触发和单位阵亡事件。</p>
  {events_table}

  <div class="meta">
    <strong>回放日志路径：</strong> {_esc(jsonl_path)}<br>
    <strong>总帧数：</strong> {len(frames)}<br>
    <strong>报告生成：</strong> {Path(__file__).name}
  </div>
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_doc, encoding="utf-8")


def find_latest_replay() -> Optional[Path]:
    """在 artifacts/ 目录找最新的 dead_of_night_replay_*.jsonl。"""
    artifacts = Path(__file__).resolve().parents[1] / "artifacts"
    if not artifacts.exists():
        return None
    replays = sorted(artifacts.glob("dead_of_night_replay_*.jsonl"))
    return replays[-1] if replays else None


def main():
    parser = argparse.ArgumentParser(description="把亡者之夜 JSONL 回放日志转成 HTML 报告")
    parser.add_argument("jsonl", type=str, nargs="?", default=None,
                        help="回放日志 JSONL 路径；省略时与 --latest 配合使用")
    parser.add_argument("--latest", action="store_true",
                        help="转换最新的回放日志")
    parser.add_argument("--output", type=str, default=None,
                        help="HTML 输出路径；默认与 JSONL 同名 .html")
    args = parser.parse_args()

    if args.latest:
        p = find_latest_replay()
        if p is None:
            print("错误：未找到任何 dead_of_night_replay_*.jsonl", file=sys.stderr)
            return 1
        jsonl_path = p
    elif args.jsonl:
        jsonl_path = Path(args.jsonl)
    else:
        parser.error("需要提供 JSONL 路径或使用 --latest")
        return 1

    if not jsonl_path.exists():
        print(f"错误：文件不存在: {jsonl_path}", file=sys.stderr)
        return 1

    output_path = Path(args.output) if args.output else jsonl_path.with_suffix(".html")

    frames = load_replay(jsonl_path)
    if not frames:
        print("错误：JSONL 为空", file=sys.stderr)
        return 1

    render_html_report(frames, jsonl_path, output_path)
    print(f"HTML 报告已生成: {output_path}")
    print(f"  帧数: {len(frames)}")
    print(f"  Loop 范围: {frames[0]['loop']} → {frames[-1]['loop']}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
