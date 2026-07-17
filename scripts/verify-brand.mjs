import { readFile, readdir } from "node:fs/promises";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const publicRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const workspaceRoot = resolve(publicRoot, "..");
const verifierPath = fileURLToPath(import.meta.url);
const excludedDirectories = new Set([
  ".agent-runtime",
  ".agents",
  ".framework-peers",
  ".git",
  ".mypy_cache",
  ".ruff_cache",
  ".venv-frameworks",
  "__pycache__",
  "build",
  "dist",
  "node_modules",
]);
const legacyPatterns = [
  /@agentruntime/iu,
  /\bagentruntime(?:_(?:premium|enterprise))?\b/iu,
  /\bAGENT_RUNTIME_/u,
  /\bAgent Runtime\b/u,
  /(?<!\.)\bagent-runtime\b/iu,
  /@causentra-premium/iu,
  /\bcausentra[_-]premium\b/iu,
  /\bpremium\b/iu,
];

async function* sourceFiles(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (!excludedDirectories.has(entry.name) && !entry.name.endsWith(".egg-info")) {
        yield* sourceFiles(join(directory, entry.name));
      }
      continue;
    }
    if (entry.isFile()) yield join(directory, entry.name);
  }
}

const violations = [];
for await (const path of sourceFiles(workspaceRoot)) {
  if (path === verifierPath) continue;
  const content = await readFile(path);
  if (content.includes(0)) continue;
  const text = content.toString("utf8");
  for (const pattern of legacyPatterns) {
    if (pattern.test(text)) {
      violations.push(`${relative(workspaceRoot, path)} contains ${String(pattern)}`);
    }
  }
}

if (violations.length > 0) {
  throw new Error(`Legacy brand contract violations:\n${violations.join("\n")}`);
}

console.log("Causentra brand contract verified across public and enterprise source.");
