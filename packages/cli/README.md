# @causentra/cli

Local operations for the open-source Causentra data plane.

```bash
causentra serve
causentra doctor
causentra demo
causentra traces
causentra trace <trace-id>
causentra export <trace-id> [file]
causentra import <bundle-file>
causentra delete <trace-id>
causentra prune <keep-latest-count>
```

Export/import uses a versioned, validated trace bundle. Deletion and pruning are explicit; the local store has no automatic trace-count limit. Run `causentra help` for configuration variables.
