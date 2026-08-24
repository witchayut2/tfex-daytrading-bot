"""Validate a real market-data file before it is allowed anywhere near replay.

`CLAUDE_TFEX.md` section 28 lists the conditions that must hold before strategy processing,
and says plainly what happens when they do not: *"paper/live order mode must stop on critical
data-quality failure"*. This module is where that stopping is decided.

Every check keeps its own status. A single aggregate score would let a contract-identity
failure hide behind nine passes, and contract identity is precisely the thing that must never
be wrong (section 30: datasets must preserve contract identity).

Two behaviours are worth stating up front because they look like bugs otherwise:

* **Anomalous rows are reported, never deleted.** A validator that silently drops the rows it
  dislikes produces a clean dataset that no longer matches the file it came from.
* **A zero-volume bar is not treated as missing data.** TFEX has quiet minutes. Conflating
  "nobody traded" with "the feed lost data" would either hide real gaps or invent fake ones.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.tfex.calendar.models import ContractExpiry, LastTradingDaySource
from app.tfex.calendar.service import TradingCalendar
from app.tfex.config import TfexConfig
from app.tfex.contracts.metadata import ContractResolver
from app.tfex.errors import TfexError
from app.tfex.marketdata.models import (
    Bar,
    BarInterval,
    CheckResult,
    CheckStatus,
    DatasetManifest,
    Finding,
    MissingRange,
    MissingRangeKind,
    SessionMembership,
    ValidationReport,
)
from app.tfex.sessions.boundaries import DaySessionPlan, SessionState
from app.tfex.sessions.engine import SessionEngine
from app.tfex.sessions.midday_break import spans_midday_break

__all__ = [
    "VALIDATOR_VERSION",
    "MarketDataValidator",
    "ValidationSettings",
]

VALIDATOR_VERSION = "tfex-market-data-validator/1"

_BLOCKED_UNVERIFIED_CONTRACT_CALENDAR = "BLOCKED_UNVERIFIED_CONTRACT_CALENDAR"

#: Sanity bounds on a timestamp. Outside these a date is a parsing artefact, not a bar.
_EARLIEST_PLAUSIBLE_YEAR = 2006
_LATEST_PLAUSIBLE_YEARS_AHEAD = 2


@dataclass(frozen=True, slots=True)
class ValidationSettings:
    """Thresholds. Research defaults, not exchange rules — every one is arguable."""

    possible_no_trade_max_bars: int = 2
    """A gap this short inside a session is more likely a quiet market than lost data."""

    source_data_gap_max_bars: int = 15
    """Beyond this, a gap is critical rather than merely reportable."""

    require_published_contract_calendar: bool = True
    """PART R: without a verified contract calendar the validator may not return a pass."""

    max_findings_per_check: int = 200
    """Findings are for humans. Ten thousand identical ones help nobody."""


class MarketDataValidator:
    """Runs every data-quality check over one contract's bars."""

    def __init__(
        self,
        config: TfexConfig,
        calendar: TradingCalendar,
        *,
        settings: ValidationSettings | None = None,
    ) -> None:
        self._config = config
        self._calendar = calendar
        self._engine = SessionEngine(config, calendar)
        self._resolver = ContractResolver(config, calendar)
        self._settings = settings or ValidationSettings()

    # --- entry point ------------------------------------------------------------------

    def validate(
        self,
        bars: list[Bar],
        *,
        symbol: str,
        interval: BarInterval,
        file_path: str,
        sha256: str,
        manifest: DatasetManifest | None = None,
        load_findings: tuple[Finding, ...] = (),
        row_count: int | None = None,
    ) -> ValidationReport:
        symbol = symbol.strip().upper()
        ordered = sorted(bars, key=lambda b: (b.timestamp, b.line_number))
        expiry = self._resolve_expiry(symbol)

        checks = [
            self._check_provenance(manifest),
            self._check_parsing(load_findings, row_count if row_count is not None else len(bars)),
            self._check_contract_identity(bars, symbol),
            self._check_timestamps(bars),
            self._check_duplicates(ordered),
            self._check_ohlc(bars),
            self._check_tick_size(bars),
            self._check_volume(bars),
            self._check_sessions(ordered, interval, expiry),
            self._check_missing_bars(ordered, interval, expiry),
            self._check_expiry(ordered, symbol, expiry),
        ]

        return ValidationReport(
            dataset_id=manifest.dataset_id if manifest else f"{symbol}-{interval.value}",
            symbol=symbol,
            interval=interval,
            file_path=file_path,
            sha256=sha256,
            row_count=len(bars),
            checks=tuple(checks),
            validator_version=VALIDATOR_VERSION,
            generated_at=datetime.now(UTC),
            manifest=manifest,
        )

    # --- helpers ----------------------------------------------------------------------

    def _resolve_expiry(self, symbol: str) -> ContractExpiry | None:
        try:
            parsed = self._resolver.parse(symbol, reference_date=date.today())
            return self._calendar.contract_expiry(parsed.contract_year, parsed.contract_month)
        except TfexError:
            return None

    def _cap(self, findings: list[Finding]) -> tuple[Finding, ...]:
        limit = self._settings.max_findings_per_check
        if len(findings) <= limit:
            return tuple(findings)
        return (
            *findings[:limit],
            Finding(f"... {len(findings) - limit} further findings suppressed"),
        )

    def _plan(self, day: date, expiry: ContractExpiry | None) -> DaySessionPlan | None:
        try:
            return self._engine.plan_for(day, expiry=expiry)
        except TfexError:
            return None

    # --- PART T: provenance -----------------------------------------------------------

    def _check_provenance(self, manifest: DatasetManifest | None) -> CheckResult:
        if manifest is None:
            return CheckResult(
                "provenance",
                CheckStatus.FAIL,
                "no dataset manifest; a backtest that cannot name its input is not reproducible",
            )
        findings: list[Finding] = []
        if manifest.retrieved_at is None:
            findings.append(Finding("manifest has no retrieved_at"))
        if not manifest.license:
            findings.append(Finding("manifest has no licence recorded"))
        if manifest.authority is None:
            findings.append(Finding("manifest has no authority recorded"))

        if manifest.synthetic:
            return CheckResult(
                "provenance",
                CheckStatus.WARNING,
                "SYNTHETIC dataset - valid for unit tests and fault injection, never for "
                "TFEX-2 acceptance",
                self._cap(findings),
                {"synthetic": True, "source": manifest.source, "real_market_data": False},
            )
        if not manifest.source_is_verified:
            return CheckResult(
                "provenance",
                CheckStatus.WARNING,
                f"source is still the placeholder {manifest.source!r}; until it names a real "
                f"source this dataset does not count as real market data",
                self._cap(findings),
                {"synthetic": False, "source": manifest.source, "real_market_data": False},
            )
        status = CheckStatus.WARNING if findings else CheckStatus.PASS
        return CheckResult(
            "provenance",
            status,
            f"real market data from {manifest.source}",
            self._cap(findings),
            {
                "synthetic": False,
                "source": manifest.source,
                "license": manifest.license,
                "real_market_data": True,
            },
        )

    def _check_parsing(self, load_findings: tuple[Finding, ...], row_count: int) -> CheckResult:
        if load_findings:
            return CheckResult(
                "row_parsing",
                CheckStatus.FAIL,
                f"{len(load_findings)} of {row_count} row(s) could not be parsed",
                self._cap(list(load_findings)),
                {"rows": row_count, "unparseable": len(load_findings)},
            )
        return CheckResult(
            "row_parsing",
            CheckStatus.PASS,
            f"all {row_count} row(s) parsed",
            (),
            {"rows": row_count},
        )

    # --- PART Q: contract identity ----------------------------------------------------

    def _check_contract_identity(self, bars: list[Bar], symbol: str) -> CheckResult:
        if not bars:
            return CheckResult("contract_identity", CheckStatus.FAIL, "the file contains no bars")

        symbols = {bar.symbol for bar in bars}
        if len(symbols) > 1:
            offenders = [b for b in bars if b.symbol != symbol][:20]
            return CheckResult(
                "contract_identity",
                CheckStatus.FAIL,
                f"the file mixes {len(symbols)} contracts {sorted(symbols)}; a candle that "
                f"mixes contracts is meaningless and must be split into raw per-contract "
                f"datasets first",
                self._cap(
                    [Finding(f"symbol {b.symbol}", b.line_number, b.timestamp) for b in offenders]
                ),
                {"symbols": sorted(symbols)},
            )

        found = symbols.pop()
        if found != symbol:
            return CheckResult(
                "contract_identity",
                CheckStatus.FAIL,
                f"the file contains {found} but {symbol} was declared",
                (),
                {"declared": symbol, "found": found},
            )

        try:
            parsed = self._resolver.parse(symbol, reference_date=date.today())
        except TfexError as exc:
            return CheckResult(
                "contract_identity",
                CheckStatus.FAIL,
                f"{symbol} is not a valid SET50 futures contract symbol: {exc}",
            )
        return CheckResult(
            "contract_identity",
            CheckStatus.PASS,
            f"every bar belongs to {symbol} ({parsed.contract_year}-{parsed.contract_month:02d})",
            (),
            {"symbol": symbol, "contract_month": parsed.contract_month_key},
        )

    # --- PART K: timestamps -----------------------------------------------------------

    def _check_timestamps(self, bars: list[Bar]) -> CheckResult:
        if not bars:
            return CheckResult("timestamps", CheckStatus.FAIL, "no bars to check")

        findings: list[Finding] = []
        naive = [b for b in bars if b.timestamp.tzinfo is None]
        findings += [
            Finding("timestamp is not timezone-aware", b.line_number, b.timestamp)
            for b in naive[:20]
        ]

        latest_year = date.today().year + _LATEST_PLAUSIBLE_YEARS_AHEAD
        for bar in bars:
            if not _EARLIEST_PLAUSIBLE_YEAR <= bar.timestamp.year <= latest_year:
                findings.append(
                    Finding(
                        f"implausible date {bar.timestamp.date().isoformat()} (outside "
                        f"{_EARLIEST_PLAUSIBLE_YEAR}-{latest_year})",
                        bar.line_number,
                        bar.timestamp,
                    )
                )

        out_of_order = 0
        previous: datetime | None = None
        for bar in bars:
            if previous is not None and bar.timestamp < previous:
                out_of_order += 1
                if out_of_order <= 20:
                    findings.append(
                        Finding(
                            f"timestamp {bar.timestamp.isoformat()} precedes the previous row "
                            f"{previous.isoformat()}",
                            bar.line_number,
                            bar.timestamp,
                        )
                    )
            previous = bar.timestamp

        zones = {str(b.timestamp.tzinfo) for b in bars if b.timestamp.tzinfo is not None}
        status = CheckStatus.FAIL if findings else CheckStatus.PASS
        return CheckResult(
            "timestamps",
            status,
            (
                f"{len(bars):,} timestamps, {len(zones)} timezone(s) {sorted(zones)}, "
                f"{out_of_order} out of order"
            ),
            self._cap(findings),
            {
                "first": bars[0].timestamp.isoformat(),
                "last": bars[-1].timestamp.isoformat(),
                "timezones": sorted(zones),
                "out_of_order": out_of_order,
            },
        )

    # --- PART O: duplicates -----------------------------------------------------------

    def _check_duplicates(self, ordered: list[Bar]) -> CheckResult:
        by_key: dict[tuple[str, datetime], list[Bar]] = defaultdict(list)
        for bar in ordered:
            by_key[(bar.symbol, bar.timestamp)].append(bar)

        exact = 0
        conflicting: list[Finding] = []
        for (sym, stamp), group in by_key.items():
            if len(group) == 1:
                continue
            signatures = {(b.open, b.high, b.low, b.close, b.volume) for b in group}
            if len(signatures) == 1:
                exact += len(group) - 1
            else:
                conflicting.append(
                    Finding(
                        f"conflicting duplicate for {sym} at {stamp.isoformat()}: "
                        f"{len(signatures)} different OHLCV values on {len(group)} rows",
                        group[0].line_number,
                        stamp,
                    )
                )

        if conflicting:
            return CheckResult(
                "duplicates",
                CheckStatus.FAIL,
                f"{len(conflicting)} conflicting duplicate timestamp(s); these must never be "
                f"silently deduplicated - the source disagrees with itself",
                self._cap(conflicting),
                {"conflicting": len(conflicting), "exact": exact},
            )
        if exact:
            return CheckResult(
                "duplicates",
                CheckStatus.WARNING,
                f"{exact} exact duplicate row(s); harmless but the source is repeating itself",
                (),
                {"conflicting": 0, "exact": exact},
            )
        return CheckResult("duplicates", CheckStatus.PASS, "no duplicate timestamps")

    # --- PART M: OHLC -----------------------------------------------------------------

    def _check_ohlc(self, bars: list[Bar]) -> CheckResult:
        findings: list[Finding] = []
        for bar in bars:
            problems: list[str] = []
            if bar.high < bar.low:
                problems.append(f"high {bar.high} < low {bar.low}")
            if bar.high < bar.open:
                problems.append(f"high {bar.high} < open {bar.open}")
            if bar.high < bar.close:
                problems.append(f"high {bar.high} < close {bar.close}")
            if bar.low > bar.open:
                problems.append(f"low {bar.low} > open {bar.open}")
            if bar.low > bar.close:
                problems.append(f"low {bar.low} > close {bar.close}")
            for name, value in (
                ("open", bar.open),
                ("high", bar.high),
                ("low", bar.low),
                ("close", bar.close),
            ):
                if value <= 0:
                    problems.append(f"{name} {value} is not positive")
            if problems:
                findings.append(Finding("; ".join(problems), bar.line_number, bar.timestamp))

        if findings:
            return CheckResult(
                "ohlc",
                CheckStatus.FAIL,
                f"{len(findings)} bar(s) violate OHLC consistency",
                self._cap(findings),
                {"invalid_bars": len(findings)},
            )
        return CheckResult(
            "ohlc", CheckStatus.PASS, f"{len(bars):,} bars are internally consistent"
        )

    def _check_tick_size(self, bars: list[Bar]) -> CheckResult:
        tick = self._config.contract.tick_size_points
        findings: list[Finding] = []
        misaligned = 0
        for bar in bars:
            bad = [
                f"{name}={value}"
                for name, value in (
                    ("open", bar.open),
                    ("high", bar.high),
                    ("low", bar.low),
                    ("close", bar.close),
                )
                if value % tick != 0
            ]
            if bad:
                misaligned += 1
                findings.append(
                    Finding(
                        f"price(s) not on the {tick} point tick grid: {', '.join(bad)}",
                        bar.line_number,
                        bar.timestamp,
                    )
                )
        if findings:
            return CheckResult(
                "tick_size",
                CheckStatus.WARNING,
                f"{misaligned} bar(s) carry prices off the {tick} point grid; check whether "
                f"the source is averaging or rounding",
                self._cap(findings),
                {"tick_size": str(tick), "misaligned_bars": misaligned},
            )
        return CheckResult(
            "tick_size", CheckStatus.PASS, f"every price sits on the {tick} point tick grid"
        )

    # --- PART N: volume ---------------------------------------------------------------

    def _check_volume(self, bars: list[Bar]) -> CheckResult:
        negative = [b for b in bars if b.volume < 0]
        zero_volume = sum(1 for b in bars if b.volume == 0)
        if negative:
            return CheckResult(
                "volume",
                CheckStatus.FAIL,
                f"{len(negative)} bar(s) report negative volume",
                self._cap(
                    [Finding(f"volume={b.volume}", b.line_number, b.timestamp) for b in negative]
                ),
                {"negative": len(negative)},
            )
        total = sum(b.volume for b in bars)
        return CheckResult(
            "volume",
            CheckStatus.PASS,
            (
                f"total volume {total:,}; {zero_volume:,} zero-volume bar(s), treated as quiet "
                f"minutes rather than missing data"
            ),
            (),
            {"total_volume": total, "zero_volume_bars": zero_volume},
        )

    # --- PART L: sessions -------------------------------------------------------------

    def _check_sessions(
        self, ordered: list[Bar], interval: BarInterval, expiry: ContractExpiry | None
    ) -> CheckResult:
        counts: dict[SessionMembership, int] = defaultdict(int)
        findings: list[Finding] = []
        break_crossings = 0
        bar_length = timedelta(minutes=interval.minutes)

        for bar in ordered:
            plan = self._plan(bar.trading_date, expiry)
            membership = self._membership(bar, plan, expiry)
            counts[membership] += 1

            if membership is not SessionMembership.VALID_CONTINUOUS_SESSION:
                if counts[membership] <= 25:
                    findings.append(Finding(f"{membership}", bar.line_number, bar.timestamp))
            elif plan is not None and spans_midday_break(
                plan, bar.timestamp, bar.timestamp + bar_length
            ):
                break_crossings += 1
                if break_crossings <= 25:
                    findings.append(
                        Finding(
                            "bar spans the midday break, which section 27 forbids",
                            bar.line_number,
                            bar.timestamp,
                        )
                    )

        details = {membership.value: count for membership, count in counts.items()}
        details["midday_break_crossings"] = break_crossings

        fatal = (
            counts[SessionMembership.UNKNOWN]
            + counts[SessionMembership.NON_TRADING_DAY]
            + counts[SessionMembership.LAST_TRADING_DAY_AFTER_CUTOFF]
            + break_crossings
        )
        soft = (
            counts[SessionMembership.PREOPEN_DATA]
            + counts[SessionMembership.MIDDAY_BREAK_DATA]
            + counts[SessionMembership.OUTSIDE_SESSION]
        )
        valid = counts[SessionMembership.VALID_CONTINUOUS_SESSION]

        if fatal:
            status = CheckStatus.FAIL
            summary = (
                f"{fatal} bar(s) cannot belong to a tradable session "
                f"(unknown calendar, non-trading day, after cessation, or crossing the break)"
            )
        elif soft:
            status = CheckStatus.WARNING
            summary = (
                f"{valid:,} continuous-session bars; {soft} outside it "
                f"(pre-open/break/after close) - reported, not deleted"
            )
        else:
            status = CheckStatus.PASS
            summary = f"all {valid:,} bars fall inside a continuous trading session"

        return CheckResult("session_boundaries", status, summary, self._cap(findings), details)

    def _membership(
        self, bar: Bar, plan: DaySessionPlan | None, expiry: ContractExpiry | None
    ) -> SessionMembership:
        if plan is None:
            return SessionMembership.UNKNOWN
        if not plan.is_trading_day:
            return SessionMembership.NON_TRADING_DAY
        if (
            expiry is not None
            and bar.trading_date == expiry.last_trading_date
            and bar.timestamp >= expiry.last_trading_timestamp
        ):
            return SessionMembership.LAST_TRADING_DAY_AFTER_CUTOFF

        states = plan.states_at(bar.timestamp)
        if SessionState.MORNING_PREOPEN in states or SessionState.AFTERNOON_PREOPEN in states:
            return SessionMembership.PREOPEN_DATA
        if SessionState.MIDDAY_BREAK in states:
            return SessionMembership.MIDDAY_BREAK_DATA
        if plan.is_executable(bar.timestamp):
            return SessionMembership.VALID_CONTINUOUS_SESSION
        return SessionMembership.OUTSIDE_SESSION

    # --- PART P: missing bars ---------------------------------------------------------

    def _check_missing_bars(
        self, ordered: list[Bar], interval: BarInterval, expiry: ContractExpiry | None
    ) -> CheckResult:
        if not ordered:
            return CheckResult("missing_bars", CheckStatus.FAIL, "no bars to check")

        first, last = ordered[0].timestamp, ordered[-1].timestamp
        observed = {bar.timestamp for bar in ordered}
        step = timedelta(minutes=interval.minutes)

        expected: list[datetime] = []
        day = first.date()
        while day <= last.date():
            plan = self._plan(day, expiry)
            if plan is None:
                return CheckResult(
                    "missing_bars",
                    CheckStatus.BLOCKED,
                    f"the trading calendar cannot answer for {day.isoformat()}; import that "
                    f"year before validating data that spans it",
                    (),
                    {"unresolved_date": day.isoformat()},
                )
            if plan.is_trading_day:
                expected.extend(self._expected_slots(plan, step))
            day += timedelta(days=1)

        # Only judge the interior: a dataset legitimately starts and ends mid-session.
        missing = [slot for slot in expected if first <= slot <= last and slot not in observed]
        ranges = self._group_missing(missing, step)

        critical = [r for r in ranges if r.kind is MissingRangeKind.CRITICAL_DATA_GAP]
        source_gaps = [r for r in ranges if r.kind is MissingRangeKind.SOURCE_DATA_GAP]
        quiet = [r for r in ranges if r.kind is MissingRangeKind.POSSIBLE_NO_TRADE]
        longest = max((r.bar_count for r in ranges), default=0)

        details = {
            "expected_bars": len(expected),
            "missing_bar_count": len(missing),
            "longest_missing_run": longest,
            "critical_gaps": len(critical),
            "source_data_gaps": len(source_gaps),
            "possible_no_trade": len(quiet),
            "missing_ranges": [r.describe() for r in ranges[:50]],
        }

        if critical:
            return CheckResult(
                "missing_bars",
                CheckStatus.FAIL,
                f"{len(critical)} critical gap(s), longest {longest} bars; the dataset is not "
                f"complete enough for replay",
                self._cap([Finding(r.describe(), timestamp=r.start) for r in critical]),
                details,
            )
        if source_gaps:
            return CheckResult(
                "missing_bars",
                CheckStatus.WARNING,
                f"{len(source_gaps)} source gap(s) and {len(quiet)} short quiet run(s); "
                f"{len(missing)} of {len(expected)} expected bars absent",
                self._cap([Finding(r.describe(), timestamp=r.start) for r in source_gaps]),
                details,
            )
        return CheckResult(
            "missing_bars",
            CheckStatus.PASS,
            (
                f"{len(missing)} of {len(expected):,} expected bars absent, all in runs of "
                f"{self._settings.possible_no_trade_max_bars} or fewer (quiet minutes)"
            ),
            (),
            details,
        )

    def _expected_slots(self, plan: DaySessionPlan, step: timedelta) -> list[datetime]:
        """Bar open times a complete feed would carry, per continuous session.

        Built per session, never across the break: section 10 forbids a bar spanning it, so
        the grid restarts at the afternoon open rather than continuing through lunch.
        """
        slots: list[datetime] = []
        for open_at, close_at in (
            (plan.morning_open_at, plan.morning_close_at),
            (plan.afternoon_open_at, plan.afternoon_close_at),
        ):
            if open_at is None or close_at is None:
                continue
            current = open_at
            while current + step <= close_at:
                slots.append(current)
                current += step
        return slots

    def _group_missing(self, missing: list[datetime], step: timedelta) -> list[MissingRange]:
        if not missing:
            return []
        ranges: list[MissingRange] = []
        run_start = missing[0]
        previous = missing[0]
        count = 1

        def close_run(start: datetime, end: datetime, length: int) -> MissingRange:
            if length <= self._settings.possible_no_trade_max_bars:
                kind = MissingRangeKind.POSSIBLE_NO_TRADE
            elif length <= self._settings.source_data_gap_max_bars:
                kind = MissingRangeKind.SOURCE_DATA_GAP
            else:
                kind = MissingRangeKind.CRITICAL_DATA_GAP
            return MissingRange(kind, start, end + step, length)

        for slot in missing[1:]:
            if slot - previous == step:
                count += 1
            else:
                ranges.append(close_run(run_start, previous, count))
                run_start = slot
                count = 1
            previous = slot
        ranges.append(close_run(run_start, previous, count))
        return ranges

    # --- PART R: expiry ---------------------------------------------------------------

    def _check_expiry(
        self, ordered: list[Bar], symbol: str, expiry: ContractExpiry | None
    ) -> CheckResult:
        if expiry is None:
            return CheckResult(
                "expiry",
                CheckStatus.BLOCKED,
                f"{_BLOCKED_UNVERIFIED_CONTRACT_CALENDAR}: expiry for {symbol} could not be "
                f"resolved; import the calendar year and the contract calendar first",
            )
        if (
            self._settings.require_published_contract_calendar
            and expiry.source is LastTradingDaySource.DERIVED_RULE
        ):
            return CheckResult(
                "expiry",
                CheckStatus.BLOCKED,
                f"{_BLOCKED_UNVERIFIED_CONTRACT_CALENDAR}: the last trading day for {symbol} "
                f"came from the derived rule, not the exchange-published calendar; run "
                f"scripts/import_tfex_contracts.py",
                (),
                {"expiry_source": expiry.source.value},
            )
        if not ordered:
            return CheckResult("expiry", CheckStatus.FAIL, "no bars to check")

        after_expiry = [b for b in ordered if b.trading_date > expiry.last_trading_date]
        after_cutoff = [
            b
            for b in ordered
            if b.trading_date == expiry.last_trading_date
            and b.timestamp >= expiry.last_trading_timestamp
        ]
        findings = [
            Finding("bar dated after the last trading day", b.line_number, b.timestamp)
            for b in after_expiry[:25]
        ] + [
            Finding(
                f"bar at or after cessation {expiry.last_trading_time.isoformat()}",
                b.line_number,
                b.timestamp,
            )
            for b in after_cutoff[:25]
        ]

        details = {
            "last_trading_date": expiry.last_trading_date.isoformat(),
            "last_trading_time": expiry.last_trading_time.isoformat(),
            "expiry_source": expiry.source.value,
            "rows_after_expiry": len(after_expiry),
            "rows_after_cutoff": len(after_cutoff),
        }
        if findings:
            return CheckResult(
                "expiry",
                CheckStatus.FAIL,
                f"{len(after_expiry)} row(s) after expiry and {len(after_cutoff)} at or after "
                f"cessation on the last trading day",
                self._cap(findings),
                details,
            )
        return CheckResult(
            "expiry",
            CheckStatus.PASS,
            (
                f"no rows past {expiry.last_trading_date.isoformat()} "
                f"{expiry.last_trading_time.isoformat()} [{expiry.source.value}]"
            ),
            (),
            details,
        )


def tick_aligned(value: Decimal, tick: Decimal) -> bool:
    """Public helper: is ``value`` an exact multiple of ``tick``?"""
    return value % tick == 0
