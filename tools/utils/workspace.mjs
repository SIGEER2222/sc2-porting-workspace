import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, "..", "..");
const configPath = join(repoRoot, "src", "config", "workspace.json");
const localSourcesPath = join(repoRoot, "src", "config", "local.sources.json");

async function readJson(path) {
  return JSON.parse(await readFile(path, "utf8"));
}

async function loadConfig() {
  return readJson(configPath);
}

async function loadLocalSources() {
  if (!existsSync(localSourcesPath)) return { schemaVersion: 1, bindings: {} };
  return readJson(localSourcesPath);
}

function resolveRegisteredPath(entry, localSources) {
  if (entry.path) return resolve(repoRoot, entry.path);
  const localPath = localSources.bindings?.[entry.id];
  return localPath ? resolve(localPath) : null;
}

async function validate() {
  const errors = [];
  const warnings = [];
  let config;
  let localSources;
  try {
    config = await loadConfig();
    localSources = await loadLocalSources();
  } catch (error) {
    errors.push("Cannot parse workspace configuration: " + error.message);
    return { ok: false, errors, warnings };
  }

  if (config.schemaVersion !== 1) errors.push("workspace schemaVersion must be 1");
  if (localSources.schemaVersion !== 1) errors.push("local source schemaVersion must be 1");
  const ids = new Set();
  for (const entry of [...(config.tools ?? []), ...(config.sources ?? [])]) {
    if (!entry.id || (!entry.path && !entry.localBinding)) {
      errors.push("Every tool and source requires id plus path or localBinding");
      continue;
    }
    if (ids.has(entry.id)) errors.push("Duplicate registered id: " + entry.id);
    ids.add(entry.id);
    const resolvedPath = resolveRegisteredPath(entry, localSources);
    if (!resolvedPath) {
      warnings.push("Local source is not bound: " + entry.id);
    } else if (!existsSync(resolvedPath)) {
      warnings.push("Registered path is missing: " + entry.id + " -> " + resolvedPath);
    }
  }

  const requiredFiles = [
    "AGENTS.md",
    "docs/architecture.md",
    "docs/workflow.md",
    "docs/schemas/project.schema.json",
    "docs/schemas/stage-result.schema.json",
    "docs/schemas/dependency-graph.schema.json",
    "docs/schemas/package-manifest.schema.json",
    "docs/schemas/composition-manifest.schema.json",
    "docs/schemas/static-analysis-request.schema.json",
    "docs/schemas/runtime-scenario.schema.json",
    "docs/schemas/runtime-verdict.schema.json",
    "src/templates/project/project.json",
    "src/templates/stage/plan.md",
    "src/templates/stage/log.md",
    "src/templates/stage/result.json",
    "src/templates/stage/issues.json",
    "src/config/local.sources.example.json"
  ];
  for (const path of requiredFiles) {
    if (!existsSync(join(repoRoot, path))) errors.push("Required workspace file is missing: " + path);
  }

  for (const path of [
    "docs/schemas/project.schema.json",
    "docs/schemas/stage-result.schema.json",
    "docs/schemas/dependency-graph.schema.json",
    "docs/schemas/package-manifest.schema.json",
    "docs/schemas/composition-manifest.schema.json",
    "docs/schemas/static-analysis-request.schema.json",
    "docs/schemas/runtime-scenario.schema.json",
    "docs/schemas/runtime-verdict.schema.json",
    "src/templates/project/project.json",
    "src/templates/stage/result.json",
    "src/templates/stage/issues.json"
  ]) {
    try {
      await readJson(join(repoRoot, path));
    } catch (error) {
      errors.push("Invalid JSON in " + path + ": " + error.message);
    }
  }

  const skillRoot = join(repoRoot, "tools", ".codex", "skills");
  const requiredSkills = [
    "sc2-static-analysis",
    "sc2-runtime-analysis",
    "sc2-adapter-design",
    "sc2-ai-development-loop",
    "sc2-editor-knowledge",
    "sc2-blizzard-tutorials"
  ];
  for (const skill of requiredSkills) {
    const skillPath = join(skillRoot, skill, "SKILL.md");
    if (!existsSync(skillPath)) {
      errors.push("Required skill is missing: " + skill);
      continue;
    }
    const contents = await readFile(skillPath, "utf8");
    if (contents.includes("[TODO:")) errors.push("Skill still contains TODO markers: " + skill);
  }

  return { ok: errors.length === 0, errors, warnings };
}

