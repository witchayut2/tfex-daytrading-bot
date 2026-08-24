# Data-Readiness Gate — Baseline Verification (PART A)

Verification run **before any code was modified** by the data-readiness gate.

- **UTC timestamp:** 2026-08-23T23:16:03Z
- **Working directory:** `C:\apps7 tfex\TFEX_ClaudeCode_Starter`
- **Git state at time of run:** not a repository (initialised later in PART B)
- **Baseline under test:** Milestones TFEX-0 and TFEX-1 as delivered

## Commands and exact results

```text
$ uv run pytest tests/tfex
277 passed in 0.58s

$ uv run pytest -m anti_repaint
12 passed, 265 deselected in 0.36s

$ uv run ruff check .
All checks passed!

$ uv run ruff format --check .
73 files already formatted

$ uv run mypy .
Success: no issues found in 71 source files
```

## Verdict

| Check | Expected | Observed | Result |
| --- | --- | --- | --- |
| `pytest tests/tfex` | 277 passed | 277 passed | ✅ match |
| `pytest -m anti_repaint` | 12 passed | 12 passed, 265 deselected | ✅ match |
| `ruff check .` | pass | All checks passed | ✅ match |
| `ruff format --check .` | 73 formatted | 73 files already formatted | ✅ match |
| `mypy .` | 71 files, no issues | Success, 71 source files | ✅ match |

**Baseline intact. No test was failing, so no investigation or repair was required, and no
test was weakened.** Implementation of the gate proceeded from here.

## Toolchain

| Component | Version |
| --- | --- |
| OS | Windows 11 Home 10.0.26100 |
| git | 2.54.0.windows.1 |
| uv | 0.11.14 (3fdfdc7d4 2026-05-12, x86_64-pc-windows-msvc) |
| CPython | 3.12.13 (uv-managed) |
| pytest | 9.1.1 |
| ruff | 0.16.4 |
| mypy | 2.3.1 |
| pydantic | 2.13.4 |
| PyYAML | 6.0.3 |
| tzdata | 2026.3 |

Note on `python`: the interpreter on `PATH` is the Microsoft Store alias stub and exits 49.
All commands run through `uv run` from `backend/`, as recorded in
`docs/tfex_architecture.md` §1.

## Re-running this verification

```bash
cd backend
uv run pytest tests/tfex
uv run pytest -m anti_repaint
uv run pytest -m real_market_data      # added by this gate
uv run ruff check .
uv run ruff format --check .
uv run mypy .
```
