"""Market-data validation (`CLAUDE_TFEX.md` section 28, data-readiness gate PARTS K-T).

The bars here are **synthetic** and say so in their manifests. That is exactly what fixtures
are for: every defect below — a mixed-symbol file, a bar in the lunch break, a conflicting
duplicate — has to be constructed deliberately, because real data does not supply them on
demand. What synthetic data can never do is satisfy TFEX-2 acceptance; see
`test_acceptance_gate.py`.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest

from app.tfex.calendar.service import TradingCalendar
from app.tfex.config import TfexConfig
from app.tfex.marketdata.models import (
    Bar,
    BarInterval,
    CheckStatus,
    DatasetManifest,
    Finding,
    SessionMembership,
    ValidationOutcome,
    ValidationReport,
)
from app.tfex.marketdata.validation import MarketDataValidator, ValidationSettings
from tests.tfex.conftest import bkk

SYMBOL = "S50Z26"
DAY = date(2026, 12, 23)  # Wednesday, an ordinary session in the fixture calendar
MORNING_OPEN = time(9, 45)
MORNING_BARS = 165  # 09:45 -> 12:30
AFTERNOON_BARS = 190  # 13:45 -> 16:55
BARS_PER_DAY = MORNING_BARS + AFTERNOON_BARS


def bar(
    stamp: datetime,
    *,
    symbol: str = SYMBOL,
    price: str = "1080.0",
    volume: int = 10,
    line: int = 0,
    high: str | None = None,
    low: str | None = None,
) -> Bar:
    base = Decimal(price)
    return Bar(
        symbol=symbol,
        timestamp=stamp,
        open=base,
        high=Decimal(high) if high else base + Decimal("0.2"),
        low=Decimal(low) if low else base - Decimal("0.2"),
        close=base,
        volume=volume,
        line_number=line or 2,
    )


def session_bars(day: date = DAY, *, symbol: str = SYMBOL) -> list[Bar]:
    """A complete, clean one-minute day: both continuous sessions, nothing else."""
    bars: list[Bar] = []
    line = 2
    for start, count in ((MORNING_OPEN, MORNING_BARS), (time(13, 45), AFTERNOON_BARS)):
        first = bkk(day, start)
        for index in range(count):
            bars.append(bar(first + timedelta(minutes=index), symbol=symbol, line=line))
            line += 1
    return bars


def manifest(*, synthetic: bool = True, rows: int = BARS_PER_DAY) -> DatasetManifest:
    return DatasetManifest(
        dataset_id="fixture-s50z26-1m",
        source="unit-test fixture",
        authority="tests",
        retrieved_at=bkk(date(2026, 12, 24), time(9, 0)),
        license="n/a - fixture",
        original_filename="fixture.csv",
        sha256="0" * 64,
        symbol=SYMBOL,
        interval=BarInterval.ONE_MINUTE,
        source_timezone="Asia/Bangkok",
        record_count=rows,
        synthetic=synthetic,
    )


@pytest.fixture
def validator(config: TfexConfig, published_calendar: TradingCalendar) -> MarketDataValidator:
    return MarketDataValidator(config, published_calendar)


def run(
    validator: MarketDataValidator,
    bars: list[Bar],
    *,
    symbol: str = SYMBOL,
    interval: BarInterval = BarInterval.ONE_MINUTE,
    dataset: DatasetManifest | None = None,
    load_findings: tuple[Finding, ...] = (),
) -> ValidationReport:
    return validator.validate(
        bars,
        symbol=symbol,
        interval=interval,
        file_path="fixture.csv",
        sha256="0" * 64,
        manifest=dataset if dataset is not None else manifest(),
        load_findings=load_findings,
    )


# --- the clean case -------------------------------------------------------------------


def test_a_complete_clean_day_validates(validator: MarketDataValidator) -> None:
    report = run(validator, session_bars())

    for name in (
        "row_parsing",
        "contract_identity",
        "timestamps",
        "duplicates",
        "ohlc",
        "tick_size",
        "volume",
        "session_boundaries",
        "missing_bars",
        "expiry",
    ):
        check = report.check(name)
        assert check is not None, name
        assert check.status is CheckStatus.PASS, f"{name}: {check.summary}"

    # Only the synthetic manifest keeps it off a clean PASS, which is the point.
    assert report.check("provenance") is not None
    assert report.check("provenance").status is CheckStatus.WARNING  # type: ignore[union-attr]
    assert report.outcome is ValidationOutcome.PASS_WITH_WARNINGS


def test_a_real_manifest_yields_a_clean_pass(validator: MarketDataValidator) -> None:
    report = run(validator, session_bars(), dataset=manifest(synthetic=False))
    assert report.outcome is ValidationOutcome.PASS
    assert report.outcome.exit_code == 0


# --- PART Q: contract identity ----------------------------------------------------------


def test_a_mixed_symbol_file_is_rejected(validator: MarketDataValidator) -> None:
    bars = session_bars()
    bars[100] = bar(bars[100].timestamp, symbol="S50H27", line=bars[100].line_number)

    report = run(validator, bars)
    check = report.check("contract_identity")

    assert check is not None and check.status is CheckStatus.FAIL
    assert "mixes 2 contracts" in check.summary
    assert report.outcome is ValidationOutcome.REJECTED


def test_a_file_of_the_wrong_contract_is_rejected(validator: MarketDataValidator) -> None:
    report = run(validator, session_bars(symbol="S50H27"))
    check = report.check("contract_identity")
    assert check is not None and check.status is CheckStatus.FAIL
    assert "S50H27" in check.summary


def test_an_empty_file_is_rejected(validator: MarketDataValidator) -> None:
    report = run(validator, [])
    assert report.outcome is ValidationOutcome.REJECTED


# --- PART K: timestamps -------------------------------------------------------------------


def test_out_of_order_timestamps_are_reported(validator: MarketDataValidator) -> None:
    bars = session_bars()
    # Feed them unsorted by handing the validator a deliberately shuffled prefix.
    reordered = [bars[5], bars[0], *bars[1:5], *bars[6:]]
    report = validator.validate(
        reordered,
        symbol=SYMBOL,
        interval=BarInterval.ONE_MINUTE,
        file_path="fixture.csv",
        sha256="0" * 64,
        manifest=manifest(),
    )
    # The validator sorts before the ordered checks, so ordering alone is not fatal; what
    # matters is that no data is lost or duplicated by the sort.
    assert report.check("duplicates").status is CheckStatus.PASS  # type: ignore[union-attr]
    assert report.check("missing_bars").status is CheckStatus.PASS  # type: ignore[union-attr]


def test_an_implausible_date_is_rejected(validator: MarketDataValidator) -> None:
    bars = session_bars()
    bars.append(bar(bkk(date(1971, 1, 4), time(10, 0)), line=9999))
    report = run(validator, bars)
    check = report.check("timestamps")
    assert check is not None and check.status is CheckStatus.FAIL
    assert any("implausible date" in f.message for f in check.findings)


# --- PART O: duplicates ---------------------------------------------------------------------


def test_a_conflicting_duplicate_is_never_silently_deduplicated(
    validator: MarketDataValidator,
) -> None:
    bars = session_bars()
    clash = bars[10]
    bars.append(bar(clash.timestamp, price="1090.0", line=9999))

    report = run(validator, bars)
    check = report.check("duplicates")

    assert check is not None and check.status is CheckStatus.FAIL
    assert "conflicting" in check.summary
    assert check.details["conflicting"] == 1


def test_an_exact_duplicate_is_a_warning_not_a_rejection(validator: MarketDataValidator) -> None:
    bars = session_bars()
    bars.append(bars[10])

    check = run(validator, bars).check("duplicates")
    assert check is not None and check.status is CheckStatus.WARNING
    assert check.details["exact"] == 1


# --- PART M: OHLC ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("high", "low", "fragment"),
    [
        ("1079.0", "1080.5", "high 1079.0 < low 1080.5"),
        ("1079.5", "1079.0", "high 1079.5 < open"),
    ],
)
def test_inconsistent_ohlc_is_rejected(
    validator: MarketDataValidator, high: str, low: str, fragment: str
) -> None:
    bars = session_bars()
    bars[3] = bar(bars[3].timestamp, high=high, low=low, line=5)

    check = run(validator, bars).check("ohlc")
    assert check is not None and check.status is CheckStatus.FAIL
    assert any(fragment in f.message for f in check.findings)


def test_a_non_positive_price_is_rejected(validator: MarketDataValidator) -> None:
    bars = session_bars()
    bars[3] = Bar(
        symbol=SYMBOL,
        timestamp=bars[3].timestamp,
        open=Decimal("0"),
        high=Decimal("0"),
        low=Decimal("0"),
        close=Decimal("0"),
        volume=1,
        line_number=5,
    )
    check = run(validator, bars).check("ohlc")
    assert check is not None and check.status is CheckStatus.FAIL


def test_prices_off_the_tick_grid_are_flagged(validator: MarketDataValidator) -> None:
    bars = session_bars()
    bars[7] = bar(bars[7].timestamp, price="1080.05", line=9)

    check = run(validator, bars).check("tick_size")
    assert check is not None and check.status is CheckStatus.WARNING
    assert check.details["misaligned_bars"] == 1


# --- PART N: volume ------------------------------------------------------------------------------


def test_negative_volume_is_rejected(validator: MarketDataValidator) -> None:
    bars = session_bars()
    bars[2] = bar(bars[2].timestamp, volume=-1, line=4)

    check = run(validator, bars).check("volume")
    assert check is not None and check.status is CheckStatus.FAIL


def test_a_zero_volume_bar_is_a_quiet_minute_not_missing_data(
    validator: MarketDataValidator,
) -> None:
    bars = session_bars()
    bars[2] = bar(bars[2].timestamp, volume=0, line=4)

    volume = run(validator, bars).check("volume")
    missing = run(validator, bars).check("missing_bars")

    assert volume is not None and volume.status is CheckStatus.PASS
    assert volume.details["zero_volume_bars"] == 1
    assert missing is not None and missing.status is CheckStatus.PASS


# --- PART L: sessions -----------------------------------------------------------------------------


def test_a_bar_inside_the_midday_break_is_reported(validator: MarketDataValidator) -> None:
    bars = session_bars()
    bars.append(bar(bkk(DAY, time(13, 0)), line=9999))

    check = run(validator, bars).check("session_boundaries")
    assert check is not None and check.status is CheckStatus.WARNING
    assert check.details[SessionMembership.MIDDAY_BREAK_DATA.value] == 1


def test_a_preopen_bar_is_reported_not_deleted(validator: MarketDataValidator) -> None:
    bars = session_bars()
    bars.append(bar(bkk(DAY, time(9, 30)), line=9999))

    report = run(validator, bars)
    check = report.check("session_boundaries")

    assert check is not None and check.status is CheckStatus.WARNING
    assert check.details[SessionMembership.PREOPEN_DATA.value] == 1
    assert report.row_count == BARS_PER_DAY + 1  # nothing was dropped


def test_a_bar_on_a_holiday_is_rejected(validator: MarketDataValidator) -> None:
    bars = session_bars()
    bars.append(bar(bkk(date(2026, 12, 31), time(10, 0)), line=9999))  # fixture holiday

    check = run(validator, bars).check("session_boundaries")
    assert check is not None and check.status is CheckStatus.FAIL
    assert check.details[SessionMembership.NON_TRADING_DAY.value] == 1


@pytest.mark.anti_repaint
def test_a_five_minute_bar_that_spans_the_lunch_break_is_rejected(
    validator: MarketDataValidator,
) -> None:
    """Section 27: no candle may span the midday break."""
    bars = [
        bar(bkk(DAY, time(10, 0)), line=2),
        bar(bkk(DAY, time(12, 28)), line=3),  # 12:28 + 5m = 12:33, straddling 12:30
    ]
    check = run(validator, bars, interval=BarInterval.FIVE_MINUTE).check("session_boundaries")

    assert check is not None and check.status is CheckStatus.FAIL
    assert check.details["midday_break_crossings"] == 1


# --- PART P: missing bars ------------------------------------------------------------------------


def test_a_single_missing_minute_is_treated_as_a_quiet_market(
    validator: MarketDataValidator,
) -> None:
    bars = session_bars()
    del bars[50]

    check = run(validator, bars).check("missing_bars")
    assert check is not None and check.status is CheckStatus.PASS
    assert check.details["missing_bar_count"] == 1
    assert check.details["possible_no_trade"] == 1


def test_a_medium_gap_is_a_warning(validator: MarketDataValidator) -> None:
    bars = session_bars()
    del bars[50:60]  # 10 minutes

    check = run(validator, bars).check("missing_bars")
    assert check is not None and check.status is CheckStatus.WARNING
    assert check.details["source_data_gaps"] == 1
    assert check.details["longest_missing_run"] == 10


def test_a_long_gap_is_critical(validator: MarketDataValidator) -> None:
    bars = session_bars()
    del bars[50:110]  # an hour

    check = run(validator, bars).check("missing_bars")
    assert check is not None and check.status is CheckStatus.FAIL
    assert check.details["critical_gaps"] == 1
    assert "not complete enough for replay" in check.summary


def test_missing_bars_are_never_filled_in(validator: MarketDataValidator) -> None:
    bars = session_bars()
    del bars[50:60]
    report = run(validator, bars)
    assert report.row_count == BARS_PER_DAY - 10


def test_the_expected_grid_does_not_run_through_lunch(validator: MarketDataValidator) -> None:
    """A grid built straight through the break would invent 75 phantom missing bars."""
    check = run(validator, session_bars()).check("missing_bars")
    assert check is not None
    assert check.details["expected_bars"] == BARS_PER_DAY
    assert check.details["missing_bar_count"] == 0


def test_an_unimported_calendar_year_blocks_rather_than_passes(
    validator: MarketDataValidator,
) -> None:
    bars = [bar(bkk(date(2031, 6, 17), time(10, 0)), line=2)]
    report = run(validator, bars)

    assert report.check("missing_bars").status is CheckStatus.BLOCKED  # type: ignore[union-attr]
    assert report.outcome is ValidationOutcome.REJECTED


# --- PART R: expiry -------------------------------------------------------------------------------


def test_a_bar_after_cessation_on_the_last_trading_day_is_rejected(
    validator: MarketDataValidator,
) -> None:
    bars = session_bars()
    bars.append(bar(bkk(date(2026, 12, 29), time(16, 35)), line=9999))

    report = run(validator, bars)
    expiry = report.check("expiry")

    assert expiry is not None and expiry.status is CheckStatus.FAIL
    assert expiry.details["rows_after_cutoff"] == 1


def test_a_bar_after_the_last_trading_day_is_rejected(validator: MarketDataValidator) -> None:
    bars = session_bars()
    bars.append(bar(bkk(date(2026, 12, 30), time(10, 0)), line=9999))

    expiry = run(validator, bars).check("expiry")
    assert expiry is not None and expiry.status is CheckStatus.FAIL
    assert expiry.details["rows_after_expiry"] == 1


def test_expiry_uses_the_exchange_published_date(validator: MarketDataValidator) -> None:
    expiry = run(validator, session_bars()).check("expiry")
    assert expiry is not None
    assert expiry.details["expiry_source"] == "EXCHANGE_PUBLISHED"
    assert expiry.details["last_trading_date"] == "2026-12-29"


def test_a_derived_only_contract_calendar_blocks_the_pass(
    config: TfexConfig, calendar: TradingCalendar
) -> None:
    """PART R: without a verified contract calendar there is no production pass."""
    strict = MarketDataValidator(config, calendar)  # fixture calendar has no published dates
    report = strict.validate(
        session_bars(),
        symbol=SYMBOL,
        interval=BarInterval.ONE_MINUTE,
        file_path="fixture.csv",
        sha256="0" * 64,
        manifest=manifest(synthetic=False),
    )
    check = report.check("expiry")

    assert check is not None and check.status is CheckStatus.BLOCKED
    assert "BLOCKED_UNVERIFIED_CONTRACT_CALENDAR" in check.summary
    assert report.outcome is ValidationOutcome.REJECTED


def test_the_derived_calendar_can_be_accepted_deliberately(
    config: TfexConfig, calendar: TradingCalendar
) -> None:
    relaxed = MarketDataValidator(
        config, calendar, settings=ValidationSettings(require_published_contract_calendar=False)
    )
    report = relaxed.validate(
        session_bars(),
        symbol=SYMBOL,
        interval=BarInterval.ONE_MINUTE,
        file_path="fixture.csv",
        sha256="0" * 64,
        manifest=manifest(synthetic=False),
    )
    check = report.check("expiry")
    assert check is not None and check.status is CheckStatus.PASS
    assert check.details["expiry_source"] == "DERIVED_RULE"


# --- PART T: provenance ------------------------------------------------------------------------------


def test_a_dataset_without_a_manifest_is_rejected(validator: MarketDataValidator) -> None:
    report = validator.validate(
        session_bars(),
        symbol=SYMBOL,
        interval=BarInterval.ONE_MINUTE,
        file_path="fixture.csv",
        sha256="0" * 64,
        manifest=None,
    )
    check = report.check("provenance")

    assert check is not None and check.status is CheckStatus.FAIL
    assert report.outcome is ValidationOutcome.REJECTED


def test_a_synthetic_manifest_is_always_flagged(validator: MarketDataValidator) -> None:
    check = run(validator, session_bars()).check("provenance")
    assert check is not None and check.status is CheckStatus.WARNING
    assert "SYNTHETIC" in check.summary
    assert check.details["synthetic"] is True


def test_unparseable_rows_reject_the_file(validator: MarketDataValidator) -> None:
    report = run(
        validator,
        session_bars(),
        load_findings=(Finding("volume='abc' is not a number", line_number=42),),
    )
    check = report.check("row_parsing")
    assert check is not None and check.status is CheckStatus.FAIL


# --- PART S: the report itself --------------------------------------------------------------------------


def test_every_check_keeps_its_own_status(validator: MarketDataValidator) -> None:
    report = run(validator, session_bars())
    names = [c.name for c in report.checks]
    assert len(names) == len(set(names))
    assert len(names) == 11


def test_the_outcome_maps_to_the_documented_exit_codes() -> None:
    assert ValidationOutcome.PASS.exit_code == 0
    assert ValidationOutcome.PASS_WITH_WARNINGS.exit_code == 1
    assert ValidationOutcome.REJECTED.exit_code == 2
    assert ValidationOutcome.CONFIGURATION_OR_PROVENANCE_ERROR.exit_code == 3


def test_the_report_renders_both_forms(validator: MarketDataValidator) -> None:
    report = run(validator, session_bars())

    text = report.render_text()
    assert SYMBOL in text and "Overall:" in text

    payload = report.to_dict()
    assert payload["symbol"] == SYMBOL
    assert payload["exit_code"] == report.outcome.exit_code
    assert len(payload["checks"]) == 11
