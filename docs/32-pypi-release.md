# Causentra on PyPI

The Python runtime is publicly published as [`causentra 0.1.0a1`](https://pypi.org/project/causentra/) for Python 3.10 and later. The package contains a source distribution and a universal wheel.

## Install and use

`0.1.0a1` is an alpha, so opt into prereleases explicitly:

```bash
python -m pip install --pre causentra
```

Install named extras only when the application needs their matching framework:

```bash
python -m pip install --pre "causentra[openai-agents,langgraph]"
```

```python
from causentra import CausentraRuntime, MemoryExporter

exporter = MemoryExporter()
runtime = CausentraRuntime("support-service", exporter)
with runtime.trace("resolve-ticket"):
    with runtime.agent("triage"):
        pass
runtime.shutdown()
```

See the [integration guide](17-integration-guide.md) for framework adapters, transports, and the authenticated collector.

## Releasing a subsequent version

The first version (`0.1.0a1`) has been published. Every later release must use a new version: PyPI will not let anyone replace a published file.

1. Choose the next version in `python/pyproject.toml`, update the version string in `python/src/causentra/otel.py`, and ensure the release evidence is complete.
2. From a clean checkout, run:

   ```bash
   npm ci
   python -m pip install -e "python[dev]"
   npm run python:verify
   ```

   On Windows, the reusable publishing helper creates its own isolated virtual environment, builds the sdist/wheel, and validates their metadata without modifying the global Python installation:

   ```bat
   scripts\publish-python.bat build
   ```

3. Use the local helper to build and validate the distribution. TestPyPI is optional but recommended before a production upload:

   ```bat
   scripts\publish-python.bat test-upload
   scripts\publish-python.bat upload
   ```
4. Verify the public artifact from a new virtual environment:

   ```bash
   python -m venv .venv-causentra-check
   .venv-causentra-check/bin/python -m pip install causentra
   ```

   On Windows, use `.venv-causentra-check\Scripts\python.exe` instead.

The first release is an alpha (`0.1.0a1`). Pip considers pre-releases only when no final release satisfies the request; use `python -m pip install --pre causentra` if a later final release is already installed or selected.

## Future automation

Local publishing is the current release path. Before moving future releases to GitHub Actions, configure PyPI Trusted Publishing, a protected release environment, protected version tags, and package provenance. Trusted Publishing exchanges a GitHub Actions OIDC identity for a short-lived PyPI credential, so it does not require a long-lived `PYPI_TOKEN` secret.

Do not delete or re-upload a published version: PyPI package files are immutable. Correct a release with a new version and yank a harmful version if necessary.