async function status() {
  const config = await loadConfig();
  const localSources = await loadLocalSources();
  const result = await validate();
  const tools = (config.tools ?? []).map((tool) => ({
    id: tool.id,
    kind: tool.kind,
    exists: Boolean(resolveRegisteredPath(tool, localSources) && existsSync(resolveRegisteredPath(tool, localSources))),
    capabilities: tool.capabilities
  }));
  const sources = (config.sources ?? []).map((source) => ({
    id: source.id,
    kind: source.kind,
    bound: Boolean(resolveRegisteredPath(source, localSources)),
    exists: Boolean(resolveRegisteredPath(source, localSources) && existsSync(resolveRegisteredPath(source, localSources))),
    writePolicy: source.writePolicy
  }));
  console.log(JSON.stringify({ validation: result, tools, sources }, null, 2));
  process.exitCode = result.ok ? 0 : 1;
}

async function resolveId(id) {
  const config = await loadConfig();
  const localSources = await loadLocalSources();
  const entry = [...(config.tools ?? []), ...(config.sources ?? [])].find((candidate) => candidate.id === id);
  if (!entry) throw new Error("Unknown registered id: " + id);
  const resolvedPath = resolveRegisteredPath(entry, localSources);
  if (!resolvedPath) throw new Error("Registered id requires a local binding: " + id);
  console.log(resolvedPath);
}

async function bindSource(id, path) {
  const config = await loadConfig();
  const source = (config.sources ?? []).find((candidate) => candidate.id === id);
  if (!source) throw new Error("Unknown source id: " + id);
  if (!source.localBinding) throw new Error("Source does not use a local binding: " + id);
  if (!path) throw new Error("bind-source requires a local path");
  const resolvedPath = resolve(path);
  if (!existsSync(resolvedPath)) throw new Error("Local source path is missing: " + resolvedPath);
  const localSources = await loadLocalSources();
  localSources.schemaVersion = 1;
  localSources.bindings ??= {};
  localSources.bindings[id] = resolvedPath;
  await writeFile(localSourcesPath, JSON.stringify(localSources, null, 2) + "\n", "utf8");
  console.log(resolvedPath);
}

async function initProject(id) {
  if (!/^[a-z0-9][a-z0-9-]*$/.test(id ?? "")) throw new Error("Project id must use lowercase letters, digits, and hyphens");
  const projectDir = join(repoRoot, "src", "projects", id);
  if (existsSync(projectDir)) throw new Error("Project already exists: " + id);
  const stageDir = join(projectDir, "stages", "01-discovery");
  await mkdir(join(stageDir, "evidence"), { recursive: true });
  await copyFile(join(repoRoot, "src", "templates", "project", "project.json"), join(projectDir, "project.json"));
  for (const file of ["plan.md", "log.md", "result.json", "issues.json"]) {
    await copyFile(join(repoRoot, "src", "templates", "stage", file), join(stageDir, file));
  }
  const projectPath = join(projectDir, "project.json");
  const project = await readJson(projectPath);
  project.id = id;
  await writeFile(projectPath, JSON.stringify(project, null, 2) + "\n", "utf8");
  console.log(projectDir);
}

// 包装 spawn 为 Promise，stdout/stderr 透传到当前进程
function runTool(cmd, args, options = {}) {
  return new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(cmd, args, { stdio: "inherit", shell: false, ...options });
    child.on("error", rejectPromise);
    child.on("close", (code) => {
      if (code === 0) resolvePromise(0);
      else rejectPromise(new Error(`${cmd} exited with code ${code}`));
    });
  });
}

