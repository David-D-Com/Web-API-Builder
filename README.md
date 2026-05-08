# Repo Layout

This repository is intentionally not the same thing as the Python package.

## Layout

- `python/`
  The actual installable `soliscloud_web_api` Python module.
- `builder_app/`
  Qt6 desktop app for managing browser-derived API modules.
- `modules/`
  YAML manifests describing each managed target module.
- `tests/`
  Smoke tests and platform-specific helpers.
- `scripts/`
  One-off exploration or browser-assisted helper scripts.
- `har/`
  Raw captured browser API responses before processing.
- `captures_processed/`
  Cleaned endpoint-grouped capture artifacts derived from raw browser captures.
- `PROJECT_GUIDELINES.md`
  Repo-wide development guidelines.

## Package install

```powershell
py -m pip install -e .\python
py -m pip install -e .\python[windows-credentials]
```

## Builder app install

```powershell
py -m pip install -e .\builder_app
```
