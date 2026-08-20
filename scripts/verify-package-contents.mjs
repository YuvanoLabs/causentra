import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const cache = fileURLToPath(new URL("../.causentra/npm-cache/", import.meta.url));
const npmCli = process.env.npm_execpath;
if (npmCli === undefined) {
  throw new Error("Run package verification through npm so npm_execpath is available");
}
mkdirSync(cache, { recursive: true });

const packages = [
  ["@causentra/sdk", "dist/src/index.js"],
  ["@causentra/openai-agents", "dist/src/index.js"],
  ["@causentra/langgraph", "dist/src/index.js"],
  ["@causentra/opentelemetry", "dist/src/index.js"],
  ["@causentra/server", "dist/src/index.js"],
  ["@causentra/cli", "dist/src/index.js"],
];

for (const [workspace, entry] of packages) {
  const output = execFileSync(
    process.execPath,
    [npmCli, "pack", "--dry-run", "--json", "-w", workspace],
    {
      cwd: root,
      encoding: "utf8",
      env: { ...process.env, npm_config_cache: cache },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  const result = JSON.parse(output)[0];
  const paths = result.files.map((file) => file.path);
  for (const required of ["package.json", "README.md", "LICENSE", "NOTICE", entry]) {
    if (!paths.includes(required)) {
      throw new Error(`${workspace} archive is missing ${required}`);
    }
  }
  if (workspace === "@causentra/sdk" && !paths.includes("schema/runtime-event-v1.schema.json")) {
    throw new Error("@causentra/sdk archive is missing the versioned JSON Schema");
  }
  const forbidden = paths.filter(
    (path) =>
      path.includes("/test/") ||
      path.startsWith("test/") ||
      path.includes("node_modules"),
  );
  if (forbidden.length > 0) {
    throw new Error(`${workspace} archive contains forbidden files: ${forbidden.join(", ")}`);
  }
  console.log(`Verified ${workspace}: ${String(paths.length)} public files.`);
}
