/**
 * CMRE 启动器 - Tabbed Layout
 *
 * 布局：左侧栏（当前指挥官+难度+模式+敌方+高级选项）| 主区域（Tab：指挥官/地图/突变因子）
 * 突变因子列表式布局，说明文字直接显示；点击不重建DOM；localStorage 预设保存
 */

const API = {
  factors: "/api/factors",
  maps: "/api/maps",
  mutators: "/api/mutators",
  voicePacks: "/api/voice-packs",
  buffMetadata: "/api/buff-metadata",
  extraMods: (bank) => `/api/extra-mods?commander=${encodeURIComponent(bank)}`,
  launch: "/api/launch",
  launchAsync: "/api/launch-async",
  stop: "/api/stop",
  status: "/api/status",
  logStream: "/api/logs/stream",
  vibeCatalog: "/api/vibe/catalog",
  vibeSessions: "/api/vibe/sessions",
  vibeStatus: "/api/vibe/status",
  vibeConnect: "/api/vibe/connect",
  vibeDisconnect: "/api/vibe/disconnect",
  vibeInvoke: "/api/vibe/invoke",
  vibeRunVm: "/api/vibe/run-vm",
  asset: (relPath) => `/api/assets/dds?path=${encodeURIComponent(relPath)}`,
};

const PRESET_KEY = "cmre_presets_v1";
const runtimeState = {
  functions: [],
  selectedFunction: null,
  selectedTrace: null,
  trace: [],
  pollTimer: null,
};

const state = {
  maps: [],
  commanders: [],
  mutators: [],
  voicePacks: [],
  buffMetadata: [],
  extraMods: [],
  cmdrFilter: "all",
  activeTab: "commanders",
  presets: [],
  presetListOpen: false,
  selected: {
    mapName: "亡者之夜.SC2Map",
    mapPackage: "cmre",
    commander: "TerranRaynor",
    commanderPackage: "cmre",
    faction: "",
    commanderBank: "Raynor",
    commanderPortrait: "ui_commanderportrait_raynor.dds",
    commanderCachedImage: "",
    mode: 1,
    difficultyBase: 0,
    difficultyPlus: 0,
    enemy: "",
    mutators: [],
    voicePack: "",
    extraMods: [],
    apiMode: false,
    listenPort: 5000,
    // Buff 补丁：仅对原版 18 指挥官生效。
    // - enabled: 是否启用补丁
    // - buffs: ["P1","P2","P3"] 子集，对应 3 个威望优点
    // - masteries: { slot1: value, ... }，slot 为 1..6，value 为 0..30；空对象表示用默认 30
    // - extras: { P1: Set([0,...]), P2: Set(...), P3: Set(...) }，每个威望下勾选的 extra 子选项 index 集合
    buffPatch: {
      enabled: false,
      buffs: [],
      masteries: {},
      extras: { P1: new Set(), P2: new Set(), P3: new Set() },
      _lastCommander: "",
    },
  },
};

const DIFFICULTY_BASE_NAMES = ["普通", "困难", "残暴", "残酷", "极限", "炼狱"];

const ENEMY_CONFIG = {
  "": { name: "默认", color: "#7a8693", abbr: "?" },
  "ZergAmonSwarm": { name: "虫族", color: "#c85858", abbr: "虫" },
  "ProtossCorruptedTemplar": { name: "星灵", color: "#c8a858", abbr: "星" },
};

const RACE_CONFIG = {
  Terran: { color: "#d4a047", abbr: "T", name: "人类" },
  Zerg: { color: "#c85858", abbr: "Z", name: "异虫" },
  Protoss: { color: "#5898c8", abbr: "P", name: "星灵" },
  Unknown: { color: "#7a8693", abbr: "?", name: "未知" },
};

const GROUP_LABELS = {
  official: "官方",
  alenger: "起义",
  reborn: "重生",
  "revolution-overdrive": "起义狂潮",
};

