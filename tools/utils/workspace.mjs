import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

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
  for (const skill of ["sc2-static-analysis", "sc2-runtime-analysis", "sc2-adapter-design", "sc2-ai-development-loop"]) {
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
} else {
  throw new Error("Unknown command: " + command);
}
