import { readFile, readdir } from "node:fs/promises";
import { join, relative } from "node:path";

const root = new URL("../", import.meta.url);
const textExtensions = new Set([".ts", ".tsx", ".js", ".mjs", ".json", ".py", ".toml"]);
const violations = [];

const rootManifest = await json("package.json");
for (const workspace of rootManifest.workspaces ?? []) {
  if (String(workspace).startsWith("enterprise")) {
    violations.push(`root workspace includes private path: ${workspace}`);
  }
}

for (const directory of ["packages", "apps", "examples", "templates", "python"]) {
  for (const file of await walk(directory)) {
    if (!textExtensions.has(extension(file)) || file.includes("/dist/")) continue;
    const contents = await readFile(new URL(file, root), "utf8");
    if (contents.includes("@causentra-enterprise/")) {
      violations.push(`OSS source imports or names the private namespace: ${file}`);
    }
    if (contents.includes("causentra_enterprise")) {
      violations.push(`OSS source imports or names the private Python namespace: ${file}`);
    }
  }
}

const adapterTemplateManifest = await json("templates/community-adapter/package.json");
if (adapterTemplateManifest.private !== true) {
  violations.push("community adapter template must remain private until copied and reviewed");
}
if (adapterTemplateManifest.license !== "Apache-2.0") {
  violations.push("community adapter template must preserve the public Apache-2.0 license");
}

for (const manifestPath of await findManifests("packages", "apps")) {
  const manifest = await json(manifestPath);
  if (manifest.license !== "Apache-2.0") {
    violations.push(`OSS package must use Apache-2.0: ${manifestPath}`);
  }
  if (!String(manifest.name ?? "").startsWith("@causentra/")) {
    violations.push(`OSS package uses an invalid namespace: ${manifestPath}`);
  }
}

if (violations.length > 0) {
  console.error("OSS boundary verification failed:\n");
  for (const violation of violations) console.error(`- ${violation}`);
  process.exitCode = 1;
} else {
  console.log("OSS boundary verified: public build is independent of enterprise code.");
}

async function json(path) {
  return JSON.parse(await readFile(new URL(path, root), "utf8"));
}

async function findManifests(directory) {
  return (await walk(directory)).filter((file) => file.endsWith("/package.json"));
}

async function walk(directory) {
  const absolute = new URL(`${directory}/`, root);
  let entries;
  try {
    entries = await readdir(absolute, { withFileTypes: true });
  } catch (error) {
    if (error?.code === "ENOENT") return [];
    throw error;
  }
  const files = [];
  for (const entry of entries) {
    if (entry.name === "node_modules" || entry.name === "dist") continue;
    const child = join(directory, entry.name).replaceAll("\\", "/");
    if (entry.isDirectory()) files.push(...(await walk(child)));
    else files.push(relative(".", child).replaceAll("\\", "/"));
  }
  return files;
}

function extension(file) {
  const dot = file.lastIndexOf(".");
  return dot < 0 ? "" : file.slice(dot);
}
