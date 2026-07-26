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
  asset: (relPath) => `/api/assets/dds?path=${encodeURIComponent(relPath)}`,
};

const PRESET_KEY = "cmre_presets_v1";

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
    commander: "TerranRaynor",
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
    buffPatch: {
      enabled: false,
      buffs: [],
      masteries: {},
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
    commander: s.commander,
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
  const parts = [];
  parts.push(s.mapName.replace(/\.SC2Map$/, ""));
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
  state.maps = data.maps || [];
  renderMaps();
}

async function loadCommanders() {
  const data = await fetch(API.factors).then(r => r.json());
  state.commanders = data.commanders || [];
  if (state.commanders.length > 0 && !state.commanders.find(c => c.id === state.selected.commander)) {
    const c = state.commanders[0];
    state.selected.commander = c.id;
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
    state.selected.buffPatch._lastCommander = cid;
  }

  panel.hidden = false;
  enableCk.disabled = false;
  enableCk.checked = state.selected.buffPatch.enabled;

  // 更新面板状态文字
  let statusText = cmdr.display_name;
  if (state.selected.buffPatch.enabled) {
    const n = state.selected.buffPatch.buffs.length;
    if (n > 0) {
      statusText += ` · ${n} 个威望优点已选`;
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
    html += `
      <label class="buff-prestige-row">
        <input type="checkbox" class="buff-prestige-ck" data-token="${token}" ${checked}>
        <div class="buff-prestige-info">
          <div class="buff-prestige-name">P${p.slot} · ${esc(p.name)} ${reviewBadge}</div>
          <div class="buff-prestige-adv"><span class="buff-tag buff-tag-adv">优点</span> ${esc(p.advantage_text || '(无说明)')}</div>
          <div class="buff-prestige-dis"><span class="buff-tag buff-tag-dis">原缺点</span> ${esc(p.disadvantage_text || '(无)')}</div>
          ${p.bonus_upgrade_id ? `<div class="buff-prestige-upgrade">↑ ${esc(p.bonus_upgrade_id)}</div>` : ''}
        </div>
      </label>`;
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
      if (ck.checked) set.add(token); else set.delete(token);
      state.selected.buffPatch.buffs = Array.from(set).sort();
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
    if (n > 0) {
      text += ` · ${n} 个威望优点已选`;
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
    const mapLabel = (p.mapName || "").replace(/\.SC2Map$/, "");
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
async function launchGame() {
  const s = state.selected;
  const btn = $("launch-btn");
  btn.disabled = true; btn.textContent = "启动中...";
  showStatus("正在启动 SC2...", "info");

  const body = {
    commander: s.commander, mapName: s.mapName, mode: s.mode,
    difficultyBase: s.difficultyBase, difficultyPlus: s.difficultyPlus,
    enemy: s.enemy, mutators: s.mutators,
    voicePack: s.voicePack, extraMods: s.extraMods,
  };
  if (s.apiMode) { body.listenPort = s.listenPort; body.apiMinimal = true; }
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
  }

  const output = $("output");
  const outputBody = $("output-body");
  output.hidden = false;
  outputBody.textContent = "正在调用启动脚本...";

  try {
    const resp = await fetch(API.launch, { method: "POST", headers: { "Content-Type": "application/json; charset=utf-8" }, body: JSON.stringify(body) });
    const data = await resp.json();
    if (data.success) {
      outputBody.textContent = data.message + (data.output ? "\n\n" + data.output : "");
      showStatus("SC2 已启动", "success");
    } else {
      outputBody.textContent = `错误: ${data.error}\n\n${data.output || ""}${data.stderr ? "\n\nSTDERR:\n" + data.stderr : ""}`;
      showStatus("启动失败", "error");
    }
  } catch (e) {
    outputBody.textContent = `请求失败: ${e.message}`;
    showStatus("请求失败", "error");
  } finally {
    btn.disabled = false; btn.textContent = "启动游戏";
  }
}

function resetSelection() {
  const c0 = state.commanders.find(c => c.group === "official") || state.commanders[0] || {};
  state.selected = {
    mapName: "亡者之夜.SC2Map",
    commander: c0.id || "TerranRaynor",
    commanderBank: c0.bank || "Raynor",
    commanderPortrait: c0.portrait || "ui_commanderportrait_raynor.dds",
    commanderCachedImage: c0.cachedImage || "",
    mode: 1, difficultyBase: 0, difficultyPlus: 0, enemy: "",
    mutators: [], voicePack: "", extraMods: [],
    apiMode: false, listenPort: 5000,
    buffPatch: { enabled: false, buffs: [], masteries: {}, _lastCommander: "" },
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
