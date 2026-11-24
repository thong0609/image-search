# Repository Guidelines

## Project Structure & Module Organization

Vietnamese image search. Python package in `src/image_search/` (planner, retrieval, embedding,
graph, baseline, adapters, api), Next.js playground in `frontend/`, tests in `tests/`, evaluation
scripts in `scripts/`, documentation in `docs/`. See `README.md` for the full layout.

Keep downloaded images, models, datasets and run artifacts in `data/` and `var/`, outside Git.

## Build, Test, and Development Commands

```bash
uv sync --frozen --extra baseline --extra planner
uv run ruff check . && uv run ruff format --check .
uv run pytest
```

Integration tests and service commands are documented in `README.md` and `docs/guides/`.
Do not describe a command as supported until its configuration exists.

## Coding Style & Naming Conventions

Follow existing conventions and Ruff configuration. Use descriptive names and small modules with a
single responsibility. Prefer lowercase, hyphen-separated names for documentation and asset files.
Avoid unrelated formatting changes in feature or bug-fix patches.

## Testing Guidelines

Use pytest; name tests after the behavior they verify. Prefer deterministic fixtures and mocked
external requests over live network dependencies.

## Commit & Pull Request Guidelines

Use short, imperative commit subjects, such as `Add image search endpoint`, and keep commits focused.
Pull requests should explain the change, link related issues when available, and describe validation
performed. Include screenshots for visible interface changes.

## Security & Configuration

Never commit credentials, API keys, or private image data. Document required configuration with
placeholder values in `.env.example`. Do not modify hidden workspace metadata directories.

## User decisions (required)

- Qdrant is the persistent vector store agreed in the project plan. Do not add
  NumPy vector files, disk vector caches, or an alternative retrieval backend.
  NumPy calculations in memory are allowed; persist model/index metadata in Qdrant.
- Follow the approved plan. If an implementation decision lacks necessary
  information or changes that plan, ask before proceeding with the dependent work.
- At task completion, explicitly report missing information, assumptions made,
  and deviations from the approved plan (state none when applicable).
- Keep implementation simple and explanations concise.
- Treat metadata of records marked approve=yes as trusted; do not add external
  source verification. Build entity relations from what the metadata states.
- The revised graph must focus on entities and their relations, without
  SourceRecord, SourcePage, or SourceLabel nodes. Keep search metadata in Qdrant.

- Current graph extraction is authored directly by Codex from trusted dataset metadata.
  Do not call paid extraction APIs without a new request; online planner is separate.
