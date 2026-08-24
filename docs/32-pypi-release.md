# Causentra on PyPI

The Python runtime is publicly published as [`causentra 0.1.0b1`](https://pypi.org/project/causentra/) for Python 3.10 and later. This public beta ships a source distribution and a universal wheel.

## Install and use

`0.1.0b1` is a beta, so opt into prereleases explicitly:

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

The initial alpha (`0.1.0a1`) is immutable. `0.1.0b1` is the first public beta. Every later release must use a new version: PyPI will not let anyone replace a published file.

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

3. Commit the release change, create an annotated version tag, and push the branch and tag:

   ```bash
   git tag -a v0.1.0b1 -m "Causentra 0.1.0b1"
   git push origin main --follow-tags
   ```

   The pinned `publish-python` GitHub Actions workflow builds, audits, verifies, and publishes through PyPI Trusted Publishing. The local helper is for a pre-tag build/metadata check; do not bypass the protected release environment with a manual production upload.
4. Verify the public artifact from a new virtual environment:

   ```bash
   python -m venv .venv-causentra-check
   .venv-causentra-check/bin/python -m pip install causentra
   ```

   On Windows, use `.venv-causentra-check\Scripts\python.exe` instead.

The current public release is a beta (`0.1.0b1`). Pip considers pre-releases only when no final release satisfies the request; use `python -m pip install --pre causentra` if a later final release is already installed or selected.

## Release automation

Before tagging, configure PyPI Trusted Publishing for the `YuvanoLabs/causentra` repository, `.github/workflows/release.yml`, and the `pypi` GitHub environment. Protect version tags and require maintainer approval for that environment. Trusted Publishing exchanges the GitHub Actions OIDC identity for a short-lived PyPI credential, so it does not require a long-lived `PYPI_TOKEN` secret.

Do not delete or re-upload a published version: PyPI package files are immutable. Correct a release with a new version and yank a harmful version if necessary.
