# Module Manifests

Each subdirectory under `modules/` represents one managed API-builder module.

At minimum, each module should contain:

- `module.yml`

The manifest is used by the Qt6 builder app to:

- identify the module
- show/edit settings
- infer implemented endpoints from the configured client class
- find processed capture summaries
- run module-specific helper commands

The `_template/` directory provides a starter manifest for new modules.