function $(id) { return document.getElementById(id); }
function $$(s, r) { return (r || document).querySelectorAll(s); }
function showStatus(text, type) {
  const el = $("status");
  el.textContent = text; el.hidden = !text; el.dataset.type = type || "info";
}
function esc(s) { return String(s).replace(/[&<>"']/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c])); }
function raceOf(c) {
  if (c.startsWith("Terran")) return "Terran";
  if (c.startsWith("Zerg")) return "Zerg";
  if (c.startsWith("Protoss")) return "Protoss";
  return "Unknown";
}

function loadPresets() {
  try {
    const raw = localStorage.getItem(PRESET_KEY);
    state.presets = raw ? JSON.parse(raw) : [];
  } catch { state.presets = []; }
}
function savePresets() {
  try { localStorage.setItem(PRESET_KEY, JSON.stringify(state.presets)); } catch {}
}

function buildPresetSnapshot() {
  const s = state.selected;
  return {
    name: "",
    mapName: s.mapName,
    mapPackage: s.mapPackage,
    commander: s.commander,
    commanderPackage: s.commanderPackage,
    faction: s.faction,
    mode: s.mode,
    difficultyBase: s.difficultyBase,
    difficultyPlus: s.difficultyPlus,
    enemy: s.enemy,
    mutators: s.mutators.map(m => ({ id: m.id, enhanced: m.enhanced })),
    voicePack: s.voicePack,
    extraMods: [...s.extraMods],
    savedAt: 0,
  };
}

function applyPreset(preset) {
  const s = state.selected;
  s.mapName = preset.mapName || s.mapName;
  const map = state.maps.find(m => m.id === s.mapName && (!preset.mapPackage || m.packageId === preset.mapPackage));
  if (map) s.mapPackage = map.packageId || "cmre";
  s.mode = preset.mode || 1;
  s.difficultyBase = preset.difficultyBase || 0;
  s.difficultyPlus = preset.difficultyPlus || 0;
  s.enemy = preset.enemy || "";
  s.mutators = (preset.mutators || []).map(m => ({ id: m.id, enhanced: !!m.enhanced })).slice(0, 20);
  s.voicePack = preset.voicePack || "";
  s.extraMods = [...(preset.extraMods || [])];
  const cmdr = state.commanders.find(c => c.id === preset.commander);
  if (cmdr) {
    s.commander = cmdr.id;
    s.commanderPackage = cmdr.packageId || "cmre";
    s.faction = cmdr.faction || "";
    s.commanderBank = cmdr.bank;
    s.commanderPortrait = cmdr.portrait;
    s.commanderCachedImage = cmdr.cachedImage || "";
  }
  syncUI();
  renderCommanderGrid();
  renderCommanderCard();
  renderMaps();
  renderMutators();
  loadExtraMods();
  updateFooter();
  updateMutatorCount();
}

function syncUI() {
  const s = state.selected;
  $("mode").value = s.mode;
  $("difficultyBase").value = s.difficultyBase;
  $("difficultyBase-value").textContent = s.difficultyBase;
  $("difficultyBase-hint").textContent = DIFFICULTY_BASE_NAMES[s.difficultyBase] || "Lv" + s.difficultyBase;
  $("difficultyPlus").value = s.difficultyPlus;
  $("difficultyPlus-value").textContent = s.difficultyPlus;
  $("difficultyPlus-hint").textContent = s.difficultyPlus === 0 ? "无" : "+" + s.difficultyPlus;
  $("voicePack").value = s.voicePack;
  $("apiMode").checked = s.apiMode;
  $("api-mode-config").hidden = !s.apiMode;
  $("listenPort").value = s.listenPort;
}

function updateFooter() {
  const s = state.selected;
  const cmd = state.commanders.find(c => c.id === s.commander);
  const map = state.maps.find(m => m.id === s.mapName && (!s.mapPackage || m.packageId === s.mapPackage))
    || state.maps.find(m => m.id === s.mapName);
  const parts = [];
  parts.push(map ? map.name : "未选择地图");
  parts.push(cmd ? cmd.label : s.commander);
  const diff = DIFFICULTY_BASE_NAMES[s.difficultyBase] + (s.difficultyPlus > 0 ? "+" + s.difficultyPlus : "");
  parts.push(diff);
  if (s.mutators.length > 0) parts.push("突变x" + s.mutators.length);
  if (s.enemy) {
    const ec = ENEMY_CONFIG[s.enemy];
    parts.push(ec ? ec.name : s.enemy);
  }
  $("footer-summary").textContent = parts.join(" | ");
}

function updateMutatorCount() {
  const n = state.selected.mutators.length;
  $("mutator-count").textContent = n;
  const tabCount = $("tab-mutator-count");
  if (tabCount) tabCount.textContent = n;
}

async function loadFactors() {
  const data = await fetch(API.factors).then(r => r.json());
  const modeSel = $("mode");
  modeSel.innerHTML = "";
  for (const m of data.modes) {
    const o = document.createElement("option");
    o.value = m.id; o.textContent = m.name;
    modeSel.appendChild(o);
  }
  modeSel.value = state.selected.mode;
  renderEnemies(data.enemies);
  return data;
}

async function loadMaps() {
  const data = await fetch(API.maps).then(r => r.json());
  state.maps = [...(data.maps || []), ...(data.rebornMaps || []), ...(data.revolutionMaps || [])];
  const selectedMap = state.maps.find(m => m.id === state.selected.mapName && m.packageId === state.selected.mapPackage)
    || state.maps.find(m => m.id === state.selected.mapName);
  if (selectedMap) state.selected.mapPackage = selectedMap.packageId || "cmre";
  renderMaps();
}

async function loadCommanders() {
  const data = await fetch(API.factors).then(r => r.json());
  state.commanders = [...(data.commanders || []), ...(data.revolutionCommanders || [])];
  if (state.commanders.length > 0 && !state.commanders.find(c => c.id === state.selected.commander)) {
    const c = state.commanders[0];
    state.selected.commander = c.id;
    state.selected.commanderPackage = c.packageId || "cmre";
    state.selected.faction = c.faction || "";
    state.selected.commanderBank = c.bank;
    state.selected.commanderPortrait = c.portrait;
    state.selected.commanderCachedImage = c.cachedImage || "";
  }
  renderCommanderGrid();
  renderCommanderCard();
}

async function loadMutators() {
  state.mutators = await fetch(API.mutators).then(r => r.json());
  renderMutators();
}

async function loadVoicePacks() {
  const data = await fetch(API.voicePacks).then(r => r.json());
  state.voicePacks = data.voicePacks || [];
  const sel = $("voicePack");
  sel.innerHTML = '<option value="">指挥官默认语音</option>';
  for (const v of state.voicePacks) {
    const o = document.createElement("option");
    o.value = v.id; o.textContent = v.name;
    sel.appendChild(o);
  }
  sel.value = state.selected.voicePack;
}

async function loadExtraMods() {
  const bank = state.selected.commanderBank;
  const data = await fetch(API.extraMods(bank)).then(r => r.json());
  state.extraMods = data.extraMods || [];
  renderExtraMods();
}

/* === Buff 补丁元数据 === */
async function loadBuffMetadata() {
  try {
    const data = await fetch(API.buffMetadata).then(r => r.json());
    state.buffMetadata = data.commanders || [];
  } catch {
    state.buffMetadata = [];
  }
  renderBuffPatch();
}

/* === Buff 补丁：根据当前指挥官渲染 === */
function getCurrentBuffCommander() {
  const cid = state.selected.commander;
  return state.buffMetadata.find(c => c.runtime_commander === cid) || null;
}

function renderBuffPatch() {
  const body = $("buff-body");
  const panel = $("buff-panel");
  const enableCk = $("buff-enable");
  const statusEl = $("buff-panel-status");
  const cmdr = getCurrentBuffCommander();
  const cid = state.selected.commander;

  if (!cmdr) {
    panel.hidden = true;
    return;
  }

  // 切换到不同指挥官时重置 buff 选择（威望 P1/P2/P3 含义不同）
  if (state.selected.buffPatch._lastCommander !== cid) {
    state.selected.buffPatch.buffs = [];
    state.selected.buffPatch.masteries = {};
    state.selected.buffPatch.extras = { P1: new Set(), P2: new Set(), P3: new Set() };
    state.selected.buffPatch._lastCommander = cid;
  }

  panel.hidden = false;
  enableCk.disabled = false;
  enableCk.checked = state.selected.buffPatch.enabled;

  // 更新面板状态文字
  let statusText = cmdr.display_name;
  if (state.selected.buffPatch.enabled) {
    const n = state.selected.buffPatch.buffs.length;
    const extraN = ["P1","P2","P3"].reduce((s,k) => s + state.selected.buffPatch.extras[k].size, 0);
    if (n > 0) {
      statusText += ` · ${n} 威望`;
      if (extraN > 0) statusText += ` + ${extraN} 子选项`;
    } else {
      statusText += " · 已启用";
    }
  } else {
    statusText += " · 未启用";
  }
  statusEl.textContent = statusText;

  // 威望优点区
  let html = '<div class="buff-section">';
  html += '<div class="buff-section-head">威望优点（叠加，不替代原版威望）</div>';
  html += '<div class="buff-section-hint">勾选要叠加的威望优点，效果通过 supplement upgrade 独立施加，不影响原版威望的缺点。</div>';
  for (const p of cmdr.prestiges) {
    const token = `P${p.slot}`;
    const checked = state.selected.buffPatch.buffs.includes(token) ? "checked" : "";
    const reviewBadge = p.needs_manual_review ? '<span class="buff-review" title="' + esc(p.review_notes || '') + '">⚠ 需注意</span>' : '';
    let extrasHtml = '';
    if (p.extras && p.extras.length > 0) {
      const pSelected = state.selected.buffPatch.buffs.includes(token);
      extrasHtml = `<div class="buff-extras" data-p="${token}" style="${pSelected ? '' : 'display:none;'}">`;
      for (const ex of p.extras) {
        const exChecked = state.selected.buffPatch.extras[token].has(ex.index) ? "checked" : "";
        const exReview = ex.needs_manual_review ? '<span class="buff-review" title="效果待完善">⚠</span>' : '';
        extrasHtml += `
          <label class="buff-extra-row">
            <input type="checkbox" class="buff-extra-ck" data-p="${token}" data-idx="${ex.index}" ${exChecked}>
            <div class="buff-extra-info">
              <div class="buff-extra-name">└ ${esc(ex.name)} ${exReview}</div>
              <div class="buff-extra-desc">${esc(ex.description)}</div>
              <div class="buff-extra-upgrade">↑ ${esc(ex.upgrade_id)}</div>
            </div>
          </label>`;
      }
      extrasHtml += '</div>';
    }
    html += `
      <label class="buff-prestige-row">
        <input type="checkbox" class="buff-prestige-ck" data-token="${token}" ${checked}>
        <div class="buff-prestige-info">
          <div class="buff-prestige-name">P${p.slot} · ${esc(p.name)} ${reviewBadge}</div>
          <div class="buff-prestige-adv"><span class="buff-tag buff-tag-adv">优点</span> ${esc(p.advantage_text || '(无说明)')}</div>
          <div class="buff-prestige-dis"><span class="buff-tag buff-tag-dis">原缺点</span> ${esc(p.disadvantage_text || '(无)')}</div>
          ${p.bonus_upgrade_id ? `<div class="buff-prestige-upgrade">↑ ${esc(p.bonus_upgrade_id)}</div>` : ''}
        </div>
      </label>
      ${extrasHtml}`;
  }
  html += '</div>';

  // 精通点数区
  html += '<div class="buff-section">';
  html += '<div class="buff-section-head">精通点数（覆盖原版，默认满级 30）</div>';
  html += '<div class="buff-section-hint">滑块控制每个精通槽位的点数。默认 30（满级），可单独调整。</div>';
  for (const m of cmdr.masteries) {
    const stored = state.selected.buffPatch.masteries[m.slot];
    const val = (stored !== undefined) ? stored : 30;
    html += `
      <div class="buff-mastery-row">
        <div class="buff-mastery-head">
          <span class="buff-mastery-name">槽 ${m.slot} · ${esc(m.name)}</span>
          <span class="buff-mastery-val" id="buff-mastery-val-${m.slot}">${val}</span>
        </div>
        <input type="range" class="buff-mastery-slider" data-slot="${m.slot}" min="0" max="30" step="1" value="${val}">
        <div class="buff-mastery-fmt">${esc(m.value_format || '')} · 增量 ${esc((m.point_increments || []).join('/'))}</div>
      </div>`;
  }
  html += '</div>';

  body.innerHTML = html;

  // 绑定威望优点 checkbox
  body.querySelectorAll(".buff-prestige-ck").forEach(ck => {
    ck.onchange = () => {
      const token = ck.dataset.token;
      const set = new Set(state.selected.buffPatch.buffs);
      if (ck.checked) { set.add(token); } else {
        set.delete(token);
        // 取消勾选威望时，清除该威望下所有 extra 子选项
        state.selected.buffPatch.extras[token].clear();
        body.querySelectorAll(`.buff-extra-ck[data-p="${token}"]`).forEach(ec => { ec.checked = false; });
      }
      state.selected.buffPatch.buffs = Array.from(set).sort();
      // 显示/隐藏该威望的 extras 容器
      const extrasDiv = body.querySelector(`.buff-extras[data-p="${token}"]`);
      if (extrasDiv) extrasDiv.style.display = ck.checked ? '' : 'none';
      updateBuffStatus();
    };
  });

  // 绑定 extra 子选项 checkbox
  body.querySelectorAll(".buff-extra-ck").forEach(ck => {
    ck.onchange = () => {
      const p = ck.dataset.p;
      const idx = parseInt(ck.dataset.idx, 10);
      const set = state.selected.buffPatch.extras[p];
      if (ck.checked) set.add(idx); else set.delete(idx);
      updateBuffStatus();
    };
  });

  // 绑定精通滑块
  body.querySelectorAll(".buff-mastery-slider").forEach(sl => {
    sl.oninput = () => {
      const slot = parseInt(sl.dataset.slot, 10);
      const v = parseInt(sl.value, 10);
      state.selected.buffPatch.masteries[slot] = v;
      const valEl = $("buff-mastery-val-" + slot);
      if (valEl) valEl.textContent = v;
    };
  });
}

function updateBuffStatus() {
  const statusEl = $("buff-panel-status");
  const cmdr = getCurrentBuffCommander();
  if (!cmdr || !statusEl) return;
  let text = cmdr.display_name;
  if (state.selected.buffPatch.enabled) {
    const n = state.selected.buffPatch.buffs.length;
    const extraN = ["P1","P2","P3"].reduce((s,k) => s + state.selected.buffPatch.extras[k].size, 0);
    if (n > 0) {
      text += ` · ${n} 威望`;
      if (extraN > 0) text += ` + ${extraN} 子选项`;
    } else {
      text += " · 已启用";
    }
  } else {
    text += " · 未启用";
  }
  statusEl.textContent = text;
}

/* === Tab 切换 === */
function switchTab(tabName) {
  state.activeTab = tabName;
  $$(".tab-btn").forEach(b => b.classList.toggle("active", b.dataset.tab === tabName));
  $$(".tab-content").forEach(c => c.hidden = c.id !== "tab-" + tabName);
}

/* === Runtime Debug Console === */
async function runtimeRequest(url, options = {}) {
  const response = await fetch(url, options);
  let data = {};
  try { data = await response.json(); } catch { data = { error: "服务返回了无效 JSON" }; }
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function runtimeJson(value) {
  try { return JSON.stringify(value, null, 2); }
  catch (e) { return String(value); }
}

function runtimeFunctionMeta(definition) {
  const args = Object.entries(definition.args || {}).map(([name, spec]) => {
    const suffix = spec.required ? "" : "?";
    return `${name}${suffix}:${spec.type || "value"}`;
  });
  const mode = definition.debug_only ? "debug-only" : (definition.capability || "callable");
  return `${mode} · ${args.join(", ") || "无参数"}`;
}

function renderRuntimeCatalog() {
  const list = $("runtime-function-list");
  const query = ($("runtime-function-search")?.value || "").trim().toLowerCase();
  const matches = runtimeState.functions.filter(item => {
    const haystack = `${item.function_id} ${item.capability || ""} ${item.handler || ""}`.toLowerCase();
    return !query || haystack.includes(query);
  });
  $("runtime-catalog-count").textContent = `${matches.length}/${runtimeState.functions.length}`;
  list.innerHTML = "";
  if (!matches.length) {
    list.innerHTML = '<p class="hint">没有匹配的显式注册函数。</p>';
    return;
  }
  for (const definition of matches) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "runtime-function-item" + (definition.debug_only ? " debug-only" : "");
    if (runtimeState.selectedFunction?.function_id === definition.function_id) button.classList.add("selected");
    const name = document.createElement("span");
    name.className = "runtime-function-name";
    name.textContent = definition.function_id;
    const meta = document.createElement("span");
    meta.className = "runtime-function-meta";
    meta.textContent = runtimeFunctionMeta(definition);
    button.append(name, meta);
    button.onclick = () => selectRuntimeFunction(definition);
    list.appendChild(button);
  }
}

function selectRuntimeFunction(definition) {
  runtimeState.selectedFunction = definition;
  $("runtime-function-id").value = definition.function_id;
  $("runtime-selected-function").textContent = definition.function_id;
  const defaults = {};
  for (const [name, spec] of Object.entries(definition.args || {})) {
    if (Object.prototype.hasOwnProperty.call(spec, "default")) defaults[name] = spec.default;
  }
  $("runtime-call-args").value = runtimeJson(defaults);
  const args = Object.entries(definition.args || {}).map(([name, spec]) => `${name}${spec.required ? "" : "?"}`).join(", ");
  $("runtime-args-hint").textContent = `${definition.debug_only ? "debug-only · " : ""}${args || "无参数"}`;
  renderRuntimeCatalog();
  pollRuntimeStatus();
}

function runtimeTraceStatus(record) {
  if (record.status === "passed" || record.status === "allowed-error") return ["通过", "trace-pass"];
  if (record.status === "failed") return ["失败", "trace-fail"];
  const code = record.result?.error_code;
  if (code && code !== "OK") return [code, "trace-fail"];
  return [record.op === "assert" ? "断言" : "完成", "trace-neutral"];
}

function runtimeTraceFunction(record) {
  return record.function_id || record.fn || (record.op === "step" ? `step(${record.loops || 1})` : record.op || "-");
}

function runtimeTraceSummary(record) {
  if (record.result) {
    const code = record.result.error_code || "OK";
    const payload = record.result.payload || {};
    return `${code} ${JSON.stringify(payload)}`;
  }
  if (record.actual !== undefined) return `actual=${JSON.stringify(record.actual)} ${record.reason || ""}`;
  return record.status || "";
}

function renderRuntimeTrace() {
  const body = $("runtime-trace-body");
  $("runtime-trace-count").textContent = String(runtimeState.trace.length);
  body.innerHTML = "";
  if (!runtimeState.trace.length) {
    body.innerHTML = '<tr><td colspan="5" class="runtime-empty">连接后，函数调用和 VM 结果会出现在这里。</td></tr>';
    $("runtime-detail").textContent = "暂无记录";
    return;
  }
  runtimeState.trace.forEach((record, index) => {
    const row = document.createElement("tr");
    row.className = "runtime-trace-row" + (runtimeState.selectedTrace === index ? " selected" : "");
    const [status, statusClass] = runtimeTraceStatus(record);
    const cells = [index + 1, record.op || "-", runtimeTraceFunction(record), status, runtimeTraceSummary(record)];
    cells.forEach((value, cellIndex) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      if (cellIndex === 1) cell.className = "runtime-trace-op";
      if (cellIndex === 2) cell.className = "runtime-trace-function";
      if (cellIndex === 3) cell.className = statusClass;
      if (cellIndex === 4) cell.className = "runtime-trace-summary";
      row.appendChild(cell);
    });
    row.onclick = () => {
      runtimeState.selectedTrace = index;
      $("runtime-detail").textContent = runtimeJson(record);
      renderRuntimeTrace();
    };
    body.appendChild(row);
  });
  if (runtimeState.selectedTrace === null || runtimeState.selectedTrace >= runtimeState.trace.length) {
    runtimeState.selectedTrace = runtimeState.trace.length - 1;
  }
  $("runtime-detail").textContent = runtimeJson(runtimeState.trace[runtimeState.selectedTrace]);
}

function syncRuntimeStatus(status) {
  const data = status || {};
  const connected = data.status === "connected";
  const busy = Boolean(data.running);
  const stateName = busy ? "busy" : (data.status || "disconnected");
  const statusEl = $("runtime-status");
  statusEl.dataset.state = stateName;
  statusEl.textContent = busy ? `执行中 · ${data.running}` : ({ connected: "已连接", connecting: "连接中", error: "连接错误", disconnected: "未连接" }[data.status] || "未连接");
  $("runtime-connect").disabled = data.status === "connecting" || busy;
  $("runtime-disconnect").disabled = !connected || busy;
  $("runtime-invoke").disabled = !connected || busy || !runtimeState.selectedFunction;
  $("runtime-run-vm").disabled = !connected || busy;
  const session = data.session_id ? `session=${data.session_id}` : "session=未建立";
  $("runtime-session-meta").textContent = `${data.port ? `port=${data.port} · ` : ""}${session}${data.error ? ` · ${data.error}` : ""}`;
  if (Array.isArray(data.trace)) {
    runtimeState.trace = data.trace;
    renderRuntimeTrace();
  }
}

async function pollRuntimeStatus() {
  try { syncRuntimeStatus(await runtimeRequest(API.vibeStatus)); }
  catch (e) { $("runtime-session-meta").textContent = `调试服务不可用: ${e.message}`; }
}

async function loadRuntimeCatalog() {
  try {
    const data = await runtimeRequest(API.vibeCatalog);
    runtimeState.functions = data.functions || [];
    renderRuntimeCatalog();
  } catch (e) {
    $("runtime-function-list").innerHTML = `<p class="hint">函数目录加载失败: ${esc(e.message)}</p>`;
  }
}

async function loadRuntimeSessions() {
  try {
    const data = await runtimeRequest(API.vibeSessions);
    const select = $("runtime-session-select");
    select.innerHTML = '<option value="">新建或手动填写</option>';
    for (const session of data.sessions || []) {
      const option = document.createElement("option");
      option.value = session.session_id;
      option.textContent = `${session.session_id} · seq ${session.sequence} · ${session.operation || "未知"}`;
      select.appendChild(option);
    }
    showStatus(`发现 ${(data.sessions || []).length} 个可恢复 session`, "success");
  } catch (e) { showStatus(`读取 session 失败: ${e.message}`, "error"); }
}

async function connectRuntime() {
  const button = $("runtime-connect");
  button.disabled = true;
  syncRuntimeStatus({ status: "connecting" });
  try {
    const data = await runtimeRequest(API.vibeConnect, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        port: parseInt($("runtime-port").value, 10) || 5000,
        rpcSessionId: $("runtime-session-id").value.trim(),
        mapPath: $("runtime-map-path").value.trim(),
        joinWait: 0,
      }),
    });
    syncRuntimeStatus(data);
    $("runtime-session-id").value = data.session_id || $("runtime-session-id").value;
    showStatus("Vibe session 已连接", "success");
  } catch (e) {
    await pollRuntimeStatus();
    showStatus(`Vibe session 连接失败: ${e.message}`, "error");
  }
}

