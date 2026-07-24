"use strict";

// CMRE 亡者之夜 WebUI 前端逻辑

const els = {
  form: document.getElementById("launch-form"),
  commander: document.getElementById("commander"),
  mode: document.getElementById("mode"),
  modeHint: document.getElementById("mode-hint"),
  difficultyBase: document.getElementById("difficultyBase"),
  difficultyBaseValue: document.getElementById("difficultyBase-value"),
  difficultyBaseHint: document.getElementById("difficultyBase-hint"),
  difficultyPlus: document.getElementById("difficultyPlus"),
  difficultyPlusValue: document.getElementById("difficultyPlus-value"),
  difficultyPlusHint: document.getElementById("difficultyPlus-hint"),
  enemy: document.getElementById("enemy"),
  enemyHint: document.getElementById("enemy-hint"),
  mutatorSearch: document.getElementById("mutator-search"),
  mutatorList: document.getElementById("mutator-list"),
  mutatorLoading: document.getElementById("mutator-loading"),
  mutatorCount: document.getElementById("mutator-count"),
  launchBtn: document.getElementById("launch-btn"),
  resetBtn: document.getElementById("reset-btn"),
  status: document.getElementById("status"),
  output: document.getElementById("output"),
  outputTitle: document.getElementById("output-title"),
  outputBody: document.getElementById("output-body"),
  outputClose: document.getElementById("output-close"),
};

let factorsData = null;
let mutatorsData = [];
let selectedMutators = new Map(); // id -> { id, enhanced }

async function fetchJson(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
  return resp.json();
}

function setStatus(type, text) {
  els.status.hidden = false;
  els.status.className = `status ${type}`;
  els.status.textContent = text;
}

function clearStatus() {
  els.status.hidden = true;
  els.status.textContent = "";
}

function renderOptions(select, items, valueKey, labelKey, descKey, hintEl) {
  select.innerHTML = "";
  items.forEach((item) => {
    const opt = document.createElement("option");
    opt.value = item[valueKey];
    opt.textContent = item[labelKey];
    select.appendChild(opt);
  });
  if (hintEl && items.length > 0) {
    const updateHint = () => {
      const cur = items.find((i) => String(i[valueKey]) === select.value);
      hintEl.textContent = cur && cur[descKey] ? cur[descKey] : "";
    };
    updateHint();
    select.addEventListener("change", updateHint);
  }
}

function renderFactors(data) {
  // 指挥官
  els.commander.innerHTML = "";
  data.commanders.forEach((cmd) => {
    const opt = document.createElement("option");
    opt.value = cmd;
    opt.textContent = cmd;
    els.commander.appendChild(opt);
  });

  // 模式
  renderOptions(els.mode, data.modes, "id", "name", "description", els.modeHint);

  // 基础难度
  const db = data.difficultyBase;
  els.difficultyBase.min = db.min;
  els.difficultyBase.max = db.max;
  els.difficultyBase.value = db.default;
  els.difficultyBaseValue.textContent = db.default;
  els.difficultyBaseHint.textContent = `范围 ${db.min}-${db.max} · ${db.name}`;

  // 残酷+等级
  const dp = data.difficultyPlus;
  els.difficultyPlus.min = dp.min;
  els.difficultyPlus.max = dp.max;
  els.difficultyPlus.value = dp.default;
  els.difficultyPlusValue.textContent = dp.default;
  els.difficultyPlusHint.textContent = `范围 ${dp.min}-${dp.max} · ${dp.name}`;

  // 敌方阵营
  renderOptions(els.enemy, data.enemies, "id", "name", "description", els.enemyHint);
}

function renderMutatorItem(mut) {
  const isSelected = selectedMutators.has(mut.id);
  const item = document.createElement("label");
  item.className = `mutator-item${isSelected ? " selected" : ""}`;
  item.setAttribute("role", "listitem");

  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = isSelected;
  checkbox.addEventListener("change", () => {
    if (checkbox.checked) {
      selectedMutators.set(mut.id, { id: mut.id, enhanced: false });
    } else {
      selectedMutators.delete(mut.id);
    }
    updateMutatorCount();
    // 切换样式 + 刷新 enhanced 可见性
    item.classList.toggle("selected", checkbox.checked);
    enhancedWrap.style.display = checkbox.checked ? "flex" : "none";
    if (!checkbox.checked) {
      enhancedCheckbox.checked = false;
    }
  });

  const info = document.createElement("div");
  info.className = "mutator-info";

  const name = document.createElement("span");
  name.className = "mutator-name";
  name.textContent = mut.name || mut.id;

  const idTag = document.createElement("span");
  idTag.className = "mutator-id";
  idTag.textContent = mut.id;

  const desc = document.createElement("span");
  desc.className = "mutator-desc";
  desc.textContent = mut.description || "";

  info.appendChild(name);
  info.appendChild(idTag);
  if (mut.description) info.appendChild(desc);

  // 强化开关
  const enhancedWrap = document.createElement("label");
  enhancedWrap.className = "enhanced-toggle";
  enhancedWrap.style.display = isSelected ? "flex" : "none";
  const enhancedCheckbox = document.createElement("input");
  enhancedCheckbox.type = "checkbox";
  enhancedCheckbox.checked = isSelected ? selectedMutators.get(mut.id).enhanced : false;
  enhancedCheckbox.addEventListener("change", (e) => {
    e.stopPropagation();
    if (selectedMutators.has(mut.id)) {
      selectedMutators.get(mut.id).enhanced = enhancedCheckbox.checked;
    }
  });
  enhancedWrap.appendChild(enhancedCheckbox);
  enhancedWrap.appendChild(document.createTextNode("强化"));

  item.appendChild(checkbox);
  item.appendChild(info);
  item.appendChild(enhancedWrap);
  return item;
}

