Read `AGENTS.md` and every project file it requires before doing any work.

This repository is migrating from Claude Code to Codex. Do not restart or redesign it.

Perform a READ-ONLY repository audit only.

1. Run `git status --short`.
2. Run `git log --oneline -5`.
3. Identify repo root and current branch.
4. Read legacy specs and all current TFEX/data-readiness docs named in `AGENTS.md`.
5. Inspect the existing Settrade probe script and market-data validator without editing.
6. From `backend/`, run:
   - `uv run pytest tests/tfex`
   - `uv run pytest -m anti_repaint`
   - `uv run ruff check .`
   - `uv run ruff format --check .`
   - `uv run mypy .`
7. Do not call Settrade yet.
8. Do not print or inspect credential values.
9. Do not edit any file.

Return:
- Git state
- latest commits
- current milestone
- current data-readiness gate
- exact test results
- Settrade probe script path
- real-market-data validator path
- exactly one recommended next action

If repository facts conflict with `AGENTS.md`, report the conflict instead of guessing.
