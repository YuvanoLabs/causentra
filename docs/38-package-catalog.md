# Package catalog

This catalog is the authoritative repository release line for Causentra
`1.0.0`. The Python runtime is published on PyPI. The TypeScript packages have
verified `1.0.0` archives but are not yet listed in the public npm registry;
consume them from this workspace or owner-supplied package archives until their
registry publication is complete.

| Package | Runtime | Purpose | Package documentation |
|---|---|---|---|
| `causentra` `1.0.0` | Python 3.10+ | Primary instrumentation runtime, durable delivery, authenticated collector, CLI, adapters, signing, aggregation, evaluation, and price catalogs | [Python package](../python/README.md) |
| `@causentra/sdk` `1.0.0` | Node.js 22+ | Framework-neutral TypeScript event SDK, schemas, W3C context, redaction, and local signatures | [SDK](../packages/sdk/README.md) |
| `@causentra/openai-agents` `1.0.0` | Node.js 22+ | OpenAI Agents SDK tracing processor | [OpenAI Agents adapter](../packages/adapter-openai-agents/README.md) |
| `@causentra/langgraph` `1.0.0` | Node.js 22+ | LangGraph/LangChain callback instrumentation | [LangGraph adapter](../packages/adapter-langgraph/README.md) |
| `@causentra/opentelemetry` `1.0.0` | Node.js 22+ | OpenTelemetry span projection and OTLP/HTTP protobuf export | [OpenTelemetry bridge](../packages/adapter-opentelemetry/README.md) |
| `@causentra/server` `1.0.0` | Node.js 22+ | Loopback local collector, query API, and dashboard | [Local server](../apps/runtime-server/README.md) |
| `@causentra/cli` `1.0.0` | Node.js 22+ | Local server and trace-operation CLI | [CLI](../packages/cli/README.md) |

## Installation

Install the stable Python runtime with only the extras an application uses:

```bash
python -m pip install "causentra[openai-agents,langgraph]==1.0.0"
```

For TypeScript development from this repository, install the workspace and
build its package artifacts:

```bash
npm install
npm run build
```

After an owner publishes the matching npm artifacts, a consumer can install an
exact package set such as:

```bash
npm install @causentra/sdk@1.0.0 @causentra/openai-agents@1.0.0
```

The Node.js CLI and the Python runtime both expose a `causentra` executable.
Keep them in separate application environments or invoke one through the
package manager; do not install both global commands into the same PATH.

All internal npm dependencies are exact `1.0.0` dependencies. Build and
verify the repository before publishing any package archive; a package
registry will reject replacement of an already-published version.

## Compatibility and production boundary

Every package in this catalog uses RuntimeEvent schema 1.0 and preserves the
privacy-default contract: prompts, model outputs, tool arguments/results,
arbitrary framework state, and raw exception messages are not collected by
default. The Node.js server is a loopback development/inspection component;
use the authenticated Python collector with TLS for a remote production data
plane. See the [integration guide](17-integration-guide.md),
[production runtime](24-production-python-runtime.md), and
[deployment runbook](34-production-deployment-runbook.md) for operational
requirements.