async function disconnectRuntime() {
  try {
    syncRuntimeStatus({ status: "connecting", running: "disconnect" });
    const data = await runtimeRequest(API.vibeDisconnect, { method: "POST" });
    syncRuntimeStatus(data);
    showStatus("Vibe session 已断开", "info");
  } catch (e) { showStatus(`断开失败: ${e.message}`, "error"); }
}

async function invokeRuntimeFunction() {
  if (!runtimeState.selectedFunction) return;
  let args;
  try { args = JSON.parse($("runtime-call-args").value || "{}"); }
  catch (e) { showStatus(`args JSON 无效: ${e.message}`, "error"); return; }
  try {
    const data = await runtimeRequest(API.vibeInvoke, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ functionId: runtimeState.selectedFunction.function_id, args }),
    });
    syncRuntimeStatus(data.status);
    showStatus(data.record.status === "passed" ? "函数调用成功" : `函数返回 ${data.record.result?.error_code || "失败"}`, data.record.status === "passed" ? "success" : "warn");
  } catch (e) { await pollRuntimeStatus(); showStatus(`函数调用失败: ${e.message}`, "error"); }
}

async function runRuntimeVm() {
  let program;
  try { program = JSON.parse($("runtime-vm-program").value || "{}"); }
  catch (e) { showStatus(`VM JSON 无效: ${e.message}`, "error"); return; }
  try {
    const data = await runtimeRequest(API.vibeRunVm, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ program }),
    });
    syncRuntimeStatus(data.status);
    const passed = data.result?.status === "passed";
    showStatus(passed ? "VM 执行成功" : `VM 执行失败: ${data.result?.error || data.error || "未知错误"}`, passed ? "success" : "error");
  } catch (e) { await pollRuntimeStatus(); showStatus(`VM 请求失败: ${e.message}`, "error"); }
}

