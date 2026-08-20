# Publishing Causentra on PyPI

The public Python package is `causentra`. Users install a published release with:

```bash
python -m pip install causentra
```

The package is built from `python/` and publishes both a source distribution and a universal wheel. Its release workflow is deliberately separate from CI so the only job that receives a PyPI identity merely downloads the already-built distributions and uploads them.

## One-time owner setup

1. Create and secure the PyPI owner account that will own `causentra`. Confirm the name is available immediately before the first release.
2. In PyPI, create a **pending Trusted Publisher** with these exact values:
   - PyPI project name: `causentra`
   - Owner: `smartbytecoder`
   - Repository: `causentra`
   - Workflow file: `release.yml`
   - Environment: `pypi`
3. In GitHub, create the `pypi` environment, set its URL to `https://pypi.org/project/causentra/`, and require approval by a release maintainer. Protect tags matching `v*` so only release maintainers can create them.

Trusted Publishing exchanges a GitHub Actions OIDC identity for a short-lived PyPI credential. There is no `PYPI_TOKEN` secret to create, copy, rotate, or expose.

## Releasing a version

1. Choose the version in `python/pyproject.toml`, update the version string in `python/src/causentra/otel.py`, and ensure the release evidence is complete.
2. From a clean checkout, run:

   ```bash
   npm ci
   python -m pip install -e "python[dev]"
   npm run python:verify
   ```

3. Commit the version changes, then create and push the matching immutable tag. For the present `0.1.0a1` version:

   ```bash
   git tag -a v0.1.0a1 -m "Causentra 0.1.0a1"
   git push origin v0.1.0a1
   ```

4. Approve the `pypi` environment deployment after the build and clean-wheel jobs pass. The workflow verifies the tag exactly matches `python/pyproject.toml`, publishes `python/dist/`, and uploads PyPI attestations automatically.
5. Verify the public artifact from a new virtual environment:

   ```bash
   python -m venv .venv-causentra-check
   .venv-causentra-check/bin/python -m pip install causentra
   ```

   On Windows, use `.venv-causentra-check\Scripts\python.exe` instead.

The first release is an alpha (`0.1.0a1`). Pip considers pre-releases only when no final release satisfies the request; use `python -m pip install --pre causentra` if a later final release is already installed or selected.

## Security properties

- Only a protected `v*` tag can start publication.
- The tag must equal `v` plus the package version.
- The build runs before the publish job and installs the wheel in a fresh virtual environment.
- The publish job has only `id-token: write`; it has no checkout, repository write permission, or long-lived package credential.
- PyPI's official publishing action attaches package attestations by default.

Do not delete or re-upload a published version: PyPI package files are immutable. Correct a release with a new version and yank a harmful version if necessary.
