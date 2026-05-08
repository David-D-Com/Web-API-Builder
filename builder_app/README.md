# Web API Builder

Qt6 desktop app for managing browser-derived API modules in this repo.

## Goals

- treat each reverse-engineered target as a module
- make module settings editable without hand-editing every file
- scaffold starter package files for new modules
- show implemented endpoints and processed captures in one place
- run module-specific tests
- launch a browser session using the module's existing helper flow
- process and clean raw captures after a browser session

## Current Scope

The first scaffold focuses on:

- loading module manifests from `../modules/*/module.yml`
- editing basic metadata and capture settings
- keeping raw/processed capture roots as workspace-level settings
- deriving module code paths automatically from module names
- showing implemented client methods inferred from Python source
- showing raw capture sessions for the currently selected module
- launching configured commands:
  - run tests
  - open browser
  - process captures

The first managed module is `soliscloud`.

## Install

```powershell
py -m pip install -e .\builder_app
```

## Run

```powershell
python -m web_api_builder
```

or

```powershell
web-api-builder
```

## Notes

- The app uses `PySide6` for Qt6.
- Module manifests use YAML and are stored in the repo under `modules/`.
- New template modules automatically get a starter package under `python/src/<module_slug>/`
  and a smoke runner under `tests/<module_slug>_smoke.py`.
- The app intentionally manages modules and helper workflows, not the internal logic of the target packages themselves.
