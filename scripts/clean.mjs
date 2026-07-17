import { rm } from "node:fs/promises";

for (const directory of [
  "packages/sdk/dist",
  "packages/adapter-openai-agents/dist",
  "packages/adapter-langgraph/dist",
  "packages/adapter-opentelemetry/dist",
  "packages/cli/dist",
  "apps/runtime-server/dist",
  "templates/community-adapter/dist",
]) {
  await rm(new URL(`../${directory}`, import.meta.url), {
    recursive: true,
    force: true,
  });
}
