# Adapter template

This copyable scaffold demonstrates the minimum acceptable Causentra adapter: public framework hooks, allowlisted operational metadata, fail-open mapping, shared parent context, portable relationships, and executable conformance tests.

## Adapt it

1. Copy this directory outside `templates/`.
2. Replace the package name and `FRAMEWORK_NAME`; keep `private: true` until publication is approved.
3. Add the framework as a narrow peer dependency and compile against its minimum and maximum supported versions.
4. Replace `ExampleFrameworkEvent` with types from the framework's documented extension surface.
5. Map lifecycle events explicitly. Do not monkey-patch private methods or spread arbitrary framework objects into attributes.
6. Add a deterministic real-framework integration test in addition to the included contract fixture.
7. Copy the repository `LICENSE`, create an accurate `NOTICE`, document limitations and shutdown behavior, then run the complete workspace verification.

From the repository root, the unchanged template is validated with:

```bash
npm run test:adapter-template
```

The scaffold intentionally has no prompt, message, state, output, tool-argument, exception-message, credential, or generic metadata fields. Add content capture only through an explicit, documented, tested policy reviewed by maintainers.

Read the repository [contribution policy](../../CONTRIBUTING.md) and [schema compatibility contract](../../docs/18-schema-compatibility.md) before proposing an adapter.
