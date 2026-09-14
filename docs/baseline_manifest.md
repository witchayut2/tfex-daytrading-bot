# Baseline Manifest (PART B)

Durable identification of the verified TFEX-0 / TFEX-1 state, recorded before the
data-readiness gate modified anything.

- **UTC timestamp:** 2026-08-23T23:16:03Z
- **Repository:** `C:\apps7 tfex\TFEX_ClaudeCode_Starter`

## Current-state note — 2026-09-14

This note updates repository state without rewriting the historical baseline record below.
The baseline commit now exists as `0a5daae`. The repository is on branch `main`, Git identity
is configured locally, and status commit `fb7cdc2` was HEAD before this readiness
re-evaluation. The index and working tree were clean at the start of this task. Post-baseline
data-readiness, dormant risk, and research-protocol work is preserved in later commits.

The latest verified state has 499 TFEX tests passing with 1 optional SDK check skipped,
22 anti-repaint tests passing, and 20 real-market-data tests passing across the immutable
four-day parent and five-day extended dataset. Ruff is clean across 108 files and strict
mypy succeeds over 105 source files. Canonical current status and QA live in
`docs/development_status.md`.

Everything from **Git state** onward is the original baseline-time evidence. Statements that
identity or the baseline commit was blocked describe that historical moment, not current Git
state.

## Git state

| Item | Value |
| --- | --- |
| `.git` existed before this gate | **No** |
| Action taken | `git init` (branch `master`) |
| Files staged | **85** |
| **Baseline tree hash** | **`4b7cb1f697a97d9bc625c0b26607e30b7bc5f3dc`** |
| Baseline commit | **NOT CREATED** — see blocker below |

### BASELINE COMMIT BLOCKED

```text
BASELINE COMMIT BLOCKED:
git user.name / user.email not configured
```

Checked and empty at every scope:

```text
git config user.name           -> (empty)
git config user.email          -> (empty)
git config --global user.name  -> (empty)
git config --global user.email -> (empty)
```

No name or email was invented, and global Git configuration was not modified.

**What was done instead.** The repository was initialised and the complete verified baseline
was staged, then `git write-tree` was used to record an immutable tree object:

```text
4b7cb1f697a97d9bc625c0b26607e30b7bc5f3dc
```

A tree hash needs no author identity, so the baseline is durably identified and content-
addressable even without a commit. It can be inspected at any time:

```bash
git ls-tree -r 4b7cb1f697a97d9bc625c0b26607e30b7bc5f3dc
```

**Operator action to convert it into a real commit** (run from the repository root; these set
the identity *locally*, not globally):

```bash
git config user.name  "Your Name"
git config user.email "you@example.com"
git commit -m "baseline: verified TFEX-0 and TFEX-1 foundation"
```

The staged index still holds exactly the baseline tree, so this produces a commit whose tree
is `4b7cb1f6…` provided it is run before staging any later work. If the index has already
moved on, recover the baseline explicitly:

```bash
git commit-tree 4b7cb1f697a97d9bc625c0b26607e30b7bc5f3dc \
  -m "baseline: verified TFEX-0 and TFEX-1 foundation"
```

## What the baseline tree contains

The state in which all of the following were true simultaneously:

| Check | Result |
| --- | --- |
| `uv run pytest tests/tfex` | 277 passed |
| `uv run pytest -m anti_repaint` | 12 passed, 265 deselected |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 73 files already formatted |
| `uv run mypy .` | Success — no issues in 71 source files |

Full evidence: `docs/data_readiness_baseline.md`.

The tree contains **no holiday data and no market data** — the TFEX-1 delivery deliberately
shipped neither. Everything the gate imports afterwards is therefore cleanly separable from
the baseline.

## Toolchain at baseline

| Component | Version |
| --- | --- |
| OS | Windows 11 Home 10.0.26100 |
| git | 2.54.0.windows.1 |
| uv | 0.11.14 |
| CPython | 3.12.13 (uv-managed) |
| pytest | 9.1.1 |
| ruff | 0.16.4 |
| mypy | 2.3.1 |
| pydantic | 2.13.4 |
| PyYAML | 6.0.3 |
| tzdata | 2026.3 |

## Index state after the gate

The index was **deliberately left holding the baseline tree**. Verified after all gate work:

```text
$ git write-tree
4b7cb1f697a97d9bc625c0b26607e30b7bc5f3dc

staged (baseline):        85 files
modified vs index (gate): 19 files
untracked (gate):         35 files
```

So the recommended commit order, once identity is configured, is:

```bash
git commit -m "baseline: verified TFEX-0 and TFEX-1 foundation"   # the staged baseline
git add -A
git commit -m "data-readiness gate: real TFEX calendar, fee semantics, market-data validator"
```

Committing the baseline first keeps the two states separable in history, which is the whole
point of recording the tree before touching anything.

## Changes made after the baseline tree was recorded

1. `.gitattributes` added — `* text=auto eol=lf` so blob checksums are stable across
   machines, and raw source captures under `data/tfex/official/**/raw.*` and
   `data/tfex/historical/raw/**` are marked binary so nothing rewrites them. Repository
   hygiene only; no source or test file was touched.
2. Everything else recorded in `docs/tfex_data_readiness_gate.md`.
