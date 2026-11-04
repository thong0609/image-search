# Repository Guidelines

## Project Structure & Module Organization

This workspace, `Images-search`, currently has no application source, tests, assets, or build configuration. Treat it as an initial scaffold; do not assume a language or framework has been selected.

When adding the first implementation, use a clear layout such as `src/` for application code, `tests/` for automated tests, and `assets/` for static resources and sample images. Document the actual layout in `README.md`. Keep generated files and downloaded image collections outside version control unless explicitly required as small test fixtures.

## Build, Test, and Development Commands

No build, test, or development commands are configured yet. When introducing a toolchain, document exact installation, local startup, build, lint, and test commands in `README.md`, and commit the relevant manifest and lockfile.

Use `rg --files --hidden -g '!.git/**'` to inspect repository files. Do not describe commands such as `npm test` or `make build` as supported until their configuration exists.

## Coding Style & Naming Conventions

Follow the conventions of the language chosen for the implementation. Use consistent indentation within each file, descriptive names, and small modules with a single responsibility. Prefer lowercase, hyphen-separated names for documentation and asset files, such as `search-results.png`.

Configure an appropriate formatter and linter with the first source contribution. Avoid unrelated formatting changes in feature or bug-fix patches.

## Testing Guidelines

No testing framework or coverage threshold is established. Add a framework appropriate to the selected stack and document how to run it. Name tests after the behavior they verify and follow that framework's discovery conventions.

For image-search functionality, cover query handling, empty results, invalid inputs, and service failures as these features are introduced. Prefer deterministic fixtures and mocked external requests over live network dependencies.

## Commit & Pull Request Guidelines

No usable Git history is available to establish existing commit conventions. Use short, imperative commit subjects, such as `Add image search endpoint`, and keep commits focused.

Pull requests should explain the change, link related issues when available, and describe validation performed. Include screenshots for visible interface changes and note any new configuration or dependencies.

## Security & Configuration

Never commit credentials, API keys, or private image data. Document required configuration with placeholder values in an example environment file. Treat hidden workspace metadata directories as environment-managed; do not modify them as part of application work.
