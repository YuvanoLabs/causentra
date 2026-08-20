# Product roadmap

This roadmap covers Causentra. Exit criteria depend on evidence, not dates.

## Current: Python release candidate

- [x] One privacy-safe lifecycle schema across Python and TypeScript
- [x] Six maintained Python framework adapters and two maintained TypeScript adapter families
- [x] Eight deep provider mappings, seven compatibility profiles, custom provider IDs, and OTLP interoperability
- [x] Durable producer spool with HTTP, WebSocket, Kafka, NATS JetStream, Redis Streams, and MQTT delivery
- [x] Durable event engine with named subscriptions, retry, dead letters, and explicit redelivery
- [x] Authenticated, project-isolated Python collector with quotas, readiness, metrics, and durable SQLite WAL storage
- [x] Permissioned, integrity-checked child-process plugin protocol
- [x] Causal tree, handoff/delegation view, safe filters, CLI, dashboard, and portable trace lifecycle

## Gate A: trustworthy source launch

- Assign monitored maintainer, security, conduct, and funding contacts
- Pin reviewed CI actions; enable branch protection and private vulnerability reporting
- Publish benchmark results from a documented target machine
- Commission an independent security review and resolve critical/high findings
- Record restore, broker failure/recovery, and 24-hour soak evidence on target infrastructure

Exit: no open critical/high release finding; all automated gates pass from a clean checkout; recovery evidence is reviewed.

## Gate B: public package preview

- Verify package namespace ownership, signing, provenance, and rollback procedure
- Test the declared Python/OS matrix in the public CI environment
- Observe five external onboarding sessions; at least four reach a first trace in five minutes
- Publish the supported-version matrix and first compatibility results

Exit: signed packages install cleanly; 4/5 onboarding target; no cross-project or content-capture defect.

## Gate C: ecosystem proof

- Reach recurring use across at least five independent projects
- Accept one externally maintained adapter through the conformance contract
- Select further adapters from measured demand
- Stabilize retry/evaluation vocabulary only after real interoperability evidence

Exit: retained usage and external ownership demonstrate value beyond repository interest.

## Later managed capabilities

Shared retention, collaboration, identity, governance, analytics, alerts, managed deployment, and contracted support remain future Causentra capabilities. Their delivery requires recurring adoption, and they will use the same packages and event contract as the local runtime.

## Explicit non-promises

Agent/tool side-effect replay, chain-of-thought capture, silent price inference, compliance certification, and universal framework coverage are not promised. Event-engine replay only redelivers stored events to idempotent handlers.
