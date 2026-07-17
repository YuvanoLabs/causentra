import { access, readFile, readdir } from "node:fs/promises";
import { extname, join } from "node:path";

const root = new URL("../", import.meta.url);
const requiredFiles = [
  "CITATION.cff",
  "llms.txt",
  "docs/30-discoverability-and-search.md",
  "docs/31-product-faq.md",
];

for (const file of requiredFiles) await access(new URL(file, root));

const readme = await readFile(new URL("README.md", root), "utf8");
for (const phrase of [
  "multi-agent observability",
  "AI agent observability",
  "OpenTelemetry",
  "Status: public source release candidate",
]) {
  if (!readme.includes(phrase)) throw new Error(`README is missing discovery phrase: ${phrase}`);
}

const strategy = await readFile(new URL("docs/30-discoverability-and-search.md", root), "utf8");
if (!strategy.includes("no file, keyword list, or submission can guarantee first position")) {
  throw new Error("Discoverability strategy must reject ranking guarantees");
}

const llms = await readFile(new URL("llms.txt", root), "utf8");
for (const match of llms.matchAll(/\[[^\]]+\]\(([^)]+)\)/gu)) {
  const target = match[1]?.trim() ?? "";
  if (/^(?:https?:|mailto:|#)/u.test(target)) continue;
  await access(new URL(target, root));
}

const citation = await readFile(new URL("CITATION.cff", root), "utf8");
for (const field of ["cff-version: 1.2.0", 'title: "Causentra"', "license: Apache-2.0"]) {
  if (!citation.includes(field)) throw new Error(`CITATION.cff is missing ${field}`);
}

for (const manifestPath of await manifests("packages", "apps")) {
  const manifest = JSON.parse(await readFile(new URL(manifestPath, root), "utf8"));
  if (typeof manifest.description !== "string" || manifest.description.length < 30) {
    throw new Error(`${manifestPath} needs a descriptive package summary`);
  }
  if (!Array.isArray(manifest.keywords) || manifest.keywords.length < 5) {
    throw new Error(`${manifestPath} needs at least five accurate search keywords`);
  }
}

const pythonProject = await readFile(new URL("python/pyproject.toml", root), "utf8");
for (const keyword of ["agent-observability", "multi-agent", "opentelemetry", "otlp"]) {
  if (!pythonProject.includes(`"${keyword}"`)) {
    throw new Error(`Python package metadata is missing keyword: ${keyword}`);
  }
}

for (const workflow of await files(".github/workflows")) {
  if (![".yml", ".yaml"].includes(extname(workflow))) continue;
  const source = await readFile(new URL(workflow, root), "utf8");
  for (const match of source.matchAll(/^\s*-\s+uses:\s+([^\s#]+)(?:\s+#\s+([^\r\n]+))?/gmu)) {
    const reference = match[1] ?? "";
    if (reference.startsWith("./")) continue;
    if (!/@[0-9a-f]{40}$/u.test(reference)) {
      throw new Error(`${workflow} action is not pinned to a full commit SHA: ${reference}`);
    }
    if (!/^v\d/u.test((match[2] ?? "").trim())) {
      throw new Error(`${workflow} pinned action needs an updateable release comment: ${reference}`);
    }
  }
}

console.log(
  `Discoverability verified: ${String(requiredFiles.length)} machine/human discovery files, package metadata, and immutable workflow actions.`,
);

async function manifests(...directories) {
  const result = [];
  for (const directory of directories) {
    for (const file of await files(directory)) {
      if (file.endsWith("/package.json")) result.push(file);
    }
  }
  return result;
}

async function files(directory) {
  const entries = await readdir(new URL(`${directory}/`, root), { withFileTypes: true });
  const result = [];
  for (const entry of entries) {
    const child = join(directory, entry.name).replaceAll("\\", "/");
    if (entry.isDirectory()) result.push(...(await files(child)));
    else result.push(child);
  }
  return result;
}
