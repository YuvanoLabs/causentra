# Security policy

## Supported status

Causentra is a public source release candidate. No published version currently receives a production support commitment. Security fixes will be documented in the changelog and, after packages exist, released for the latest maintained line.

The Node.js inspection server has no authentication and is designed for loopback-only development. Do not expose it to an untrusted network. The Python collector requires project bearer keys and requires TLS for remote binding by default; its unsafe override is development-only. Prompt, output, state, tool-argument, metadata, and error-message capture are excluded by default, but key-based redaction cannot make arbitrary free text safe.

## Report a vulnerability privately

Do not open a public issue, discussion, or pull request containing vulnerability details, credentials, customer data, or an exploit.

Use the repository's **Security → Report a vulnerability** flow. The repository owner must enable GitHub private vulnerability reporting before launch. If that flow is unavailable, email [smartbytecoder@gmail.com](mailto:smartbytecoder@gmail.com) with the subject `Causentra security contact request` and no technical details; the maintainer will establish a private reporting channel.

Include the affected version or commit, impact, prerequisites, minimal synthetic reproduction, and suggested mitigation when possible. Do not test against systems or data you do not own.

## Response process

Once a monitored private channel is active, maintainers target acknowledgement within three business days, severity assessment, coordinated remediation, and disclosure after a fix is available. Reporters are credited unless anonymity is requested. No bug bounty or payment is implied.

Security fixes apply to the complete Causentra product. Optional future capabilities never justify withholding a fix needed by the SDK, adapters, collector, CLI, schema, or local dashboard.