function initRuntimeConsole() {
  $("runtime-function-search").oninput = renderRuntimeCatalog;
  $("runtime-load-sessions").onclick = loadRuntimeSessions;
  $("runtime-connect").onclick = connectRuntime;
  $("runtime-disconnect").onclick = disconnectRuntime;
  $("runtime-invoke").onclick = invokeRuntimeFunction;
  $("runtime-run-vm").onclick = runRuntimeVm;
  $("runtime-session-select").onchange = e => { $("runtime-session-id").value = e.target.value; };
  loadRuntimeCatalog();
  pollRuntimeStatus();
  if (!runtimeState.pollTimer) runtimeState.pollTimer = window.setInterval(pollRuntimeStatus, 1000);
}

/* === 地图渲染 === */
function renderMaps() {
  const grid = $("map-list");
  grid.innerHTML = "";
  for (const m of state.maps) {
    const div = document.createElement("div");
    div.className = "map-item";
    if (m.id === state.selected.mapName) div.classList.add("selected");
    const previewPath = m.preview ? API.asset(m.preview) : "";
    const previewDiv = document.createElement("div");
    previewDiv.className = "map-item-preview";
    if (previewPath) {
      const img = document.createElement("img");
      img.src = previewPath;
      img.alt = m.name;
      img.loading = "lazy";
      img.onerror = function() {
        this.style.display = "none";
        const ph = document.createElement("div");
        ph.className = "map-item-preview-placeholder";
        ph.textContent = m.name;
        this.parentElement.appendChild(ph);
      };
      previewDiv.appendChild(img);
    } else {
      const ph = document.createElement("div");
      ph.className = "map-item-preview-placeholder";
      ph.textContent = m.name;
      previewDiv.appendChild(ph);
    }
    const nameDiv = document.createElement("div");
    nameDiv.className = "map-item-name";
    nameDiv.textContent = m.name;
    div.appendChild(previewDiv);
    div.appendChild(nameDiv);
    div.onclick = () => {
      state.selected.mapName = m.id;
      state.selected.mapPackage = m.packageId || "cmre";
      $$(".map-item").forEach(el => el.classList.toggle("selected", el === div));
      updateFooter();
    };
    grid.appendChild(div);
  }
}

