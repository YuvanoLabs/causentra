import { execFileSync } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const smokeRoot = fileURLToPath(new URL("../.causentra/install-smoke/", import.meta.url));
const packageDirectory = join(smokeRoot, "packages");
const consumerDirectory = join(smokeRoot, "consumer");
const npmCli = process.env.npm_execpath;
if (npmCli === undefined) throw new Error("Run through npm so npm_execpath is available");
if (!smokeRoot.startsWith(join(root, ".causentra"))) {
  throw new Error("Refusing to clean an install-smoke path outside .causentra");
}

rmSync(smokeRoot, { recursive: true, force: true });
mkdirSync(packageDirectory, { recursive: true });
mkdirSync(consumerDirectory, { recursive: true });

const includeFrameworks = process.argv.includes("--with-frameworks");
// The core gate needs no registry packages and uses an isolated writable cache.
// The extended gate reuses the cache populated by npm install/npm ci because it
// resolves framework peers and their transitive dependency metadata.
const environment = includeFrameworks
  ? { ...process.env }
  : {
      ...process.env,
      npm_config_cache: join(root, ".causentra", "npm-cache"),
    };
const packages = [
  "@causentra/sdk",
  ...(includeFrameworks
    ? ["@causentra/openai-agents", "@causentra/langgraph", "@causentra/opentelemetry"]
    : []),
  "@causentra/server",
  "@causentra/cli",
];
for (const workspace of packages) {
  run(["pack", "-w", workspace, "--pack-destination", packageDirectory]);
}

writeFileSync(
  join(consumerDirectory, "package.json"),
  `${JSON.stringify({ name: "causentra-install-smoke", version: "0.0.0", private: true, type: "module" }, null, 2)}\n`,
);
const archives = [
  join(packageDirectory, "causentra-sdk-0.0.1.tgz"),
  ...(includeFrameworks
    ? [
        join(packageDirectory, "causentra-openai-agents-0.0.1.tgz"),
        join(packageDirectory, "causentra-langgraph-0.0.1.tgz"),
        join(packageDirectory, "causentra-opentelemetry-0.0.1.tgz"),
      ]
    : []),
  join(packageDirectory, "causentra-server-0.0.1.tgz"),
  join(packageDirectory, "causentra-cli-0.0.1.tgz"),
];
run([
  "install",
  "--ignore-scripts",
  "--no-audit",
  ...(includeFrameworks
    ? [
        "@openai/agents@0.13.4",
        "@langchain/core@1.2.3",
        "@langchain/langgraph@1.4.8",
      ]
    : []),
  ...archives,
], consumerDirectory);
const imports = [
  "@causentra/sdk",
  ...(includeFrameworks
    ? ["@causentra/openai-agents", "@causentra/langgraph", "@causentra/opentelemetry"]
    : []),
  "@causentra/server",
];
execFileSync(
  process.execPath,
  [
    "--input-type=module",
    "--eval",
    imports.map((packageName) => `await import('${packageName}')`).join("; "),
  ],
  { cwd: consumerDirectory, env: environment, stdio: "inherit" },
);
console.log(
  includeFrameworks
    ? "Clean consumer install verified for all six public package archives and exact framework peers."
    : "Clean consumer install verified for the SDK, server and CLI package archives.",
);

function run(arguments_, cwd = root) {
  execFileSync(process.execPath, [npmCli, ...arguments_], {
    cwd,
    env: environment,
    stdio: "inherit",
  });
}
