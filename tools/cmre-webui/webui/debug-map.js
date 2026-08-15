const state = { mods: [], selected: new Set() };
const $ = (id) => document.getElementById(id);

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
}

async function getJson(url) {
  const response = await fetch(url);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function setBadge(text, className = "idle") {
  $("runtime-badge").textContent = text;
  $("runtime-badge").className = `badge ${className}`;
}

function renderMap(data) {
  $("map-meta").textContent = `${data.mapName}\n${data.sourceKind === "archive" ? "原始压缩包" : "已解包目录"} · ${data.fileCount} 个文件\nSHA-256 ${data.sha256 || "目录输入不计算"}`;
  const list = $("map-dependencies");
  list.innerHTML = data.dependencies.length
    ? data.dependencies.map((item) => `<li>${esc(item.raw)}</li>`).join("")
    : "<li>无显式依赖</li>";
}

function renderMods() {
  $("mod-count").textContent = `${state.mods.length} 个可用`;
  const list = $("mods");
  if (!state.mods.length) {
    list.textContent = "没有可用 Mod。请用 --sc2-root 或 SC2_ROOT 启动。";
    return;
  }
  list.innerHTML = state.mods.map((mod) => `
    <label class="mod-item">
      <input type="checkbox" data-mod="${esc(mod.id)}" ${state.selected.has(mod.id) ? "checked" : ""}>
      <span><span class="mod-name">${esc(mod.name)}</span><span class="mod-path">${esc(mod.runtimePath)}</span></span>
    </label>`).join("");
  list.querySelectorAll("input[data-mod]").forEach((input) => {
    input.addEventListener("change", () => {
      if (input.checked) state.selected.add(input.dataset.mod);
      else state.selected.delete(input.dataset.mod);
    });
  });
}

async function refresh() {
  try {
    const [manifest, catalog] = await Promise.all([getJson("/api/manifest"), getJson("/api/mods")]);
    state.mods = catalog.mods || [];
    renderMap(manifest);
    renderMods();
    setBadge("就绪", "ready");
  } catch (error) {
    setBadge("读取失败", "error");
    $("log").textContent = error.message;
  }
}

async function submit(endpoint) {
  const body = { mods: [...state.selected] };
  if (endpoint === "/api/launch") {
    body.port = Number($("port").value);
    body.verify = $("verify").value.trim();
  }
  $("log").textContent = "处理中…";
  try {
    const response = await fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
    const session = data.session || data.status;
    $("session-id").textContent = session.sessionId || "已提交";
    $("log").textContent = JSON.stringify(session, null, 2);
    setBadge(endpoint === "/api/launch" ? "已提交" : "Shim 已生成", "ready");
  } catch (error) {
    setBadge("操作失败", "error");
    $("log").textContent = error.message;
  }
}

$("refresh").onclick = refresh;
$("prepare").onclick = () => submit("/api/prepare");
$("launch").onclick = () => submit("/api/launch");
refresh();
