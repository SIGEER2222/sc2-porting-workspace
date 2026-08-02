"""Generate a faithful, self-contained map replay player for simulator JSONL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable


def load_records(path: Path) -> list[dict[str, Any]]:
    """Load newline-delimited replay records without dropping source fields."""

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
    """Render a single HTML file that preserves and renders every observed entity."""

    data = list(records)
    if not data:
        raise ValueError("replay contains no records")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("<", "\\u003c")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_PLAYER_TEMPLATE.replace("__REPLAY_DATA__", payload), encoding="utf-8")


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
<title>CMRE Dead of Night 经济推进回放</title>
<style>
:root { color-scheme: dark; --bg:#0b0e12; --panel:#171b21; --panel2:#101419; --line:#303944; --muted:#8c98a5; --text:#eaf0f5; --blue:#55a9ff; --red:#ff6b6b; --green:#65d69a; --orange:#f4b860; --purple:#bd83ff; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:13px/1.4 "Segoe UI","Microsoft YaHei",sans-serif; }
button,input { font:inherit; }
button { min-height:30px; padding:0 10px; color:var(--text); background:#202832; border:1px solid var(--line); border-radius:4px; cursor:pointer; }
button:hover,button.active { background:#28567b; border-color:var(--blue); }
.shell { max-width:1700px; margin:0 auto; padding:12px; }
.header { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:10px; padding:10px 14px; background:var(--panel); border:1px solid var(--line); border-left:4px solid var(--green); }
.header h1 { margin:0; font-size:17px; }
.header .meta { color:var(--muted); font:11px Consolas,monospace; }
.layout { display:grid; grid-template-columns:minmax(600px,1fr) 430px; gap:10px; }
.map-panel,.panel { background:var(--panel); border:1px solid var(--line); border-radius:5px; }
.map-panel { padding:9px; }
.map-wrap { position:relative; overflow:hidden; border:1px solid #44515e; background:#0c1117; }
canvas { display:block; width:100%; height:auto; }
#map { aspect-ratio:1/1; cursor:crosshair; }
.map-hud { position:absolute; left:9px; top:9px; padding:5px 8px; background:rgba(5,8,12,.84); border:1px solid #526273; color:#dbe5ed; font:11px Consolas,monospace; pointer-events:none; }
.tooltip { display:none; position:absolute; z-index:3; pointer-events:none; max-width:360px; padding:7px 9px; background:rgba(3,6,9,.96); border:1px solid #6c8497; color:#fff; font:11px/1.55 Consolas,monospace; white-space:nowrap; }
.controls { display:flex; flex-wrap:wrap; align-items:center; gap:5px; margin-top:8px; }
.controls .label { margin-left:7px; color:var(--muted); }
.timeline { margin-top:8px; padding:8px 10px; background:var(--panel); border:1px solid var(--line); }
.timeline input { width:100%; accent-color:var(--blue); cursor:pointer; }
.time-row { display:flex; justify-content:space-between; color:var(--muted); font:11px Consolas,monospace; }
.markers { position:relative; height:19px; margin-top:3px; border-top:1px solid #33404c; }
.marker { position:absolute; top:0; width:2px; height:8px; background:var(--orange); cursor:pointer; }
.marker.action { height:13px; background:var(--blue); }
.marker:hover { background:#fff; }
.side { display:flex; flex-direction:column; gap:9px; min-width:0; }
.panel { padding:9px 11px; min-width:0; }
.panel h2 { margin:0 0 7px; color:var(--muted); font-size:11px; font-weight:600; letter-spacing:.7px; text-transform:uppercase; }
.stats { display:grid; grid-template-columns:1fr 1fr; gap:3px 14px; }
.stat { display:flex; justify-content:space-between; gap:8px; min-width:0; }
.stat span:first-child { color:var(--muted); }
.stat strong { overflow:hidden; color:#fff; font:12px Consolas,monospace; text-overflow:ellipsis; white-space:nowrap; }
.legend { display:flex; flex-wrap:wrap; gap:7px 12px; color:#dbe4eb; font-size:11px; }
.legend-item { display:flex; align-items:center; gap:4px; }
.legend-dot { width:10px; height:10px; border:1px solid #071016; border-radius:50%; }
.columns { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.unit-list { max-height:132px; overflow:auto; font:11px/1.6 Consolas,monospace; }
.unit-line { display:flex; justify-content:space-between; gap:6px; border-bottom:1px solid #242c35; }
.unit-line .count { color:var(--blue); }
.unit-line.enemy .count { color:var(--red); }
.unit-line.neutral .count { color:var(--orange); }
.chart { width:100%; height:92px; margin-top:6px; background:var(--panel2); border:1px solid #252e38; }
.entity-tools { display:flex; gap:5px; margin-bottom:6px; }
.entity-tools input { width:100%; min-height:29px; padding:0 7px; color:var(--text); background:#0d1217; border:1px solid var(--line); border-radius:3px; }
.entity-table-wrap { max-height:278px; overflow:auto; border:1px solid #2c3540; background:var(--panel2); }
.entity-table { width:100%; border-collapse:collapse; font:10px/1.35 Consolas,monospace; }
.entity-table th { position:sticky; top:0; z-index:1; padding:4px; color:var(--muted); background:#222a33; text-align:left; }
.entity-table td { padding:3px 4px; border-top:1px solid #242c35; white-space:nowrap; }
.entity-table tr { cursor:pointer; }
.entity-table tr:hover,.entity-table tr.selected { background:#21415b; }
.side-blue { color:var(--blue); }.side-red { color:var(--red); }.side-neutral { color:var(--orange); }
.event-list,.action-list { max-height:145px; overflow:auto; }
.event,.action { margin:3px 0; padding:4px 6px; border-left:2px solid var(--orange); background:var(--panel2); font-size:11px; }
.action { border-left-color:var(--blue); cursor:pointer; }.action.current { background:#1d3a53; }
.event .meta,.action .meta { color:var(--muted); font:10px Consolas,monospace; }
details { color:var(--muted); font-size:11px; }.raw { max-height:220px; overflow:auto; margin:6px 0 0; color:#c8d3dd; white-space:pre-wrap; word-break:break-word; font:10px/1.45 Consolas,monospace; }
.footer { margin-top:7px; color:var(--muted); font:10px Consolas,monospace; }
@media (max-width:1050px) { .layout { grid-template-columns:1fr; }.side { display:grid; grid-template-columns:1fr 1fr; align-items:start; }.side .wide { grid-column:1/-1; } }
@media (max-width:620px) { .shell { padding:7px; }.side { display:flex; }.layout { grid-template-columns:minmax(0,1fr); }.header { align-items:flex-start; flex-direction:column; }.controls button { padding:0 7px; }.columns { grid-template-columns:1fr; } }
</style>
</head>
<body>
<main class="shell">
  <header class="header"><h1>CMRE Dead of Night 经济推进回放</h1><div class="meta" id="headerMeta"></div></header>
  <section class="layout">
    <div class="map-panel">
      <div class="map-wrap"><canvas id="map" width="900" height="900"></canvas><div id="mapHud" class="map-hud"></div><div id="tooltip" class="tooltip"></div></div>
      <div class="controls">
        <button id="play" title="播放/暂停">▶</button><button id="back" title="上一帧">◀</button><button id="forward" title="下一帧">▶</button><button id="start" title="首帧">|◀</button><button id="end" title="末帧">▶|</button>
        <span class="label">倍速</span><button class="speed" data-speed="0.5">0.5x</button><button class="speed active" data-speed="1">1x</button><button class="speed" data-speed="2">2x</button><button class="speed" data-speed="4">4x</button><button class="speed" data-speed="8">8x</button><button class="speed" data-speed="16">16x</button>
      </div>
      <div class="timeline"><input id="seek" type="range" min="0" max="0" value="0" step="1"><div class="time-row"><span id="timeStart"></span><strong id="timeCurrent"></strong><span id="timeEnd"></span></div><div id="markers" class="markers"></div></div>
      <div class="controls"><label><input id="staticLayer" type="checkbox" checked> 原始地图 Objects 层</label></div>
      <div class="footer">空格播放/暂停 · ←/→ 逐帧 · 点击实体查看完整字段 · 时间轴拖动切换原始观测帧</div>
    </div>
    <aside class="side">
      <section class="panel wide"><h2>当前状态</h2><div class="stats"><div class="stat"><span>地图</span><strong id="mapName"></strong></div><div class="stat"><span>Loop</span><strong id="loop"></strong></div><div class="stat"><span>游戏时间</span><strong id="gameTime"></strong></div><div class="stat"><span>状态版本</span><strong id="stateVersion"></strong></div><div class="stat"><span>Context 版本</span><strong id="contextVersion"></strong></div><div class="stat"><span>阶段</span><strong id="phase"></strong></div><div class="stat"><span>夜晚 / 波次</span><strong id="nightWave"></strong></div><div class="stat"><span>友军 / 敌军 / 中立</span><strong id="entityTotals"></strong></div></div></section>
      <section class="panel"><h2>经济与补给</h2><div class="stats"><div class="stat"><span>矿物</span><strong id="minerals"></strong></div><div class="stat"><span>瓦斯</span><strong id="vespene"></strong></div><div class="stat"><span>补给</span><strong id="supply"></strong></div></div><canvas id="economy" class="chart" width="410" height="92"></canvas></section>
      <section class="panel wide"><h2>兵种与建筑构成</h2><div class="columns"><div><div class="footer">友军</div><div id="friendlyTypes" class="unit-list"></div></div><div><div class="footer">敌军 / 其他阵营</div><div id="enemyTypes" class="unit-list"></div></div></div><div id="legend" class="legend" style="margin-top:8px"></div></section>
      <section class="panel wide"><h2>当前帧全部实体</h2><div class="entity-tools"><input id="entitySearch" placeholder="按 ID、单位类型、Owner、状态筛选"></div><div class="entity-table-wrap"><table class="entity-table"><thead><tr><th>ID</th><th>Owner</th><th>类型</th><th>状态</th><th>HP</th><th>位置</th></tr></thead><tbody id="entities"></tbody></table></div></section>
      <section class="panel"><h2>动作</h2><div id="actions" class="action-list"></div></section>
      <section class="panel"><h2>事件</h2><div id="events" class="event-list"></div></section>
      <section class="panel wide"><details><summary>当前原始 context</summary><pre id="rawContext" class="raw"></pre></details></section>
    </aside>
  </section>
  <div id="footerMeta" class="footer"></div>
</main>
<script>
const RECORDS = __REPLAY_DATA__;
const FRAMES = RECORDS.filter(r => r.record_type === "frame" || r.entities_by_player);
const ACTIONS = RECORDS.filter(r => r.record_type === "action");
const SUMMARY = RECORDS.find(r => r.record_type === "summary") || {};
const MAP_META = RECORDS.find(r => r.record_type === "map") || {};
const COLORS = {"0":"#a5aeb7","1":"#55a9ff","2":"#ff6b6b","3":"#65d69a","4":"#f4b860","5":"#bd83ff","6":"#62d3cb"};
const BUILDINGS = new Set(["CommandCenter","Nexus","Hatchery","Barracks","Factory","Starport","SupplyDepot","Bunker","EngineeringBay","MissileTurret","SensorTower","Refinery","Pylon","PhotonCannon","SpineCrawler","SporeCrawler","Gateway","Forge","SpawningPool","HydraliskDen","RoachWarren","GhostAcademy","RoboticsFacility"]);
const RESOURCES = new Set(["MineralField","VespeneGeyser"]);
const RADIUS = {"CommandCenter":10,"Nexus":10,"Hatchery":10,"Barracks":7,"Factory":8,"Starport":8,"SupplyDepot":6,"Bunker":6,"EngineeringBay":7,"MissileTurret":5,"SensorTower":5,"Refinery":6,"Pylon":5,"PhotonCannon":5,"SpineCrawler":6,"SporeCrawler":5,"Gateway":8,"Forge":7,"SpawningPool":8,"HydraliskDen":7,"RoachWarren":7,"GhostAcademy":7,"RoboticsFacility":8,"SCV":4,"Drone":4,"Probe":4,"Marine":4,"Marauder":4.5,"SiegeTank":5,"Medivac":4.5,"Viking":4.5,"Ghost":4,"Zergling":3,"Hydralisk":4,"Roach":4.5,"Mutalisk":4.5,"Ultralisk":6,"Baneling":3.5,"Zealot":4.5,"Stalker":4.5,"Immortal":5,"Colossus":6,"Carrier":6,"MineralField":5,"VespeneGeyser":5};
const MAX_HP = {"Marine":45,"Marauder":125,"SCV":45,"CommandCenter":1500,"Barracks":1000,"Factory":1250,"Starport":1300,"SupplyDepot":400,"Bunker":400,"EngineeringBay":850,"MissileTurret":250,"SensorTower":250,"Refinery":500,"Pylon":200,"PhotonCannon":200,"Zergling":35,"Hydralisk":80,"Roach":145,"Ultralisk":500,"Baneling":30,"Zealot":100,"Stalker":80,"Immortal":200,"Colossus":200,"Carrier":300};
const canvas = document.getElementById("map"), ctx = canvas.getContext("2d"), tooltip = document.getElementById("tooltip");
const mapImage = new Image();
const staticObjects = Array.isArray(MAP_META.static_objects) ? MAP_META.static_objects : [];
const friendlyPlayers = new Set((MAP_META.friendly_players || [1]).map(Number));
const mapImageRect = MAP_META.image_rect_px || {x:48,y:48,w:160,h:160};
const mapWorld = MAP_META.world_bounds || {min_x:16,max_x:176,min_y:16,max_y:176};
if (MAP_META.minimap_data_url) { mapImage.src = MAP_META.minimap_data_url; mapImage.onload = () => draw(); }
let index = 0, playing = false, speed = 1, lastTime = 0, fractional = 0, selectedId = null, search = "";
function esc(value) { return String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c])); }
function number(value, fallback=0) { const n = Number(value); return Number.isFinite(n) ? n : fallback; }
function normalize(raw, ownerOverride=null) { const legacy = raw.entity_id === undefined; return { id: legacy ? raw.id : raw.entity_id, owner: ownerOverride ?? (legacy ? raw.p : raw.owner), type: legacy ? raw.t : raw.unit_type_id, x:number(raw.x), y:number(raw.y), hp:number(legacy ? raw.hp : raw.health), shields:number(raw.shields), energy:number(raw.energy), state:raw.state || (raw.alive === false ? "dead" : "visible"), alive:raw.alive !== false, raw }; }
function entitiesOf(frame) { const context = frame.context || {}; const result = []; if (frame.entities_by_player) { for (const [owner, list] of Object.entries(frame.entities_by_player)) for (const raw of list || []) result.push(normalize(raw, Number(owner))); return result; } for (const raw of context.neutral_units || context.neutral_resources || context.map_resources || []) result.push(normalize(raw, 0)); for (const raw of context.own_units || []) result.push(normalize(raw, raw.owner ?? context.player_id ?? 1)); for (const raw of context.visible_enemies || []) result.push(normalize(raw, raw.owner ?? 2)); return result; }
const allEntities = FRAMES.flatMap(entitiesOf), xs = allEntities.map(e => e.x), ys = allEntities.map(e => e.y);
const bounds = { minX:Math.min(...xs,0), maxX:Math.max(...xs,10), minY:Math.min(...ys,0), maxY:Math.max(...ys,10) }; const padX=Math.max(5,(bounds.maxX-bounds.minX)*.05), padY=Math.max(5,(bounds.maxY-bounds.minY)*.05); bounds.minX-=padX; bounds.maxX+=padX; bounds.minY-=padY; bounds.maxY+=padY;
function current() { return FRAMES[index] || FRAMES[0]; }
function contextOf(frame) { return frame.context || {}; }
function mapNameOf(frame) { return MAP_META.map_name || contextOf(frame).map || frame.map || "dead-of-night"; }
function eventsOf(frame) { return frame.events || frame.key_events || []; }
function resourcesOf(frame) { const c=contextOf(frame), m=c.mission||{}; return c.resources||m.resources||frame.p1_resources||{}; }
function pos(x,y) {
  if (MAP_META.minimap_data_url) {
    const nx=(number(x)-mapWorld.min_x)/(mapWorld.max_x-mapWorld.min_x), ny=(mapWorld.max_y-number(y))/(mapWorld.max_y-mapWorld.min_y);
    return [((mapImageRect.x+nx*mapImageRect.w)/256)*canvas.width, ((mapImageRect.y+ny*mapImageRect.h)/256)*canvas.height];
  }
  return [(x-bounds.minX)/(bounds.maxX-bounds.minX)*canvas.width, canvas.height-(y-bounds.minY)/(bounds.maxY-bounds.minY)*canvas.height];
}
function isFriendly(owner) { return friendlyPlayers.has(Number(owner)); }
function color(owner) { return COLORS[String(owner)] || (isFriendly(owner) ? COLORS["1"] : COLORS["2"]); }
function radius(type) { return RADIUS[type] || (BUILDINGS.has(type) ? 7 : 4); }
function hpValue(hp) { return Math.abs(hp) > 4096 ? hp / 1024 : hp; }
function maxHp(type) { return MAX_HP[type] || 100; }
function formatTime(loop) { return `${(number(loop)/22.4).toFixed(1)}s`; }
function ownerName(owner) { return Number(owner) === 0 ? "中立" : isFriendly(owner) ? `P${owner} 友军` : `P${owner} 敌军`; }
function drawGrid() {
  ctx.fillStyle="#05070a"; ctx.fillRect(0,0,canvas.width,canvas.height);
  if (MAP_META.minimap_data_url && mapImage.complete) { ctx.globalAlpha=1; ctx.drawImage(mapImage,0,0,canvas.width,canvas.height); }
  else { ctx.fillStyle="#10161c"; ctx.fillRect(0,0,canvas.width,canvas.height); }
  if (!MAP_META.minimap_data_url) { ctx.strokeStyle="#1c2b36"; ctx.lineWidth=1; for(let i=0;i<=10;i++){const x=i*canvas.width/10,y=i*canvas.height/10;ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,canvas.height);ctx.stroke();ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(canvas.width,y);ctx.stroke();} }
  ctx.strokeStyle="#dbe5ed88";ctx.lineWidth=1;ctx.strokeRect(1,1,canvas.width-2,canvas.height-2);
}
function drawStaticObject(object) {
  const [x,y]=pos(object.x,object.y); const r=radius(object.type)*0.72;
  ctx.save(); ctx.globalAlpha=0.28; ctx.fillStyle="#d8dee5"; ctx.strokeStyle="#101820"; ctx.lineWidth=1;
  if (BUILDINGS.has(object.type)) { ctx.fillRect(x-r,y-r,r*2,r*2); ctx.strokeRect(x-r,y-r,r*2,r*2); }
  else { ctx.beginPath();ctx.arc(x,y,Math.max(1.5,r*.55),0,Math.PI*2);ctx.fill(); }
  ctx.restore();
}
function drawEntity(entity) { if(!entity.alive) return; const [x,y]=pos(entity.x,entity.y), r=radius(entity.type), c=color(entity.owner); ctx.fillStyle=c;ctx.strokeStyle=selectedId===entity.id?"#fff":"#0a1117";ctx.lineWidth=selectedId===entity.id?3:1.5; if(RESOURCES.has(entity.type)){ctx.fillRect(x-r,y-r,r*2,r*2);ctx.strokeRect(x-r,y-r,r*2,r*2);} else if(BUILDINGS.has(entity.type)){ctx.fillRect(x-r,y-r,r*2,r*2);ctx.strokeRect(x-r,y-r,r*2,r*2);} else {ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fill();ctx.stroke();} const hp=Math.max(0,Math.min(1,hpValue(entity.hp)/maxHp(entity.type))); if(!RESOURCES.has(entity.type)){const w=Math.max(18,r*2.8);ctx.fillStyle="#351b1b";ctx.fillRect(x-w/2,y+r+3,w,3);ctx.fillStyle=hp>.6?"#56d18b":hp>.3?"#dfbd55":"#e36c6c";ctx.fillRect(x-w/2,y+r+3,w*hp,3);} if(selectedId===entity.id){ctx.fillStyle="#fff";ctx.font="bold 10px Consolas";ctx.textAlign="center";ctx.textBaseline="middle";ctx.fillText(entity.type.slice(0,3),x,y);ctx.textAlign="left";ctx.textBaseline="alphabetic";} }
function draw() { const f=current(), es=entitiesOf(f); drawGrid(); if(document.getElementById("staticLayer").checked) for(const object of staticObjects) drawStaticObject(object); for(const e of es.filter(e=>e.owner===0))drawEntity(e); for(const e of es.filter(e=>e.owner!==0 && !isFriendly(e.owner)))drawEntity(e); for(const e of es.filter(e=>isFriendly(e.owner)))drawEntity(e); for(const ev of eventsOf(f)){const e=es.find(x=>x.id===ev.entity_id);if(e){const [x,y]=pos(e.x,e.y);ctx.strokeStyle="#f4b860";ctx.lineWidth=3;ctx.beginPath();ctx.arc(x,y,radius(e.type)+7,0,Math.PI*2);ctx.stroke();}} document.getElementById("mapHud").textContent=`${mapNameOf(f)} · Loop ${f.loop} · ${formatTime(f.loop)} · Night ${f.context?.mission?.night ?? f.current_night ?? 0} · ${f.label || "frame"}`; updateSidebar(f,es); document.getElementById("seek").value=index; document.getElementById("timeCurrent").textContent=`Loop ${f.loop} · ${formatTime(f.loop)}`; }
function counts(es, owner) { const out={}; for(const e of es.filter(e=>owner==="enemy"?!isFriendly(e.owner)&&e.owner!==0:owner==="friendly"?isFriendly(e.owner):owner===null?true:e.owner===owner)) out[e.type]=(out[e.type]||0)+1; return out; }
function listHtml(map, cls) { return Object.entries(map).sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0])).map(([type,count])=>`<div class="unit-line ${cls}"><span>${esc(type)}</span><span class="count">${count}</span></div>`).join("") || `<span class="footer">无记录</span>`; }
function updateSidebar(f, es) { const c=f.context||{}, m=c.mission||{}, res=resourcesOf(f); const friendly=es.filter(e=>isFriendly(e.owner)), enemy=es.filter(e=>e.owner!==0&&!isFriendly(e.owner)), neutral=es.filter(e=>e.owner===0); document.getElementById("mapName").textContent=mapNameOf(f);document.getElementById("loop").textContent=f.loop;document.getElementById("gameTime").textContent=`${number(f.real_sec ?? f.ts_sec ?? number(f.loop)/22.4).toFixed(1)}s`;document.getElementById("stateVersion").textContent=f.state_version ?? c.state_version ?? f.loop ?? "-";document.getElementById("contextVersion").textContent=c.context_version ?? "legacy";document.getElementById("phase").textContent=m.phase||((f.current_night??0)>0?"night":"active");document.getElementById("nightWave").textContent=`${m.night??f.current_night??0} / ${m.wave??f.waves_fired??0}`;document.getElementById("entityTotals").textContent=`${friendly.length} / ${enemy.length} / ${neutral.length}`;document.getElementById("minerals").textContent=res.minerals??0;document.getElementById("vespene").textContent=res.vespene??0;document.getElementById("supply").textContent=`${res.supply_used??0}/${res.supply_cap??0}`;document.getElementById("friendlyTypes").innerHTML=listHtml(counts(es,"friendly"),"friendly");document.getElementById("enemyTypes").innerHTML=listHtml(counts(es,"enemy"),"enemy"); renderLegend(es);renderEntities(es);renderActions(f.loop);renderEvents(f);document.getElementById("rawContext").textContent=JSON.stringify(c&&Object.keys(c).length?c:f,null,2);drawEconomy(index); }
function renderLegend(es) { const owners=[...new Set(es.map(e=>e.owner))].sort((a,b)=>a-b); document.getElementById("legend").innerHTML=owners.map(owner=>`<span class="legend-item"><i class="legend-dot" style="background:${color(owner)}"></i>${ownerName(owner)} (${es.filter(e=>e.owner===owner).length})</span>`).join("") || `<span class="footer">当前帧没有实体</span>`; }
function renderEntities(es) { const rows=es.filter(e=>`${e.id} ${e.owner} ${e.type} ${e.state}`.toLowerCase().includes(search)).sort((a,b)=>a.owner-b.owner||a.id-b.id);document.getElementById("entities").innerHTML=rows.map(e=>`<tr class="${selectedId===e.id?"selected":""}" data-id="${e.id}"><td>${e.id}</td><td class="${isFriendly(e.owner)?"side-blue":e.owner===0?"side-neutral":"side-red"}">${e.owner}</td><td>${esc(e.type)}</td><td>${esc(e.state)}</td><td>${hpValue(e.hp).toFixed(0)} / ${maxHp(e.type)}</td><td>${e.x.toFixed(1)},${e.y.toFixed(1)}</td></tr>`).join("") || `<tr><td colspan="6">无匹配实体</td></tr>`;document.querySelectorAll("#entities tr[data-id]").forEach(row=>row.onclick=()=>{selectedId=Number(row.dataset.id);draw();}); }
function renderActions(loop) { document.getElementById("actions").innerHTML=ACTIONS.map(a=>`<div class="action ${number(a.loop)<=number(loop)?"current":""}" data-loop="${a.loop}"><b>${esc(a.name)}</b><div class="meta">${esc(a.action_id)} · loop ${a.loop} · ${a.dispatched?.success?"OK":"FAIL"}</div></div>`).join("")||`<span class="footer">无动作</span>`;document.querySelectorAll(".action").forEach(el=>el.onclick=()=>jumpToLoop(Number(el.dataset.loop))); }
function renderEvents(f) { const items=[...eventsOf(f),...(f.command_results||[]).map(e=>({...e,kind:`command:${e.command_kind||e.code}`}))]; document.getElementById("events").innerHTML=items.map(e=>`<div class="event"><b>${esc(e.kind)}</b><div class="meta">loop ${e.loop??f.loop} · entity ${e.entity_id??0}</div></div>`).join("")||`<span class="footer">当前帧无事件</span>`; }
function drawEconomy(cur) { const chart=document.getElementById("economy"), c=chart.getContext("2d"), w=chart.width,h=chart.height; c.fillStyle="#101419";c.fillRect(0,0,w,h);const vals=FRAMES.map(f=>Number(resourcesOf(f).minerals||0)), max=Math.max(50,...vals);c.strokeStyle="#55a9ff";c.lineWidth=2;c.beginPath();vals.forEach((v,i)=>{const x=i/(Math.max(1,vals.length-1))*w,y=h-v/max*h;i?c.lineTo(x,y):c.moveTo(x,y);});c.stroke();c.strokeStyle="#fff";c.lineWidth=1;const x=cur/Math.max(1,FRAMES.length-1)*w;c.beginPath();c.moveTo(x,0);c.lineTo(x,h);c.stroke();c.fillStyle="#8c98a5";c.font="10px Consolas";c.fillText("Minerals",5,12);c.fillText(String(max),w-40,12); }
function setIndex(value) { index=Math.max(0,Math.min(FRAMES.length-1,Number(value)));fractional=index;draw(); }
function stop() { playing=false;document.getElementById("play").textContent="▶";document.getElementById("play").classList.remove("active"); }
function toggle() { playing=!playing;document.getElementById("play").textContent=playing?"⏸":"▶";document.getElementById("play").classList.toggle("active",playing);if(playing){lastTime=performance.now();requestAnimationFrame(tick);} }
function tick(time) { if(!playing)return;const delta=Math.min(100,time-lastTime);lastTime=time;fractional+=delta*speed/250;if(fractional>=FRAMES.length-1){setIndex(FRAMES.length-1);stop();return;}index=Math.floor(fractional);draw();requestAnimationFrame(tick); }
function jumpToLoop(loop) { const target=FRAMES.reduce((best,item,i)=>Math.abs(item.loop-loop)<Math.abs(FRAMES[best].loop-loop)?i:best,0);stop();setIndex(target); }
function setupMarkers() { const strip=document.getElementById("markers"),den=Math.max(1,FRAMES.length-1);ACTIONS.forEach(a=>{const m=document.createElement("span");m.className="marker action";m.title=`${a.name} @ loop ${a.loop}`;m.style.left=`${FRAMES.findIndex(f=>f.loop>=a.loop)/den*100}%`;m.onclick=()=>jumpToLoop(a.loop);strip.appendChild(m);});FRAMES.forEach((f,i)=>eventsOf(f).forEach(ev=>{const m=document.createElement("span");m.className="marker";m.title=`${ev.kind} @ loop ${ev.loop}`;m.style.left=`${i/den*100}%`;m.onclick=()=>setIndex(i);strip.appendChild(m);})); }
document.getElementById("play").onclick=toggle;document.getElementById("back").onclick=()=>{stop();setIndex(index-1);};document.getElementById("forward").onclick=()=>{stop();setIndex(index+1);};document.getElementById("start").onclick=()=>{stop();setIndex(0);};document.getElementById("end").onclick=()=>{stop();setIndex(FRAMES.length-1);};document.getElementById("seek").oninput=e=>{stop();setIndex(e.target.value);};document.querySelectorAll(".speed").forEach(button=>button.onclick=()=>{speed=Number(button.dataset.speed);document.querySelectorAll(".speed").forEach(item=>item.classList.remove("active"));button.classList.add("active");});document.getElementById("staticLayer").onchange=draw;document.getElementById("entitySearch").oninput=e=>{search=e.target.value.toLowerCase();renderEntities(entitiesOf(current()));};document.addEventListener("keydown",e=>{if(e.code==="Space"){e.preventDefault();toggle();}else if(e.code==="ArrowLeft"){stop();setIndex(index-1);}else if(e.code==="ArrowRight"){stop();setIndex(index+1);}else if(e.code==="Home"){stop();setIndex(0);}else if(e.code==="End"){stop();setIndex(FRAMES.length-1);}});
canvas.addEventListener("mousemove",e=>{const f=current(),es=entitiesOf(f),rect=canvas.getBoundingClientRect(),mx=(e.clientX-rect.left)*canvas.width/rect.width,my=(e.clientY-rect.top)*canvas.height/rect.height;let found=null;for(const unit of [...es].reverse()){const [x,y]=pos(unit.x,unit.y),r=radius(unit.type)+6;if((mx-x)**2+(my-y)**2<=r*r){found=unit;break;}}if(!found){tooltip.style.display="none";return;}tooltip.innerHTML=`${esc(ownerName(found.owner))} · ${esc(found.type)}<br>ID=${found.id} · state=${esc(found.state)}<br>HP=${hpValue(found.hp).toFixed(0)}/${maxHp(found.type)} · shield=${hpValue(found.shields).toFixed(0)} · energy=${hpValue(found.energy).toFixed(0)}<br>(${found.x.toFixed(2)}, ${found.y.toFixed(2)})`;tooltip.style.display="block";tooltip.style.left=`${e.clientX-rect.left+12}px`;tooltip.style.top=`${e.clientY-rect.top+12}px`;});canvas.addEventListener("mouseleave",()=>tooltip.style.display="none");
document.getElementById("headerMeta").textContent=`${SUMMARY.replay_id||"replay"} · ${SUMMARY.evidence_type||"simulator"}`;document.getElementById("footerMeta").textContent=`${SUMMARY.actions_successful??0}/${SUMMARY.actions_total??0} actions · ${SUMMARY.event_count??0} events · ${allEntities.length} entity snapshots · trace ${String(SUMMARY.trace_sha256||"").slice(0,12)}`;document.getElementById("seek").max=Math.max(0,FRAMES.length-1);document.getElementById("timeStart").textContent=`Loop ${FRAMES[0].loop} · ${formatTime(FRAMES[0].loop)}`;document.getElementById("timeEnd").textContent=`Loop ${FRAMES[FRAMES.length-1].loop} · ${formatTime(FRAMES[FRAMES.length-1].loop)}`;setupMarkers();draw();
</script>
</body>
</html>
'''


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["load_records", "render_player_html"]