/* === 指挥官头像URL === */
function getCommanderPortraitUrl(c) {
  if (c.cachedImage) return c.cachedImage;
  const portraitPath = c.portrait.startsWith("Assets/") ? c.portrait : `Assets/Textures/${c.portrait}`;
  return API.asset(portraitPath);
}

/* === 指挥官网格 === */
function renderCommanderGrid() {
  const grid = $("commander-grid");
  grid.innerHTML = "";
  const filter = state.cmdrFilter;
  const filtered = state.commanders.filter(c => filter === "all" || c.group === filter);
  const countEl = $("cmdr-count");
  if (countEl) countEl.textContent = `${filtered.length} / ${state.commanders.length} 位指挥官`;
  for (const c of filtered) {
    const race = c.race || raceOf(c.id);
    const rc = RACE_CONFIG[race] || RACE_CONFIG.Unknown;
    const div = document.createElement("div");
    div.className = "cmdr-grid-item";
    if (c.id === state.selected.commander) div.classList.add("selected");
    const portraitUrl = getCommanderPortraitUrl(c);
    const useCached = !!c.cachedImage;
    const portraitDiv = document.createElement("div");
    portraitDiv.className = "cmdr-grid-portrait";
    portraitDiv.style.borderColor = rc.color;
    const img = document.createElement("img");
    img.src = portraitUrl;
    img.alt = c.label;
    const abbrDiv = document.createElement("div");
    abbrDiv.className = "cmdr-grid-abbr";
    abbrDiv.style.color = rc.color;
    abbrDiv.textContent = rc.abbr;
    if (useCached) {
      abbrDiv.style.display = "none";
    } else {
      img.onerror = function() {
        this.style.display = "none";
        abbrDiv.style.display = "";
      };
    }
    portraitDiv.appendChild(img);
    portraitDiv.appendChild(abbrDiv);
    const nameDiv = document.createElement("div");
    nameDiv.className = "cmdr-grid-name";
    nameDiv.textContent = c.label;
    div.appendChild(portraitDiv);
    div.appendChild(nameDiv);
    div.onclick = () => {
      state.selected.commander = c.id;
      state.selected.commanderPackage = c.packageId || "cmre";
      state.selected.faction = c.faction || "";
      state.selected.commanderBank = c.bank;
      state.selected.commanderPortrait = c.portrait;
      state.selected.commanderCachedImage = c.cachedImage || "";
      $$(".cmdr-grid-item").forEach(el => el.classList.toggle("selected", el === div));
      renderCommanderCard();
    };
    grid.appendChild(div);
  }
}

/* === 侧栏当前指挥官卡片 === */
function renderCommanderCard() {
  const idx = state.commanders.findIndex(c => c.id === state.selected.commander);
  const c = state.commanders[idx] || state.commanders[0];
  if (!c) return;
  state.selected.commander = c.id;
  state.selected.commanderPackage = c.packageId || "cmre";
  state.selected.faction = c.faction || "";
  state.selected.commanderBank = c.bank;
  state.selected.commanderPortrait = c.portrait;
  state.selected.commanderCachedImage = c.cachedImage || "";
  const race = c.race || raceOf(c.id);
  const rc = RACE_CONFIG[race] || RACE_CONFIG.Unknown;
  const portraitUrl = getCommanderPortraitUrl(c);
  const useCached = !!c.cachedImage;
  const img = $("commander-portrait-img");
  const fb = $("commander-portrait-fb");
  img.src = portraitUrl;
  img.style.display = "";
  fb.style.display = "none";
  fb.textContent = rc.abbr;
  fb.style.color = rc.color;
  if (!useCached) {
    img.onerror = () => { img.style.display = "none"; fb.style.display = ""; };
  } else {
    img.onerror = null;
  }
  $("commander-portrait-large").style.borderColor = rc.color;
  const groupLabel = GROUP_LABELS[c.group] || "";
  $("commander-name-large").textContent = c.label;
  const bankEl = $("commander-bank-large");
  bankEl.innerHTML = `<span style="color:${rc.color}">${rc.abbr}</span> ${rc.name}${groupLabel ? ' · <span class="group-tag">' + esc(groupLabel) + '</span>' : ""} · ${esc(c.bank)}`;
  updateFooter();
  loadExtraMods();
  if (state.buffMetadata.length > 0) renderBuffPatch();
}

