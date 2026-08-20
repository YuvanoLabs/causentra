import { spawnSync } from "node:child_process";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
await mkdir(new URL("../python/.eggs/", import.meta.url), { recursive: true });

const result = spawnSync(
  "python",
  ["-m", "build", "--no-isolation", "--outdir", "python/dist", "python"],
  { cwd: root, stdio: "inherit" },
);

if (result.error !== undefined) throw result.error;
process.exitCode = result.status ?? 1;