function renderMutators(list) {
  els.mutatorList.innerHTML = "";
  if (!list || list.length === 0) {
    const empty = document.createElement("p");
    empty.className = "mutator-empty hint";
    empty.textContent = "没有匹配的突变因子";
    els.mutatorList.appendChild(empty);
    return;
  }
  list.forEach((mut) => {
    els.mutatorList.appendChild(renderMutatorItem(mut));
  });
}

function filterMutators() {
  const q = els.mutatorSearch.value.trim().toLowerCase();
  if (!q) return mutatorsData;
  return mutatorsData.filter((m) => {
    const name = (m.name || "").toLowerCase();
    const id = (m.id || "").toLowerCase();
    const desc = (m.description || "").toLowerCase();
    return name.includes(q) || id.includes(q) || desc.includes(q);
  });
}

function refreshMutatorList() {
  renderMutators(filterMutators());
}

function updateMutatorCount() {
  els.mutatorCount.textContent = String(selectedMutators.size);
}

function showOutput(success, title, body) {
  els.output.hidden = false;
  els.output.className = `output-card ${success ? "success" : "error"}`;
  els.outputTitle.textContent = title;
  els.outputBody.textContent = body || "";
}

async function loadAll() {
  try {
    const [factors, mutators] = await Promise.all([
      fetchJson("/api/factors"),
      fetchJson("/api/mutators"),
    ]);
    factorsData = factors;
    mutatorsData = Array.isArray(mutators) ? mutators : [];
    renderFactors(factors);
    renderMutators(mutatorsData);
    if (els.mutatorLoading) els.mutatorLoading.remove();
  } catch (err) {
    setStatus("error", `加载失败: ${err.message}`);
    if (els.mutatorLoading) {
      els.mutatorLoading.textContent = `加载突变因子失败: ${err.message}`;
    }
  }
}

async function handleLaunch(e) {
  e.preventDefault();
  if (!factorsData) {
    setStatus("error", "因子数据未加载完成");
    return;
  }

  const payload = {
    commander: els.commander.value,
    mapName: "亡者之夜.SC2Map",
    mode: parseInt(els.mode.value, 10),
    difficultyBase: parseInt(els.difficultyBase.value, 10),
    difficultyPlus: parseInt(els.difficultyPlus.value, 10),
    enemy: els.enemy.value,
    mutators: Array.from(selectedMutators.values()),
  };

  els.launchBtn.disabled = true;
  const originalText = els.launchBtn.textContent;
  els.launchBtn.textContent = "启动中...";
  setStatus("loading", "正在调用启动脚本，请稍候（最多 300s）...");

  try {
    const resp = await fetch("/api/launch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();

    if (data.success) {
      setStatus("success", data.message || "SC2 已启动");
      const lines = [];
      lines.push(`指挥官: ${payload.commander}`);
      lines.push(`模式: ${payload.mode}  基础难度: ${payload.difficultyBase}  残酷+: ${payload.difficultyPlus}`);
      lines.push(`敌方: ${payload.enemy || "(默认)"}`);
      lines.push(`突变因子: ${payload.mutators.length} 个`);
      payload.mutators.forEach((m) => {
        lines.push(`  - ${m.id}${m.enhanced ? " (强化)" : ""}`);
      });
      if (data.output) {
        lines.push("");
        lines.push("--- 启动脚本输出 ---");
        lines.push(data.output);
      }
      showOutput(true, "启动成功", lines.join("\n"));
    } else {
      setStatus("error", data.error || "启动失败");
      const lines = [];
      lines.push(`错误: ${data.error || "未知错误"}`);
      if (data.output) {
        lines.push("");
        lines.push("--- stdout ---");
        lines.push(data.output);
      }
      if (data.stderr) {
        lines.push("");
        lines.push("--- stderr ---");
        lines.push(data.stderr);
      }
      showOutput(false, "启动失败", lines.join("\n"));
    }
  } catch (err) {
    setStatus("error", `请求失败: ${err.message}`);
    showOutput(false, "请求失败", String(err.message));
  } finally {
    els.launchBtn.disabled = false;
    els.launchBtn.textContent = originalText;
  }
}

function handleReset() {
  els.form.reset();
  selectedMutators.clear();
  if (factorsData) {
    els.difficultyBase.value = factorsData.difficultyBase.default;
    els.difficultyPlus.value = factorsData.difficultyPlus.default;
    els.difficultyBaseValue.textContent = factorsData.difficultyBase.default;
    els.difficultyPlusValue.textContent = factorsData.difficultyPlus.default;
  }
  els.mutatorSearch.value = "";
  refreshMutatorList();
  updateMutatorCount();
  clearStatus();
  els.output.hidden = true;
}

function bindEvents() {
  els.difficultyBase.addEventListener("input", () => {
    els.difficultyBaseValue.textContent = els.difficultyBase.value;
  });
  els.difficultyPlus.addEventListener("input", () => {
    els.difficultyPlusValue.textContent = els.difficultyPlus.value;
  });
  els.mutatorSearch.addEventListener("input", refreshMutatorList);
  els.form.addEventListener("submit", handleLaunch);
  els.resetBtn.addEventListener("click", handleReset);
  els.outputClose.addEventListener("click", () => {
    els.output.hidden = true;
  });
}

document.addEventListener("DOMContentLoaded", () => {
  bindEvents();
  loadAll();
});
