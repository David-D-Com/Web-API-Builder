# Builder Settings

Each YAML file in `settings/` represents one managed API-builder module.

Examples:

- `settings/soliscloud.yml`
- `settings/new_module_1.yml`

The builder app uses these manifests to:

- identify the module
- show and edit module-specific settings
- infer implemented endpoints from the configured client class
- find module-scoped capture sessions
- run module-specific helper commands

`settings/_template.yml` provides the starter manifest used when creating a new module.
