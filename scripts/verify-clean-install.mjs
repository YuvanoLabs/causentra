import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const defaultSmokeRoot = fileURLToPath(new URL("../.causentra/install-smoke/", import.meta.url));
let smokeRoot = defaultSmokeRoot;
const npmCli = process.env.npm_execpath;
if (npmCli === undefined) throw new Error("Run through npm so npm_execpath is available");
const safeRoot = join(root, ".causentra");
if (!smokeRoot.startsWith(join(safeRoot, "install-smoke"))) {
  throw new Error("Refusing to clean an install-smoke path outside .causentra/install-smoke");
}

try {
  rmSync(smokeRoot, { recursive: true, force: true, maxRetries: 4, retryDelay: 75 });
} catch (error) {
  if (error.code !== "EPERM") {
    throw error;
  }
  console.warn(`Falling back from ${smokeRoot}: ${error.message}`);
  smokeRoot = mkdtempSync(join(tmpdir(), "causentra-install-smoke-"));
}
if (!smokeRoot.startsWith(safeRoot)) {
  console.warn(`Using temporary smoke root: ${smokeRoot}`);
}

const packageDirectory = join(smokeRoot, "packages");
const consumerDirectory = join(smokeRoot, "consumer");
let environment;

try {
  mkdirSync(packageDirectory, { recursive: true });
  mkdirSync(consumerDirectory, { recursive: true });

  const includeFrameworks = process.argv.includes("--with-frameworks");
  // The core gate needs no registry packages and uses an isolated writable cache.
  // The extended gate reuses the cache populated by npm install/npm ci because it
  // resolves framework peers and their transitive dependency metadata.
  environment = includeFrameworks
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
    run(["pack", "-w", workspace, "--pack-destination", packageDirectory], environment);
  }

  writeFileSync(
    join(consumerDirectory, "package.json"),
    `${JSON.stringify({ name: "causentra-install-smoke", version: "0.0.0", private: true, type: "module" }, null, 2)}\n`,
  );
  const archives = packages.map((workspace) => archivePath(workspace, packageDirectory));
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
  ], environment, consumerDirectory);
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
} finally {
  try {
    rmSync(smokeRoot, { recursive: true, force: true, maxRetries: 4, retryDelay: 75 });
  } catch (error) {
    console.warn(`Unable to clean smoke root ${smokeRoot}: ${error.message}`);
  }
}

function run(arguments_, environment_, cwd = root) {
  execFileSync(process.execPath, [npmCli, ...arguments_], {
    cwd,
    env: environment_,
    stdio: "inherit",
  });
}

function archivePath(workspace, destination) {
  const manifest = JSON.parse(
    readFileSync(join(root, workspaceDirectory(workspace), "package.json"), "utf8"),
  );
  const filename = `${String(manifest.name).replace(/^@/u, "").replaceAll("/", "-")}-${String(manifest.version)}.tgz`;
  return join(destination, filename);
}

function workspaceDirectory(workspace) {
  return {
    "@causentra/sdk": "packages/sdk",
    "@causentra/openai-agents": "packages/adapter-openai-agents",
    "@causentra/langgraph": "packages/adapter-langgraph",
    "@causentra/opentelemetry": "packages/adapter-opentelemetry",
    "@causentra/server": "apps/runtime-server",
    "@causentra/cli": "packages/cli",
  }[workspace] ?? fail(`unknown workspace ${workspace}`);
}

function fail(message) {
  throw new Error(message);
}
