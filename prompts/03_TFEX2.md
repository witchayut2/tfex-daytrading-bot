Read `AGENTS.md`, legacy specs, and all data-readiness docs.

Proceed only if:
- data-readiness gate = `READY_FOR_TFEX2`
- at least one real S50 1-minute raw-contract dataset passed validation

Implement TFEX-2 only:

1. canonical TFEX market-data domain
2. real raw-contract import path
3. deterministic replay
4. 1m -> 5m aggregation
5. 1m -> 15m aggregation
6. morning/afternoon session isolation
7. midday-break handling
8. full-day VWAP
9. morning VWAP
10. afternoon VWAP
11. morning OR5/OR15/OR30
12. afternoon OR5/OR15/OR30
13. previous-day/session snapshots
14. overnight gap
15. midday gap
16. data-quality gates
17. deterministic seek reconstruction
18. provenance propagation
19. real-market anti-repaint acceptance tests

Do not implement TFEX-3 strategy logic.
Do not implement live broker order submission.

Synthetic fixtures remain allowed for unit/adversarial tests but cannot satisfy real-data acceptance.

Run:
- `uv run pytest tests/tfex`
- `uv run pytest -m anti_repaint`
- `uv run pytest -m real_market_data`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy .`

Do not declare completion if real-market tests are skipped.
