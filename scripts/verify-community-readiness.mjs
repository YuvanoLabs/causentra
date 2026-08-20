import { access, readFile, readdir } from "node:fs/promises";

const root = new URL("../", import.meta.url);
const requiredFiles = [
  "README.md",
  "CONTRIBUTING.md",
  "CODE_OF_CONDUCT.md",
  "SECURITY.md",
  "SUPPORT.md",
  "GOVERNANCE.md",
  "FUNDING.md",
  "ROADMAP.md",
  "PUBLIC_REPOSITORY_CHECKLIST.md",
  "CITATION.cff",
  "llms.txt",
  "docs/30-discoverability-and-search.md",
  "docs/31-product-faq.md",
  ".github/dependabot.yml",
  ".github/PULL_REQUEST_TEMPLATE.md",
  ".github/ISSUE_TEMPLATE/bug_report.yml",
  ".github/ISSUE_TEMPLATE/feature_request.yml",
  ".github/ISSUE_TEMPLATE/adapter_request.yml",
  ".github/ISSUE_TEMPLATE/config.yml",
  "templates/community-adapter/README.md",
  "templates/community-adapter/src/index.ts",
  "templates/community-adapter/test/adapter.test.ts",
];

const contents = new Map();
for (const file of requiredFiles) {
  try {
    contents.set(file, await readFile(new URL(file, root), "utf8"));
  } catch (error) {
    if (error?.code === "ENOENT") throw new Error(`Missing community file: ${file}`);
    throw error;
  }
}

const readme = contents.get("README.md") ?? "";
for (const requiredClaim of [
  "Status: public source release candidate",
  "What works today",
  "One product, evolving capabilities",
  "Fund the work",
]) {
  if (!readme.includes(requiredClaim)) {
    throw new Error(`README is missing required public-status language: ${requiredClaim}`);
  }
}

const security = contents.get("SECURITY.md") ?? "";
if (security.includes("security@causentra.dev") || security.includes("placeholder")) {
  throw new Error("SECURITY.md contains an unverified contact or placeholder");
}

const adapterSource = contents.get("templates/community-adapter/src/index.ts") ?? "";
const adapterTest = contents.get("templates/community-adapter/test/adapter.test.ts") ?? "";
for (const requiredContract of [
  "AdapterEventBridge",
  "parentContext",
  "createAgentRelationshipAttributes",
  "createModelTelemetryAttributes",
]) {
  if (!adapterSource.includes(requiredContract)) {
    throw new Error(`Community adapter template is missing contract: ${requiredContract}`);
  }
}
if (!adapterTest.includes("assertAdapterConformance")) {
  throw new Error("Community adapter template must execute the public conformance contract");
}
if (!security.includes("Report a vulnerability")) {
  throw new Error("SECURITY.md must explain private vulnerability reporting");
}

let checkedLinks = 0;
for (const file of await markdownFiles(".")) {
  const markdown = await readFile(new URL(file, root), "utf8");
  const links = markdown.matchAll(/\[[^\]]*\]\(([^)]+)\)/gu);
  for (const match of links) {
    const rawTarget = match[1]?.trim() ?? "";
    if (
      rawTarget.length === 0 ||
      rawTarget.startsWith("#") ||
      /^(?:https?:|mailto:)/u.test(rawTarget)
    ) {
      continue;
    }
    const target = rawTarget.replace(/^<|>$/gu, "").split("#", 1)[0];
    try {
      await access(new URL(target, new URL(file, root)));
    } catch {
      throw new Error(`Broken local Markdown link in ${file}: ${rawTarget}`);
    }
    checkedLinks += 1;
  }
}

console.log(
  `Community readiness verified: ${String(requiredFiles.length)} required files and ${String(checkedLinks)} local documentation links.`,
);

async function markdownFiles(directory) {
  const files = [];
  for (const entry of await readdir(new URL(`${directory}/`, root), { withFileTypes: true })) {
    if (
      ["node_modules", "dist", ".causentra", ".venv", "venv", ".venv-frameworks"].includes(entry.name) ||
      entry.name.startsWith(".venv-")
    ) {
      continue;
    }
    const child = directory === "." ? entry.name : `${directory}/${entry.name}`;
    if (entry.isDirectory()) files.push(...(await markdownFiles(child)));
    else if (entry.name.endsWith(".md")) files.push(child);
  }
  return files;
}
