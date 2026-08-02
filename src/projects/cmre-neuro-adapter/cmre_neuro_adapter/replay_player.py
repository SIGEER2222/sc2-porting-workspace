"""Generate a browser replay player for adapter-aware simulator replays."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable


def load_records(path: Path) -> list[dict[str, Any]]:
    """Load newline-delimited replay records."""

    records: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError("replay records must be objects")
            records.append(record)
    if not records:
        raise ValueError("replay contains no records")
    return records


def render_player_html(records: Iterable[dict[str, Any]], output_path: Path) -> None:
    """Render a self-contained HTML player with embedded replay data."""

    data = list(records)
    if not data:
        raise ValueError("replay contains no records")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # Keep embedded data from terminating the script element if future payloads
    # contain HTML-like text in a context or action description.
    payload = payload.replace("<", "\\u003c")
    html = _PLAYER_TEMPLATE.replace("__REPLAY_DATA__", payload)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replay", type=Path, help="adapter-aware replay JSONL")
    parser.add_argument("--output", type=Path, required=True, help="HTML output path")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    render_player_html(load_records(args.replay), args.output)
    print(args.output)
    return 0


_PLAYER_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CMRE Neuro 基础命令回放</title>
<style>
:root { color-scheme: dark; --bg: #0b1117; --panel: #111b24; --line: #263746; --muted: #8293a4; --text: #e8eef3; --blue: #4aa3ff; --green: #57d18c; --orange: #f2b45f; --red: #e36c6c; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 13px/1.4 "Segoe UI", "Microsoft YaHei", sans-serif; }
button, input { font: inherit; }
button { border: 1px solid var(--line); background: #172431; color: var(--text); border-radius: 4px; min-height: 30px; padding: 0 10px; cursor: pointer; }
button:hover, button.active { background: #21435d; border-color: var(--blue); }
.shell { max-width: 1500px; margin: 0 auto; padding: 14px; }
.topbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.title { display: flex; align-items: baseline; gap: 10px; }
h1 { margin: 0; font-size: 18px; letter-spacing: .2px; }
.badge { color: var(--green); border: 1px solid #2d6548; padding: 3px 8px; border-radius: 3px; font: 11px Consolas, monospace; }
.layout { display: grid; grid-template-columns: minmax(0, 1fr) 330px; gap: 12px; }
.map-panel, .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 5px; }
.map-panel { padding: 10px; }
.map-wrap { position: relative; background: #0d171d; border: 1px solid #29404f; border-radius: 3px; overflow: hidden; }
canvas { display: block; width: 100%; height: auto; aspect-ratio: 16 / 10; cursor: crosshair; }
.map-hud { position: absolute; left: 10px; top: 10px; padding: 5px 8px; background: rgba(6, 12, 17, .84); border: 1px solid #355064; color: #cbd7df; font: 11px Consolas, monospace; pointer-events: none; }
.tooltip { position: absolute; display: none; z-index: 2; pointer-events: none; padding: 6px 8px; background: #071016; border: 1px solid #52758c; border-radius: 3px; font: 11px/1.5 Consolas, monospace; white-space: nowrap; }
.controls { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 9px; }
.controls .spacer { width: 8px; }
.speed-label { color: var(--muted); margin-left: 4px; }
.timeline { margin-top: 10px; }
.timeline input { width: 100%; accent-color: var(--blue); cursor: pointer; }
.time-row { display: flex; justify-content: space-between; color: var(--muted); font: 11px Consolas, monospace; }
.marker-strip { position: relative; height: 20px; margin-top: 2px; border-top: 1px solid #1e303d; }
.marker { position: absolute; top: 0; width: 2px; height: 8px; background: var(--orange); cursor: pointer; }
.marker.action { height: 13px; background: var(--blue); }
.marker:hover { background: #fff; }
.side { display: flex; flex-direction: column; gap: 10px; }
.panel { padding: 10px 12px; }
.panel h2 { margin: 0 0 8px; color: var(--muted); font-size: 11px; font-weight: 600; letter-spacing: .7px; text-transform: uppercase; }
.stats { display: grid; grid-template-columns: 1fr 1fr; gap: 5px 14px; }
.stat { display: flex; justify-content: space-between; gap: 8px; }
.stat span:first-child { color: var(--muted); }
.stat strong { color: #fff; font: 12px Consolas, monospace; }
.units { display: grid; grid-template-columns: 1fr 1fr; gap: 5px 10px; }
.unit-row { display: flex; justify-content: space-between; border-bottom: 1px solid #1d2b36; padding-bottom: 3px; }
.unit-row span:last-child { color: var(--blue); font: 12px Consolas, monospace; }
.events, .actions { max-height: 190px; overflow: auto; }
.event, .action { border-left: 2px solid var(--line); padding: 4px 7px; margin: 4px 0; background: #0e1720; font-size: 11px; }
.event { border-left-color: var(--orange); }
.action { border-left-color: var(--blue); cursor: pointer; }
.action.current { background: #17324a; }
.event .meta, .action .meta { color: var(--muted); font: 10px Consolas, monospace; }
.action .ok { color: var(--green); }
.action .name { color: #dcecff; font-weight: 600; }
.footer { color: var(--muted); font: 10px Consolas, monospace; margin-top: 10px; }
@media (max-width: 900px) { .layout { grid-template-columns: 1fr; } .side { display: grid; grid-template-columns: 1fr 1fr; } .side .panel:first-child, .side .panel:last-child { grid-column: 1 / -1; } }
@media (max-width: 560px) { .shell { padding: 8px; } .side { display: flex; } h1 { font-size: 15px; } .topbar { align-items: flex-start; flex-direction: column; } }
</style>
</head>
<body>
<main class="shell">
  <header class="topbar">
    <div class="title"><h1>CMRE Neuro 基础命令回放</h1><span class="badge">SIMULATOR PASS</span></div>
    <div id="replayId" class="footer"></div>
  </header>
  <section class="layout">
    <div class="map-panel">
      <div class="map-wrap" id="mapWrap"><canvas id="map" width="1200" height="750"></canvas><div class="map-hud" id="mapHud"></div><div class="tooltip" id="tooltip"></div></div>
      <div class="controls">
        <button id="play" title="播放/暂停">▶</button><button id="back" title="上一帧">◀</button><button id="forward" title="下一帧">▶</button><button id="start" title="跳到开始">|◀</button><button id="end" title="跳到结束">▶|</button>
        <span class="spacer"></span><span class="speed-label">倍速</span>
        <button class="speed" data-speed="0.5">0.5x</button><button class="speed active" data-speed="1">1x</button><button class="speed" data-speed="2">2x</button><button class="speed" data-speed="4">4x</button><button class="speed" data-speed="8">8x</button><button class="speed" data-speed="16">16x</button>
      </div>
      <div class="timeline"><input id="seek" type="range" min="0" max="0" value="0" step="1"><div class="time-row"><span id="timeStart"></span><strong id="timeCurrent"></strong><span id="timeEnd"></span></div><div class="marker-strip" id="markers"></div></div>
      <div class="footer">空格播放/暂停 · ←/→ 逐帧 · 点击时间轴或关键标记跳转</div>
    </div>
    <aside class="side">
      <section class="panel"><h2>当前状态</h2><div class="stats"><div class="stat"><span>Loop</span><strong id="loop">0</strong></div><div class="stat"><span>游戏时间</span><strong id="gameTime">0.0s</strong></div><div class="stat"><span>状态版本</span><strong id="stateVersion">0</strong></div><div class="stat"><span>Context</span><strong id="contextVersion">0</strong></div><div class="stat"><span>矿物</span><strong id="minerals">0</strong></div><div class="stat"><span>补给</span><strong id="supply">0/0</strong></div></div></section>
      <section class="panel"><h2>单位</h2><div id="units" class="units"></div></section>
      <section class="panel"><h2>动作</h2><div id="actions" class="actions"></div></section>
      <section class="panel"><h2>当前事件</h2><div id="events" class="events"></div></section>
    </aside>
  </section>
  <div class="footer" id="meta"></div>
</main>
<script>
const RECORDS = __REPLAY_DATA__;
const FRAMES = RECORDS.filter(r => r.record_type === 'frame');
const ACTIONS = RECORDS.filter(r => r.record_type === 'action');
const SUMMARY = RECORDS.find(r => r.record_type === 'summary') || {};
const COLORS = { 0: '#8796a3', 1: '#4aa3ff', 2: '#e36c6c', 3: '#57d18c', 4: '#e7c45b', 5: '#cf78e8', 6: '#62d3cb' };
const BUILDINGS = new Set(['CommandCenter','Barracks','Factory','Starport','SupplyDepot','Bunker','EngineeringBay','MissileTurret','SensorTower','Refinery']);
const canvas = document.getElementById('map');
const ctx = canvas.getContext('2d');
const tooltip = document.getElementById('tooltip');
const allUnits = FRAMES.flatMap(f => [...(f.context.own_units || []), ...(f.context.visible_enemies || [])]);
const xs = allUnits.map(u => u.x), ys = allUnits.map(u => u.y);
const bounds = { minX: Math.min(...xs, 0), maxX: Math.max(...xs, 10), minY: Math.min(...ys, 0), maxY: Math.max(...ys, 10) };
const padX = Math.max(1.5, (bounds.maxX - bounds.minX) * .16), padY = Math.max(1.5, (bounds.maxY - bounds.minY) * .16);
bounds.minX -= padX; bounds.maxX += padX; bounds.minY -= padY; bounds.maxY += padY;
let index = 0, speed = 1, playing = false, lastTime = 0, fractional = 0;

function frame() { return FRAMES[index] || FRAMES[0]; }
function position(x, y) { return [(x - bounds.minX) / (bounds.maxX - bounds.minX) * canvas.width, canvas.height - (y - bounds.minY) / (bounds.maxY - bounds.minY) * canvas.height]; }
function unitRadius(unit) { return BUILDINGS.has(unit.unit_type_id) ? 12 : 7; }
function unitColor(unit) { return COLORS[unit.owner] || '#fff'; }
function fmtLoop(loop) { return `Loop ${loop} · ${(loop / 22.4).toFixed(1)}s`; }
function esc(value) { return String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

function drawGrid() {
  ctx.fillStyle = '#0d171d'; ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = '#18303d'; ctx.lineWidth = 1;
  for (let i = 0; i <= 10; i++) { const x = i * canvas.width / 10, y = i * canvas.height / 10; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, canvas.height); ctx.stroke(); ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvas.width, y); ctx.stroke(); }
  ctx.strokeStyle = '#31586b'; ctx.strokeRect(1, 1, canvas.width - 2, canvas.height - 2);
}
function drawUnit(unit) {
  const [x, y] = position(unit.x, unit.y), r = unitRadius(unit), color = unitColor(unit);
  ctx.fillStyle = color; ctx.strokeStyle = '#071016'; ctx.lineWidth = 2;
  if (BUILDINGS.has(unit.unit_type_id)) { ctx.fillRect(x-r, y-r, r*2, r*2); ctx.strokeRect(x-r, y-r, r*2, r*2); }
  else { ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill(); ctx.stroke(); }
  const label = unit.unit_type_id === 'Marine' ? 'M' : unit.unit_type_id === 'SCV' ? 'S' : BUILDINGS.has(unit.unit_type_id) ? 'B' : '';
  if (label) { ctx.fillStyle = '#071016'; ctx.font = 'bold 9px Consolas'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(label, x, y); }
  if (unit.owner === 1 && unit.health > 0) { const width = Math.max(20, r * 2.5); ctx.fillStyle = '#2a1b1b'; ctx.fillRect(x-width/2, y+r+4, width, 3); ctx.fillStyle = '#57d18c'; ctx.fillRect(x-width/2, y+r+4, width, 3); }
}
function drawEventMarks(current) {
  for (const event of current.events || []) {
    const unit = [...(current.context.own_units || []), ...(current.context.visible_enemies || [])].find(u => u.entity_id === event.entity_id);
    if (!unit) continue;
    const [x, y] = position(unit.x, unit.y); ctx.strokeStyle = '#f2b45f'; ctx.lineWidth = 3; ctx.beginPath(); ctx.arc(x, y, 19, 0, Math.PI * 2); ctx.stroke();
  }
}
function draw() {
  const current = frame(); drawGrid();
  for (const unit of current.context.own_units || []) drawUnit(unit);
  for (const unit of current.context.visible_enemies || []) drawUnit(unit);
  drawEventMarks(current);
  document.getElementById('mapHud').textContent = `${fmtLoop(current.loop)} · ${current.label}`;
  updateSidebar(current); document.getElementById('seek').value = index;
  document.getElementById('timeCurrent').textContent = fmtLoop(current.loop);
}
function updateSidebar(current) {
  const mission = current.context.mission || {}, resources = current.context.resources || {};
  document.getElementById('loop').textContent = current.loop;
  document.getElementById('gameTime').textContent = `${(current.loop / 22.4).toFixed(1)}s`;
  document.getElementById('stateVersion').textContent = current.state_version;
  document.getElementById('contextVersion').textContent = current.context.context_version;
  document.getElementById('minerals').textContent = resources.minerals ?? 0;
  document.getElementById('supply').textContent = `${resources.supply_used ?? 0}/${resources.supply_cap ?? 0}`;
  const counts = {};
  for (const unit of current.context.own_units || []) counts[unit.unit_type_id] = (counts[unit.unit_type_id] || 0) + 1;
  document.getElementById('units').innerHTML = Object.entries(counts).sort().map(([name, count]) => `<div class="unit-row"><span>${esc(name)}</span><span>${count}</span></div>`).join('') || '<span class="footer">无单位</span>';
  document.getElementById('actions').innerHTML = ACTIONS.map(action => { const active = action.loop <= current.loop; return `<div class="action ${active ? 'current' : ''}" data-loop="${action.loop}"><div class="name">${esc(action.name)}</div><div class="meta">${esc(action.action_id)} · loop ${action.loop} · <span class="ok">${action.dispatched.success ? 'OK' : 'FAIL'}</span></div></div>`; }).join('');
  const events = [...(current.events || []), ...(current.command_results || []).map(r => ({...r, kind: `command:${r.command_kind}`}))];
  document.getElementById('events').innerHTML = events.map(event => `<div class="event"><div>${esc(event.kind)}</div><div class="meta">loop ${event.loop} · entity ${event.entity_id || 0}</div></div>`).join('') || '<span class="footer">当前帧无事件</span>';
}
function stop() { playing = false; document.getElementById('play').textContent = '▶'; document.getElementById('play').classList.remove('active'); }
function setIndex(value) { index = Math.max(0, Math.min(FRAMES.length - 1, Number(value))); fractional = index; draw(); }
function tick(time) { if (!playing) return; const delta = Math.min(100, time - lastTime); lastTime = time; fractional += delta * speed / 250; if (fractional >= FRAMES.length - 1) { setIndex(FRAMES.length - 1); stop(); return; } index = Math.floor(fractional); draw(); requestAnimationFrame(tick); }
function toggle() { playing = !playing; document.getElementById('play').classList.toggle('active', playing); document.getElementById('play').textContent = playing ? '⏸' : '▶'; if (playing) { lastTime = performance.now(); requestAnimationFrame(tick); } }
function jumpToLoop(loop) { const target = FRAMES.reduce((best, item, i) => Math.abs(item.loop - loop) < Math.abs(FRAMES[best].loop - loop) ? i : best, 0); stop(); setIndex(target); }

document.getElementById('replayId').textContent = SUMMARY.replay_id || '';
document.getElementById('meta').textContent = `${SUMMARY.actions_successful}/${SUMMARY.actions_total} actions · ${SUMMARY.event_count} events · trace ${String(SUMMARY.trace_sha256 || '').slice(0, 12)}`;
document.getElementById('seek').max = Math.max(0, FRAMES.length - 1);
document.getElementById('timeStart').textContent = fmtLoop(FRAMES[0].loop);
document.getElementById('timeEnd').textContent = fmtLoop(FRAMES[FRAMES.length - 1].loop);
for (const action of ACTIONS) { const marker = document.createElement('span'); marker.className = 'marker action'; marker.title = `${action.name} @ loop ${action.loop}`; marker.style.left = `${(FRAMES.findIndex(f => f.loop >= action.loop) / Math.max(1, FRAMES.length - 1)) * 100}%`; marker.onclick = () => jumpToLoop(action.loop); document.getElementById('markers').appendChild(marker); }
for (const current of FRAMES) for (const event of current.events || []) { const marker = document.createElement('span'); marker.className = 'marker'; marker.title = `${event.kind} @ loop ${event.loop}`; marker.style.left = `${(FRAMES.indexOf(current) / Math.max(1, FRAMES.length - 1)) * 100}%`; marker.onclick = () => setIndex(FRAMES.indexOf(current)); document.getElementById('markers').appendChild(marker); }
document.getElementById('play').onclick = toggle;
document.getElementById('back').onclick = () => { stop(); setIndex(index - 1); };
document.getElementById('forward').onclick = () => { stop(); setIndex(index + 1); };
document.getElementById('start').onclick = () => { stop(); setIndex(0); };
document.getElementById('end').onclick = () => { stop(); setIndex(FRAMES.length - 1); };
document.getElementById('seek').oninput = event => { stop(); setIndex(event.target.value); };
document.querySelectorAll('.speed').forEach(button => button.onclick = () => { speed = Number(button.dataset.speed); document.querySelectorAll('.speed').forEach(item => item.classList.remove('active')); button.classList.add('active'); });
document.addEventListener('keydown', event => { if (event.code === 'Space') { event.preventDefault(); toggle(); } else if (event.code === 'ArrowLeft') { stop(); setIndex(index - 1); } else if (event.code === 'ArrowRight') { stop(); setIndex(index + 1); } else if (event.code === 'Home') { stop(); setIndex(0); } else if (event.code === 'End') { stop(); setIndex(FRAMES.length - 1); } });
canvas.addEventListener('mousemove', event => { const rect = canvas.getBoundingClientRect(); const x = (event.clientX - rect.left) * canvas.width / rect.width, y = (event.clientY - rect.top) * canvas.height / rect.height; let hit = null; for (const unit of frame().context.own_units || []) { const [ux, uy] = position(unit.x, unit.y), r = unitRadius(unit) + 5; if ((x-ux)*(x-ux) + (y-uy)*(y-uy) <= r*r) { hit = unit; break; } } if (!hit) { tooltip.style.display = 'none'; return; } tooltip.innerHTML = `P${hit.owner} ${esc(hit.unit_type_id)}<br>id=${hit.entity_id} · (${Number(hit.x).toFixed(1)}, ${Number(hit.y).toFixed(1)})<br>HP=${hit.health}`; tooltip.style.display = 'block'; tooltip.style.left = `${event.clientX - rect.left + 12}px`; tooltip.style.top = `${event.clientY - rect.top + 12}px`; });
canvas.addEventListener('mouseleave', () => tooltip.style.display = 'none');
draw();
</script>
</body>
</html>
'''


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["load_records", "render_player_html"]
