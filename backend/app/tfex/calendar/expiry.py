"""Last-trading-day and expiry resolution.

Section 3 states the rule: the last trading day is *"the business day immediately before
the last business day of the contract month"*, and trading ceases at 16:30 that day.

"Business day" is meaningless without the official holiday set, so this module cannot
answer anything for a year that has not been imported — it raises instead. Where the
exchange has published the date directly, the published date wins over our reading of the
rule, and the model records which of the two was used.
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.tfex.calendar.holiday_loader import HolidayStore
from app.tfex.calendar.models import CalendarOverrideKind, ContractExpiry, LastTradingDaySource
from app.tfex.calendar.trading_day import TradingDayCalculator
from app.tfex.config import TfexConfig
from app.tfex.errors import CalendarDataInvalidError

__all__ = ["ExpiryResolver"]

_MINIMUM_TRADING_DAYS_IN_MONTH = 2


class ExpiryResolver:
    """Resolves the last trading day of a contract month, and how we know it."""

    def __init__(
        self,
        config: TfexConfig,
        store: HolidayStore,
        trading_days: TradingDayCalculator,
    ) -> None:
        self._config = config
        self._store = store
        self._trading_days = trading_days
        self._tz = ZoneInfo(config.market.timezone)

    def resolve(
        self, contract_year: int, contract_month: int, *, resolved_at: datetime
    ) -> ContractExpiry:
        """Resolve expiry facts for one contract month.

        Precedence: approved administrative override, then the exchange-published product
        calendar, then the derived rule.
        """
        if resolved_at.tzinfo is None:
            raise ValueError("resolved_at must be timezone-aware")

        year_data = self._store.year(contract_year)
        last_trading_date, source = self._resolve_date(contract_year, contract_month)

        # Whatever the source, the date has to be a real trading day. A published date that
        # lands on a holiday means our holiday import and the exchange disagree, and that
        # must be investigated, not averaged over.
        if not self._trading_days.is_trading_day(last_trading_date):
            raise CalendarDataInvalidError(
                f"resolved last trading day {last_trading_date.isoformat()} for "
                f"{contract_year}-{contract_month:02d} (source {source}) is not a trading day "
                f"in the imported calendar; reconcile the holiday data with the exchange"
            )

        last_trading_time = self._cessation_time(last_trading_date)
        fingerprint = year_data.provenance.fingerprint or "unverified"

        return ContractExpiry(
            contract_year=contract_year,
            contract_month=contract_month,
            last_trading_date=last_trading_date,
            last_trading_time=last_trading_time,
            last_trading_timestamp=datetime.combine(
                last_trading_date, last_trading_time, tzinfo=self._tz
            ),
            expiry_date=last_trading_date,
            source=source,
            calendar_version=f"{self._config.metadata.version}/{contract_year}:{fingerprint}",
            resolved_at=resolved_at,
        )

    # --- internals --------------------------------------------------------------------

    def _resolve_date(
        self, contract_year: int, contract_month: int
    ) -> tuple[date, LastTradingDaySource]:
        year_data = self._store.year(contract_year)

        for override in year_data.effective_overrides:
            if (
                override.kind is CalendarOverrideKind.SET_LAST_TRADING_DAY
                and override.contract_year == contract_year
                and override.contract_month == contract_month
                and override.last_trading_date is not None
            ):
                return override.last_trading_date, LastTradingDaySource.ADMIN_OVERRIDE

        for published in year_data.published_contract_dates:
            if (
                published.contract_year == contract_year
                and published.contract_month == contract_month
            ):
                return published.last_trading_date, LastTradingDaySource.EXCHANGE_PUBLISHED

        if self._config.expiry.require_published_last_trading_day:
            raise CalendarDataInvalidError(
                f"no exchange-published last trading day for {contract_year}-"
                f"{contract_month:02d}, and expiry.require_published_last_trading_day is set"
            )

        month_trading_days = self._trading_days.trading_days_in_month(contract_year, contract_month)
        if len(month_trading_days) < _MINIMUM_TRADING_DAYS_IN_MONTH:
            raise CalendarDataInvalidError(
                f"{contract_year}-{contract_month:02d} has only {len(month_trading_days)} trading "
                f"day(s) in the imported calendar; the last-trading-day rule needs at least "
                f"{_MINIMUM_TRADING_DAYS_IN_MONTH}. This almost certainly means the holiday data "
                f"is wrong."
            )
        # "the business day immediately before the last business day of the contract month"
        return month_trading_days[-2], LastTradingDaySource.DERIVED_RULE

    def _cessation_time(self, last_trading_date: date) -> time:
        """16:30 by default, or earlier if an early close was announced for that day."""
        cessation = self._config.expiry.last_trading_day_cessation_time
        early_close = self._trading_days.afternoon_close_override(last_trading_date)
        if early_close is not None and early_close < cessation:
            return early_close
        return cessation