// galaxy-lint 子命令：调用 sc2-galaxy-lang 做语法/类型诊断
async function lintCommand(path, options) {
  if (!path) throw new Error("lint 需要目标路径。用法: workspace.mjs lint <path> [--out <file>] [--format json|text] [--no-type-check]");
  const lintScript = join(scriptDir, "..", "analysis", "galaxy-lint.mjs");
  if (!existsSync(lintScript)) throw new Error("galaxy-lint.mjs 不存在: " + lintScript);
  const args = [lintScript, path];
  if (options.out) args.push("--out", options.out);
  if (options.format) args.push("--format", options.format);
  if (options.noTypeCheck) args.push("--no-type-check");
  try {
    await runTool("node", args);
  } catch (e) {
    // galaxy-lint 发现 error 时退出码 1，这是正常诊断结果，不是工具故障
    if (/exited with code 1$/.test(e.message)) {
      process.exitCode = 1;
    } else {
      throw e;
    }
  }
}

// observe 子命令：启动 SC2 运行时观察器
async function observeCommand(options) {
  if (!options.port) throw new Error("observe 需要 --port。用法: workspace.mjs observe --port <n> [--duration <s>] [--scenario <file>] [--out-dir <dir>]");
  const observerScript = join(scriptDir, "..", "runtime-bridge", "sc2-observer.py");
  if (!existsSync(observerScript)) throw new Error("sc2-observer.py 不存在: " + observerScript);
  const args = [observerScript, "--port", String(options.port)];
  if (options.duration != null) args.push("--duration", String(options.duration));
  if (options.scenario) args.push("--scenario", options.scenario);
  if (options.outDir) args.push("--out-dir", options.outDir);
  await runTool("python", args);
}

// search 子命令：查询 SC2 编辑器知识库
async function searchCommand(query, options) {
  if (!query) throw new Error("search 需要查询语句。用法: workspace.mjs search \"<question>\" [--top-k <n>]");
  const kbScript = join(scriptDir, "..", "kb", "kb-query.py");
  if (!existsSync(kbScript)) throw new Error("kb-query.py 不存在: " + kbScript);
  const args = [kbScript];
  if (options.topK) args.push("--top-k", String(options.topK));
  if (options.allowStale) args.push("--allow-stale");
  args.push(query);
  await runTool("python", args);
}

// 解析 --key value 形式的选项
function parseOptions(argv) {
  const opts = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) {
      const key = a.slice(2).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      const next = argv[i + 1];
      if (next && !next.startsWith("--")) {
        opts[key] = next;
        i++;
      } else {
        opts[key] = true;
      }
    }
  }
  return opts;
}

const [command = "validate", argument, value] = process.argv.slice(2);
if (command === "validate") {
  const result = await validate();
  console.log(JSON.stringify(result, null, 2));
  process.exitCode = result.ok ? 0 : 1;
} else if (command === "status") {
  await status();
} else if (command === "resolve") {
  await resolveId(argument);
} else if (command === "bind-source") {
  await bindSource(argument, value);
} else if (command === "init-project") {
  await initProject(argument);
} else if (command === "lint") {
  // workspace.mjs lint <path> [--out <file>] [--format json|text] [--no-type-check]
  const opts = parseOptions(process.argv.slice(3));
  await lintCommand(argument, opts);
} else if (command === "observe") {
  // workspace.mjs observe --port <n> [--duration <s>] [--scenario <file>] [--out-dir <dir>]
  const opts = parseOptions(process.argv.slice(3));
  await observeCommand(opts);
} else if (command === "search") {
  // workspace.mjs search "<question>" [--top-k <n>]
  const opts = parseOptions(process.argv.slice(3));
  await searchCommand(argument, opts);
} else {
  throw new Error("Unknown command: " + command);
}