/* === 突变因子列表渲染 === */
function createMutatorRow(m) {
  const selEntry = state.selected.mutators.find(x => x.id === m.id);
  const sel = !!selEntry;
  const enh = selEntry ? selEntry.enhanced : false;

  const row = document.createElement("div");
  row.className = "mutator-row";
  row.dataset.mid = m.id;
  if (sel) row.classList.add("selected");

  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.className = "mutator-check";
  checkbox.checked = sel;
  checkbox.addEventListener("click", (e) => { e.stopPropagation(); });
  checkbox.addEventListener("change", () => toggleMutator(m.id));

  const iconWrap = document.createElement("div");
  iconWrap.className = "mutator-icon";
  if (m.cachedImage) {
    const imgWrap = document.createElement("div");
    imgWrap.className = "mutator-icon-img-wrap";
    const img = document.createElement("img");
    img.src = m.cachedImage;
    img.alt = m.name;
    img.loading = "lazy";
    imgWrap.appendChild(img);
    iconWrap.appendChild(imgWrap);
  } else if (m.icon) {
    const imgWrap = document.createElement("div");
    imgWrap.className = "mutator-icon-img-wrap";
    const img = document.createElement("img");
    img.src = API.asset(m.icon);
    img.alt = m.name;
    img.loading = "lazy";
    const textDiv = document.createElement("div");
    textDiv.className = "mutator-icon-text";
    textDiv.style.display = "none";
    const abbr = (m.name || "").replace(/[（(].*?[)）]/g, "").trim().substring(0, 2);
    textDiv.textContent = abbr || "?";
    img.onerror = function() {
      this.style.display = "none";
      textDiv.style.display = "";
    };
    imgWrap.appendChild(img);
    imgWrap.appendChild(textDiv);
    iconWrap.appendChild(imgWrap);
  } else {
    const textDiv = document.createElement("div");
    textDiv.className = "mutator-icon-text";
    const abbr = (m.name || "").replace(/[（(].*?[)）]/g, "").trim().substring(0, 2);
    textDiv.textContent = abbr || "?";
    iconWrap.appendChild(textDiv);
  }

  const infoWrap = document.createElement("div");
  infoWrap.className = "mutator-info";
  const nameDiv = document.createElement("div");
  nameDiv.className = "mutator-name";
  nameDiv.textContent = m.name;
  const descDiv = document.createElement("div");
  descDiv.className = "mutator-desc";
  descDiv.textContent = m.description || "";
  infoWrap.appendChild(nameDiv);
  if (m.description) infoWrap.appendChild(descDiv);

  const enhBtn = document.createElement("div");
  enhBtn.className = "mutator-enhanced";
  enhBtn.textContent = enh ? "强化✓" : "强化";
  if (enh) enhBtn.classList.add("active");
  if (!sel) enhBtn.style.display = "none";
  enhBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    toggleEnhanced(m.id);
  });

  row.appendChild(checkbox);
  row.appendChild(iconWrap);
  row.appendChild(infoWrap);
  row.appendChild(enhBtn);

  row.addEventListener("click", () => toggleMutator(m.id));

  return row;
}

function updateMutatorRow(id) {
  const row = document.querySelector(`.mutator-row[data-mid="${CSS.escape(id)}"]`);
  if (!row) { renderMutators(); return; }
  const selEntry = state.selected.mutators.find(x => x.id === id);
  const sel = !!selEntry;
  const enh = selEntry ? selEntry.enhanced : false;
  row.classList.toggle("selected", sel);
  const cb = row.querySelector(".mutator-check");
  if (cb) cb.checked = sel;
  const enhBtn = row.querySelector(".mutator-enhanced");
  if (enhBtn) {
    enhBtn.style.display = sel ? "" : "none";
    enhBtn.textContent = enh ? "强化✓" : "强化";
    enhBtn.classList.toggle("active", enh);
  }
}

function renderMutators() {
  const list = $("mutator-list");
  const search = $("mutator-search").value.trim().toLowerCase();
  list.innerHTML = "";
  const filtered = state.mutators.filter(m => {
    if (!search) return true;
    return m.name.toLowerCase().includes(search) ||
           (m.description || "").toLowerCase().includes(search) ||
           m.id.toLowerCase().includes(search);
  });
  if (filtered.length === 0) {
    list.innerHTML = '<p class="hint">无匹配因子</p>';
    updateMutatorCount();
    return;
  }
  for (const m of filtered) {
    list.appendChild(createMutatorRow(m));
  }
  updateMutatorCount();
}

function toggleMutator(id) {
  const idx = state.selected.mutators.findIndex(x => x.id === id);
  if (idx >= 0) {
    state.selected.mutators.splice(idx, 1);
  } else {
    if (state.selected.mutators.length >= 20) { showStatus("已达因子上限 20", "warn"); return; }
    state.selected.mutators.push({ id, enhanced: false });
  }
  updateMutatorRow(id);
  updateMutatorCount();
  updateFooter();
}

function toggleEnhanced(id) {
  const m = state.selected.mutators.find(x => x.id === id);
  if (!m) return;
  m.enhanced = !m.enhanced;
  updateMutatorRow(id);
}

/* === 敌方渲染 === */
function renderEnemies(enemies) {
  const list = $("enemy-list");
  list.innerHTML = "";
  for (const e of enemies) {
    const cfg = ENEMY_CONFIG[e.id] || ENEMY_CONFIG[""];
    const div = document.createElement("div");
    div.className = "enemy-opt";
    if (e.id === state.selected.enemy) div.classList.add("selected");
    div.innerHTML = `
      <div class="enemy-opt-icon" style="border-color:${cfg.color};background:${cfg.color}22">
        <span style="color:${cfg.color}">${cfg.abbr}</span>
      </div>
      <div class="enemy-opt-text">${esc(cfg.name || e.name)}<small>${esc(e.description || "")}</small></div>
    `;
    div.onclick = () => {
      state.selected.enemy = e.id;
      $$(".enemy-opt").forEach(el => el.classList.toggle("selected", el === div));
      updateFooter();
    };
    list.appendChild(div);
  }
}

/* === 额外Mod渲染 === */
function renderExtraMods() {
  const list = $("extra-mods-list");
  list.innerHTML = "";
  if (state.extraMods.length === 0) {
    list.innerHTML = '<p class="hint">当前指挥官已自动加载所需mod，无额外可选</p>';
    return;
  }
  for (const m of state.extraMods) {
    const checked = state.selected.extraMods.includes(m.id);
    const label = document.createElement("label");
    label.className = "extra-mod-item";
    if (checked) label.classList.add("selected");
    label.innerHTML = `<input type="checkbox" value="${esc(m.id)}" ${checked ? "checked" : ""}><span>${esc(m.name)}</span>`;
    label.querySelector("input").onchange = (e) => {
      if (e.target.checked) {
        if (!state.selected.extraMods.includes(m.id)) state.selected.extraMods.push(m.id);
        label.classList.add("selected");
      } else {
        state.selected.extraMods = state.selected.extraMods.filter(x => x !== m.id);
        label.classList.remove("selected");
      }
    };
    list.appendChild(label);
  }
}

