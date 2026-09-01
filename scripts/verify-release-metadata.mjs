import { readFile } from "node:fs/promises";

const root = new URL("../", import.meta.url);
const packageManifests = [
  "package.json",
  "packages/sdk/package.json",
  "packages/adapter-openai-agents/package.json",
  "packages/adapter-langgraph/package.json",
  "packages/adapter-opentelemetry/package.json",
  "packages/cli/package.json",
  "apps/runtime-server/package.json",
];
const internalDependencies = new Map([
  ["apps/runtime-server/package.json", ["@causentra/sdk"]],
  ["packages/adapter-openai-agents/package.json", ["@causentra/sdk"]],
  ["packages/adapter-langgraph/package.json", ["@causentra/sdk"]],
  ["packages/adapter-opentelemetry/package.json", ["@causentra/sdk"]],
  ["packages/cli/package.json", ["@causentra/sdk", "@causentra/server"]],
  ["templates/community-adapter/package.json", ["@causentra/sdk"]],
]);

const pyproject = await source("python/pyproject.toml");
const version = pyproject.match(/^version = "([^"]+)"$/mu)?.[1];
if (version === undefined) throw new Error("python/pyproject.toml must declare a release version");
if (!/^\d+\.\d+\.\d+$/u.test(version)) {
  throw new Error(`release version must be stable SemVer/PEP 440, received ${version}`);
}
if (!pyproject.includes('"Development Status :: 5 - Production/Stable"')) {
  throw new Error("Python package must declare the Production/Stable classifier");
}

for (const manifestPath of packageManifests) {
  const manifest = JSON.parse(await source(manifestPath));
  if (manifest.version !== version) {
    throw new Error(`${manifestPath} has version ${String(manifest.version)}, expected ${version}`);
  }
  for (const dependency of internalDependencies.get(manifestPath) ?? []) {
    if (manifest.dependencies?.[dependency] !== version) {
      throw new Error(`${manifestPath} must depend on ${dependency}@${version}`);
    }
  }
}

const templateManifest = JSON.parse(await source("templates/community-adapter/package.json"));
if (templateManifest.dependencies?.["@causentra/sdk"] !== version) {
  throw new Error(`community adapter template must depend on @causentra/sdk@${version}`);
}

const otel = await source("python/src/causentra/otel.py");
if (!otel.includes(`provider.get_tracer("causentra", "${version}")`)) {
  throw new Error("Python OpenTelemetry instrumentation version is out of sync");
}
const javascriptOtel = await source("packages/adapter-opentelemetry/src/index.ts");
if (!javascriptOtel.includes(`provider.getTracer("causentra", "${version}")`)) {
  throw new Error("JavaScript OpenTelemetry instrumentation version is out of sync");
}

const citation = await source("CITATION.cff");
if (!citation.includes(`version: ${version}`)) throw new Error("CITATION.cff version is out of sync");

for (const documentPath of [
  "README.md",
  "python/README.md",
  "llms.txt",
  "docs/32-pypi-release.md",
  "docs/38-package-catalog.md",
]) {
  if (!(await source(documentPath)).includes(version)) {
    throw new Error(`${documentPath} does not document the ${version} release line`);
  }
}

const localApi = await source("docs/openapi.yaml");
if (!localApi.includes(`  version: ${version}`)) {
  throw new Error("Local OpenAPI release version is out of sync");
}

console.log(`Release metadata verified: ${version} across Python, npm packages, instrumentation, and docs.`);

function source(path) {
  return readFile(new URL(path, root), "utf8");
}
