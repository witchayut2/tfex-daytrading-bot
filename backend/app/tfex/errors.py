"""Typed error hierarchy for the TFEX specialization.

Every failure that can stop strategy processing has its own type so that callers can
distinguish "the data is not available yet" from "the data is wrong" from "the request
is not permitted". `CLAUDE_TFEX.md` section 28 requires order-capable modes to stop on
critical data-quality failures rather than continue with a default.
"""

from __future__ import annotations


class TfexError(Exception):
    """Base class for every TFEX-specific error."""


# --- configuration -------------------------------------------------------------------


class ConfigurationError(TfexError):
    """The TFEX configuration is missing, malformed, or internally inconsistent."""


class RealMarketDataValidationRequired(TfexError):
    """A milestone was declared complete on synthetic data alone.

    Fixtures prove the code does what its author expected. Only real SET50 futures data
    proves it survives quiet minutes, feed gaps, off-tick prints and the holidays nobody
    remembered.
    """


class FeeSemanticsError(TfexError):
    """A cost figure was used as something it is not.

    The specific case this exists for: the exchange fee published in the SET50 Index Futures
    contract specification is a **maximum** ("Maximum of THB 7 per contract per side"), not
    the amount actually charged. Deducting a cap from P&L as if it were an actual charge
    silently misstates every result, so the cap physically refuses to be used that way.
    """


class LiveTradingDisabledError(TfexError):
    """Something attempted to enable a real-money order route.

    No live route exists in this build. `CLAUDE.md` mandates paper trading by default and
    `CLAUDE_TFEX.md` section 32 forbids real orders until every validation gate passes.
    """


# --- metadata provenance -------------------------------------------------------------


class SourceRegistryError(TfexError):
    """The official-source registry is missing an entry or its record is invalid."""


class StaleMetadataError(TfexError):
    """Exchange metadata is older than its declared freshness window.

    Section 2: never silently continue with stale exchange metadata when expiry, session,
    or margin calculations depend on it.
    """


class UnverifiedMetadataError(TfexError):
    """Metadata was loaded but has not been verified against an official source."""


# --- calendar ------------------------------------------------------------------------


class CalendarError(TfexError):
    """Base class for trading-calendar failures."""


class CalendarDataUnavailableError(CalendarError):
    """Official calendar data for the requested year has not been loaded.

    Section 8: do not derive trading days only from weekdays. When the holiday set for a
    year is unknown, the calendar refuses to answer instead of guessing.
    """


class CalendarDataInvalidError(CalendarError):
    """A calendar data file failed schema or consistency validation."""


class NotATradingDayError(CalendarError):
    """A trading-day-only operation was requested for a non-trading date."""


# --- contracts -----------------------------------------------------------------------


class ContractError(TfexError):
    """Base class for contract identity and eligibility failures."""


class SymbolParseError(ContractError):
    """A contract symbol is malformed or describes an impossible contract."""


class ContractNotFoundError(ContractError):
    """The registry holds no record for the requested contract."""


class ContractNotEligibleError(ContractError):
    """The contract exists but may not be traded under the current rules."""


class NoEligibleContractError(ContractError):
    """No listed contract satisfies the eligibility rules at the requested time."""


class PositionSpliceError(ContractError):
    """An operation attempted to carry a position across two different contracts.

    Section 7: do not splice positions across contracts.
    """


# --- sessions ------------------------------------------------------------------------


class SessionError(TfexError):
    """Base class for session-state failures."""


class SessionNotEligibleError(SessionError):
    """The requested action is not permitted in the current session state."""