/* === 预设列表渲染 === */
function renderPresetList() {
  const listEl = $("preset-list");
  listEl.innerHTML = "";
  if (state.presets.length === 0) {
    listEl.innerHTML = '<span class="hint" style="padding:4px 8px">还没有保存的预设</span>';
    return;
  }
  for (let i = 0; i < state.presets.length; i++) {
    const p = state.presets[i];
    const div = document.createElement("div");
    div.className = "preset-item";
    const cmdr = state.commanders.find(c => c.id === p.commander);
    const cmdrLabel = cmdr ? cmdr.label : p.commander;
    const presetMap = state.maps.find(m => m.id === p.mapName && (!p.mapPackage || m.packageId === p.mapPackage))
      || state.maps.find(m => m.id === p.mapName);
    const mapLabel = presetMap ? presetMap.name : "未选择地图";
    div.innerHTML = `
      <span class="preset-item-name" title="地图:${esc(mapLabel)} 指挥官:${esc(cmdrLabel)} 因子:${(p.mutators||[]).length}">${esc(p.name)}</span>
      <span class="preset-item-info">${(p.mutators||[]).length}因子</span>
      <button type="button" class="preset-load" data-i="${i}" title="加载">加载</button>
      <button type="button" class="preset-del" data-i="${i}" title="删除">×</button>
    `;
    listEl.appendChild(div);
  }
  listEl.querySelectorAll(".preset-load").forEach(btn => {
    btn.onclick = (e) => {
      e.stopPropagation();
      const i = parseInt(btn.dataset.i, 10);
      applyPreset(state.presets[i]);
      showStatus(`已加载预设: ${state.presets[i].name}`, "success");
    };
  });
  listEl.querySelectorAll(".preset-del").forEach(btn => {
    btn.onclick = (e) => {
      e.stopPropagation();
      const i = parseInt(btn.dataset.i, 10);
      const name = state.presets[i].name;
      if (confirm(`删除预设「${name}」？`)) {
        state.presets.splice(i, 1);
        savePresets();
        renderPresetList();
      }
    };
  });
}

function openPresetModal() {
  $("preset-modal-count").textContent = state.selected.mutators.length;
  $("preset-name-input").value = "";
  $("preset-modal").hidden = false;
  setTimeout(() => $("preset-name-input").focus(), 50);
}
function closePresetModal() { $("preset-modal").hidden = true; }
function confirmSavePreset() {
  const name = $("preset-name-input").value.trim();
  if (!name) { showStatus("请输入预设名称", "warn"); return; }
  const snapshot = buildPresetSnapshot();
  snapshot.name = name;
  snapshot.savedAt = Date.now();
  const existingIdx = state.presets.findIndex(p => p.name === name);
  if (existingIdx >= 0) {
    if (!confirm(`已存在同名预设「${name}」，覆盖？`)) return;
    state.presets[existingIdx] = snapshot;
  } else {
    state.presets.unshift(snapshot);
    if (state.presets.length > 20) state.presets = state.presets.slice(0, 20);
  }
  savePresets();
  closePresetModal();
  renderPresetList();
  showStatus(`预设「${name}」已保存`, "success");
}

/* === 启动游戏 === */
let logEventSource = null;

async function launchGame() {
  const s = state.selected;
  const btn = $("launch-btn");
  btn.disabled = true; btn.textContent = "启动中...";
  showStatus("正在启动 SC2...", "info");

  const body = {
    commander: s.commander, commanderPackage: s.commanderPackage,
    mapName: s.mapName, mapPackage: s.mapPackage, mode: s.mode,
    difficultyBase: s.difficultyBase, difficultyPlus: s.difficultyPlus,
    enemy: s.enemy, mutators: s.mutators,
    voicePack: s.voicePack, extraMods: s.extraMods,
  };
  if (s.mapPackage === "revolution-overdrive" && s.commanderPackage === "revolution-overdrive") {
    body.packageId = "revolution-overdrive";
    body.faction = s.faction;
  }
  if (s.apiMode) { body.listenPort = s.listenPort; body.apiMinimal = true; }
  // 重生虫心指挥官：透传 reborn 标志和指挥官名，server.py 据此追加 -EnableReborn -RebornCommander
  // 注意：state.selected.commander 是 "RebornZergAbathur" 形式（避免与原版 8 个重名指挥官冲突），
  // 但 launcher 只接受 "ZergAbathur" 形式作为 -Commander，所以用 cmdrMeta.runtimeId 覆盖 body.commander。
  // cmdrMeta.id 唯一（Reborn 前缀），find 能精确匹配；原版指挥官无 runtimeId 字段，保持 s.commander 不变。
  const cmdrMeta = state.commanders.find(c => c.id === s.commander);
  if (cmdrMeta && cmdrMeta.group === "reborn") {
    body.enableReborn = true;
    body.rebornCommander = cmdrMeta.rebornName || cmdrMeta.bank || "";
    if (cmdrMeta.runtimeId) body.commander = cmdrMeta.runtimeId;
  }
  // Buff 补丁：仅当启用且当前指挥官在原版 18 之列时透传
  if (s.buffPatch.enabled && getCurrentBuffCommander()) {
    body.enableBuffPatch = true;
    body.buffs = s.buffPatch.buffs.slice();
    // 转换 masteries dict 为 6 元素数组（按 slot 1..6 顺序）
    const masteryArr = [];
    for (let i = 1; i <= 6; i++) {
      masteryArr.push(s.buffPatch.masteries[i] !== undefined ? s.buffPatch.masteries[i] : 30);
    }
    body.masteries = masteryArr;
    // 转换 extras 为 {P1:[idx,...], P2:[...], P3:[...]} 格式
    const extrasObj = {};
    for (const key of ["P1","P2","P3"]) {
      extrasObj[key] = Array.from(s.buffPatch.extras[key]).sort((a,b) => a-b);
    }
    body.buffExtras = extrasObj;
  }

  const output = $("output");
  const outputBody = $("output-body");
  output.hidden = false;
  outputBody.textContent = "";
  const stopBtn = $("stop-btn");
  if (stopBtn) stopBtn.style.display = "";

  try {
    const resp = await fetch(API.launchAsync, { method: "POST", headers: { "Content-Type": "application/json; charset=utf-8" }, body: JSON.stringify(body) });
    const data = await resp.json();
    if (data.success) {
      showStatus("SC2 启动中，日志实时显示...", "info");
      startLogStream();
    } else {
      outputBody.textContent = `错误: ${data.error}`;
      showStatus("启动失败", "error");
      btn.disabled = false; btn.textContent = "启动游戏";
      if (stopBtn) stopBtn.style.display = "none";
    }
  } catch (e) {
    outputBody.textContent = `请求失败: ${e.message}`;
    showStatus("请求失败", "error");
    btn.disabled = false; btn.textContent = "启动游戏";
    if (stopBtn) stopBtn.style.display = "none";
  }
}

