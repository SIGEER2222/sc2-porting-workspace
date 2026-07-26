import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, "..", "..");

async function readJson(path) {
  return JSON.parse(await readFile(path, "utf8"));
}

function validateType(value, typeDef, path) {
  if (typeDef === "string" && typeof value !== "string") return `Expected string at ${path}`;
  if (typeDef === "integer" && (!Number.isInteger(value) || typeof value !== "number")) return `Expected integer at ${path}`;
  if (typeDef === "boolean" && typeof value !== "boolean") return `Expected boolean at ${path}`;
  if (typeDef === "object" && (typeof value !== "object" || value === null || Array.isArray(value))) return `Expected object at ${path}`;
  if (typeDef === "array" && !Array.isArray(value)) return `Expected array at ${path}`;
  return null;
}

function validateEnum(value, enumValues, path) {
  if (!enumValues.includes(value)) return `Invalid value at ${path}: ${JSON.stringify(value)} must be one of ${JSON.stringify(enumValues)}`;
  return null;
}

function validateRequired(obj, required, path) {
  const missing = required.filter((prop) => !(prop in obj));
  if (missing.length > 0) return `Missing required properties at ${path}: ${missing.join(", ")}`;
  return null;
}

function validateAdditionalProperties(obj, additionalProps, path) {
  if (!additionalProps) {
    const extra = Object.keys(obj).filter((key) => key.startsWith("$"));
    if (extra.length > 0) return `Unexpected additional properties at ${path}: ${extra.join(", ")}`;
  }
  return null;
}

function validateSchema(obj, schema, path = "") {
  const errors = [];

  if (schema.required) {
    const err = validateRequired(obj, schema.required, path);
    if (err) errors.push(err);
  }

  if (schema.properties) {
    for (const [key, propSchema] of Object.entries(schema.properties)) {
      const value = obj[key];
      const propPath = path ? `${path}.${key}` : key;

      if (propSchema.const !== undefined && value !== propSchema.const) {
        errors.push(`Expected constant ${propSchema.const} at ${propPath}, got ${JSON.stringify(value)}`);
        continue;
      }

      if (value !== undefined) {
        if (propSchema.type) {
          const err = validateType(value, propSchema.type, propPath);
          if (err) errors.push(err);
        }

        if (propSchema.enum) {
          const err = validateEnum(value, propSchema.enum, propPath);
          if (err) errors.push(err);
        }

        if (propSchema.type === "array" && propSchema.items) {
          for (let i = 0; i < value.length; i++) {
            errors.push(...validateSchema(value[i], propSchema.items, `${propPath}[${i}]`));
          }
        }

        if (propSchema.type === "object" && propSchema.properties) {
          errors.push(...validateSchema(value, propSchema, propPath));
        }
      }
    }
  }

  if (schema.additionalProperties === false) {
    const err = validateAdditionalProperties(obj, false, path);
    if (err) errors.push(err);
  }

  return errors;
}

async function validateFile(dataPath, schemaPath) {
  const data = await readJson(resolve(repoRoot, dataPath));
  const schema = await readJson(resolve(repoRoot, schemaPath));
  const errors = validateSchema(data, schema);

  if (errors.length === 0) {
    console.log(`✓ ${dataPath} passes ${schemaPath}`);
    return { valid: true, errors: [] };
  } else {
    console.log(`✗ ${dataPath} fails ${schemaPath}:`);
    for (const err of errors) console.log(`  - ${err}`);
    return { valid: false, errors };
  }
}

async function main() {
  const args = process.argv.slice(2);
  if (args.length < 2) {
    throw new Error("Usage: node tools/analysis/validate-schema.mjs <data.json> <schema.json> [<data2.json> <schema2.json> ...]");
  }

  if (args.length % 2 !== 0) {
    throw new Error("Arguments must be pairs of <data.json> <schema.json>");
  }

  let allValid = true;
  for (let i = 0; i < args.length; i += 2) {
    const result = await validateFile(args[i], args[i + 1]);
    if (!result.valid) allValid = false;
  }

  process.exitCode = allValid ? 0 : 1;
}

main().catch((e) => {
  console.error("validate-schema failed: " + e.message);
  process.exitCode = 2;
});