function startLogStream() {
  if (logEventSource) logEventSource.close();
  const outputBody = $("output-body");
  logEventSource = new EventSource(API.logStream);

  logEventSource.onmessage = function(event) {
    const line = event.data;
    outputBody.textContent += line + "\n";
    outputBody.scrollTop = outputBody.scrollHeight;

    // 检测完成信号
    if (line.includes("exit=0") || line.includes("SC2 API 已就绪")) {
      showStatus("SC2 启动完成", "success");
      $("launch-btn").disabled = false;
      $("launch-btn").textContent = "启动游戏";
      const stopBtn = $("stop-btn");
      if (stopBtn) stopBtn.style.display = "none";
    } else if (line.includes("exit=") && !line.includes("exit=0")) {
      showStatus("启动失败", "error");
      $("launch-btn").disabled = false;
      $("launch-btn").textContent = "启动游戏";
      const stopBtn = $("stop-btn");
      if (stopBtn) stopBtn.style.display = "none";
      logEventSource.close();
    }
  };

  logEventSource.onerror = function() {
    logEventSource.close();
    $("launch-btn").disabled = false;
    $("launch-btn").textContent = "启动游戏";
    const stopBtn = $("stop-btn");
    if (stopBtn) stopBtn.style.display = "none";
  };
}

function stopLogStream() {
  if (logEventSource) {
    logEventSource.close();
    logEventSource = null;
  }
}

async function stopGame() {
  try {
    const resp = await fetch(API.stop, { method: "POST" });
    const data = await resp.json();
    if (data.success) {
      showStatus("已停止", "info");
      stopLogStream();
      $("launch-btn").disabled = false;
      $("launch-btn").textContent = "启动游戏";
      const stopBtn = $("stop-btn");
      if (stopBtn) stopBtn.style.display = "none";
    }
  } catch (e) {
    showStatus("停止失败: " + e.message, "error");
  }
}

function resetSelection() {
  const c0 = state.commanders.find(c => c.group === "official") || state.commanders[0] || {};
  state.selected = {
    mapName: "亡者之夜.SC2Map",
    mapPackage: "cmre",
    commander: c0.id || "TerranRaynor",
    commanderPackage: c0.packageId || "cmre",
    faction: c0.faction || "",
    commanderBank: c0.bank || "Raynor",
    commanderPortrait: c0.portrait || "ui_commanderportrait_raynor.dds",
    commanderCachedImage: c0.cachedImage || "",
    mode: 1, difficultyBase: 0, difficultyPlus: 0, enemy: "",
    mutators: [], voicePack: "", extraMods: [],
    apiMode: false, listenPort: 5000,
    buffPatch: { enabled: false, buffs: [], masteries: {}, extras: { P1: new Set(), P2: new Set(), P3: new Set() }, _lastCommander: "" },
  };
  syncUI();
  $("mutator-search").value = "";
  renderMaps();
  renderCommanderGrid();
  renderCommanderCard();
  renderMutators();
  loadExtraMods();
  renderBuffPatch();
  updateFooter();
  updateMutatorCount();
  showStatus("已重置");
}

/* === 初始化 === */
function initCollapsible() {
  document.querySelectorAll(".card-head-toggle, .buff-panel-head").forEach(head => {
    head.style.cursor = "pointer";
    head.onclick = () => {
      const targetId = head.dataset.target;
      const body = $(targetId);
      const icon = head.querySelector(".toggle-icon");
      if (body.hidden) { body.hidden = false; if (icon) icon.textContent = "▼"; }
      else { body.hidden = true; if (icon) icon.textContent = "▶"; }
    };
  });
}

function initTabs() {
  $$(".tab-btn").forEach(btn => {
    btn.onclick = () => switchTab(btn.dataset.tab);
  });
}

function initCmdrTabs() {
  document.querySelectorAll(".cmdr-tab").forEach(tab => {
    tab.onclick = () => {
      state.cmdrFilter = tab.dataset.group;
      document.querySelectorAll(".cmdr-tab").forEach(t => t.classList.toggle("active", t === tab));
      renderCommanderGrid();
    };
  });
}

function initPresets() {
  loadPresets();
  renderPresetList();
  $("preset-save").onclick = openPresetModal;
  $("preset-manage").onclick = () => {
    state.presetListOpen = !state.presetListOpen;
    $("preset-list").hidden = !state.presetListOpen;
    if (state.presetListOpen) renderPresetList();
  };
  $("preset-modal-close").onclick = closePresetModal;
  $("preset-modal-cancel").onclick = closePresetModal;
  $("preset-modal-confirm").onclick = confirmSavePreset;
  $("preset-modal").onclick = (e) => { if (e.target === $("preset-modal")) closePresetModal(); };
  $("preset-name-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") confirmSavePreset();
    if (e.key === "Escape") closePresetModal();
  });
}

async function init() {
  $("launch-btn").onclick = launchGame;
  $("reset-btn").onclick = resetSelection;
  $("output-close").onclick = () => { $("output").hidden = true; };
  const stopBtn = $("stop-btn");
  if (stopBtn) stopBtn.onclick = stopGame;

  $("mode").onchange = e => { state.selected.mode = parseInt(e.target.value, 10); updateFooter(); };
  $("difficultyBase").oninput = e => {
    const v = parseInt(e.target.value, 10);
    state.selected.difficultyBase = v;
    $("difficultyBase-value").textContent = v;
    $("difficultyBase-hint").textContent = DIFFICULTY_BASE_NAMES[v] || "Lv" + v;
    updateFooter();
  };
  $("difficultyPlus").oninput = e => {
    const v = parseInt(e.target.value, 10);
    state.selected.difficultyPlus = v;
    $("difficultyPlus-value").textContent = v;
    $("difficultyPlus-hint").textContent = v === 0 ? "无" : "+" + v;
    updateFooter();
  };
  $("mutator-search").oninput = () => renderMutators();
  $("voicePack").onchange = e => { state.selected.voicePack = e.target.value; };
  $("apiMode").onchange = e => {
    state.selected.apiMode = e.target.checked;
    $("api-mode-config").hidden = !e.target.checked;
  };
  $("listenPort").oninput = e => { state.selected.listenPort = parseInt(e.target.value, 10) || 5000; };
  $("buff-enable").onchange = e => {
    state.selected.buffPatch.enabled = e.target.checked;
    updateBuffStatus();
  };

  initCollapsible();
  initTabs();
  initCmdrTabs();
  initPresets();
  initRuntimeConsole();

  try {
    await Promise.all([loadFactors(), loadMaps(), loadCommanders(), loadMutators(), loadVoicePacks(), loadBuffMetadata()]);
    syncUI();
    updateMutatorCount();
    showStatus("就绪", "success");
    updateFooter();
  } catch (e) {
    showStatus(`加载失败: ${e.message}`, "error");
  }
}

init();
