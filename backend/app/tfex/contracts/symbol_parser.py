"""Strict SET50 Index Futures symbol parsing (`CLAUDE_TFEX.md` section 5).

A TFEX SET50 futures symbol is the root, a futures month code, and a two-digit year —
``S50Z25`` is the December 2025 contract.

Section 5 requires the parser to reject malformed symbols, reject impossible month/year
combinations, support historical symbols, and **never guess the active contract**. Two
consequences shape this module:

1. Parsing is *pure syntax plus a calendar reference*. It resolves the two-digit year, and
   stops. Expiry, status and eligibility need registry and calendar data and live in
   :mod:`app.tfex.contracts.metadata`.
2. The two-digit year is resolved against an **explicit reference date**, never against
   "now". Re-parsing a 2019 symbol in 2031 must give the same answer it gave in 2019, or
   every historical backtest silently changes meaning.

Section 5 also warns against assuming only quarterly symbols exist: SET50 futures list the
three nearest consecutive months *plus* the next three quarterly months, so all twelve month
codes are valid.
"""

from __future__ import annotations

import re
from datetime import date
from types import MappingProxyType
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.tfex.config import TfexConfig
from app.tfex.errors import SymbolParseError

__all__ = [
    "MONTH_CODES",
    "MONTH_CODE_BY_MONTH",
    "ParsedContractSymbol",
    "format_symbol",
    "month_code_for",
    "parse_symbol",
    "resolve_two_digit_year",
]

#: Standard futures month codes. All twelve are valid for SET50 futures (section 5).
MONTH_CODES: MappingProxyType[str, int] = MappingProxyType(
    {
        "F": 1,
        "G": 2,
        "H": 3,
        "J": 4,
        "K": 5,
        "M": 6,
        "N": 7,
        "Q": 8,
        "U": 9,
        "V": 10,
        "X": 11,
        "Z": 12,
    }
)

MONTH_CODE_BY_MONTH: MappingProxyType[int, str] = MappingProxyType(
    {month: code for code, month in MONTH_CODES.items()}
)

_ROOT_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{0,5}$")


def month_code_for(month: int) -> str:
    """Month code for a calendar month number."""
    try:
        return MONTH_CODE_BY_MONTH[month]
    except KeyError:
        raise SymbolParseError(f"{month!r} is not a calendar month (1-12)") from None


def format_symbol(root: str, contract_year: int, contract_month: int) -> str:
    """Build a symbol string, e.g. ``("S50", 2025, 12) -> "S50Z25"``."""
    return f"{root}{month_code_for(contract_month)}{contract_year % 100:02d}"


def resolve_two_digit_year(yy: int, reference_year: int, *, pivot_years: int = 50) -> int:
    """Resolve a two-digit year against an explicit reference year.

    The candidate century is chosen so the result lands within ``+/- pivot_years`` of the
    reference. ``25`` read in 2026 is 2025; ``99`` read in 2026 is 1999.

    The reference year is a required input rather than "the current year" on purpose: a
    symbol must parse to the same contract forever, including when a 2019 dataset is replayed
    in 2031.
    """
    if not 0 <= yy <= 99:
        raise SymbolParseError(f"two-digit year {yy!r} is out of range")
    candidate = (reference_year // 100) * 100 + yy
    if candidate - reference_year > pivot_years:
        candidate -= 100
    elif reference_year - candidate > pivot_years:
        candidate += 100
    return candidate


class ParsedContractSymbol(BaseModel):
    """The purely syntactic reading of a contract symbol.

    Carries no expiry, status or eligibility: those require calendar and registry data.
    A ``ParsedContractSymbol`` says "this string names the December 2025 S50 contract" and
    nothing more.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    raw: str
    """Exactly what the caller supplied. Section 30 requires raw symbols to be preserved."""

    normalized: str
    root: str
    month_code: str = Field(min_length=1, max_length=1)
    year_2digit: int = Field(ge=0, le=99)
    contract_year: int
    contract_month: int = Field(ge=1, le=12)
    reference_date: date
    """The date the two-digit year was resolved against, recorded so the resolution is
    reproducible and auditable."""

    @model_validator(mode="after")
    def _internally_consistent(self) -> Self:
        if MONTH_CODES.get(self.month_code) != self.contract_month:
            raise ValueError(
                f"month code {self.month_code!r} does not correspond to month {self.contract_month}"
            )
        if self.contract_year % 100 != self.year_2digit:
            raise ValueError(
                f"contract year {self.contract_year} does not end in {self.year_2digit:02d}"
            )
        expected = f"{self.root}{self.month_code}{self.year_2digit:02d}"
        if self.normalized != expected:
            raise ValueError(f"normalized symbol {self.normalized!r} should be {expected!r}")
        return self

    @property
    def contract_month_key(self) -> tuple[int, int]:
        return self.contract_year, self.contract_month

    def __str__(self) -> str:
        return self.normalized


def parse_symbol(
    raw: str,
    *,
    config: TfexConfig,
    reference_date: date,
) -> ParsedContractSymbol:
    """Parse a SET50 futures symbol.

    Args:
        raw: the symbol as received. Surrounding whitespace and lower case are tolerated
            and normalised; anything else structural is an error.
        config: supplies the expected root and the acceptance window for contract years.
        reference_date: the date the two-digit year is resolved against — typically the
            timestamp of the data being processed, **not** today.

    Raises:
        SymbolParseError: the symbol is malformed, uses an unknown month code, or names a
            contract year outside the configured acceptance window.
    """
    normalized = raw.strip().upper()
    if not normalized:
        raise SymbolParseError("symbol is empty")
    if any(character.isspace() for character in normalized):
        raise SymbolParseError(f"symbol {raw!r} contains whitespace")

    root = config.symbol.root.upper()
    if not _ROOT_PATTERN.match(root):
        raise SymbolParseError(f"configured symbol root {root!r} is not a valid ticker root")

    if not normalized.startswith(root):
        raise SymbolParseError(
            f"symbol {raw!r} does not start with the configured root {root!r}; this platform "
            f"trades SET50 index futures only"
        )

    suffix = normalized[len(root) :]
    expected_suffix_length = 1 + config.symbol.year_digits
    if len(suffix) != expected_suffix_length:
        raise SymbolParseError(
            f"symbol {raw!r} must be {root} followed by a month code and "
            f"{config.symbol.year_digits} year digits (e.g. {root}Z25)"
        )

    month_code = suffix[0]
    year_text = suffix[1:]

    if month_code not in MONTH_CODES:
        raise SymbolParseError(
            f"symbol {raw!r} uses month code {month_code!r}, which is not a futures month "
            f"code ({''.join(MONTH_CODES)})"
        )
    if not year_text.isdigit():
        raise SymbolParseError(f"symbol {raw!r} has non-numeric year digits {year_text!r}")

    contract_month = MONTH_CODES[month_code]
    contract_year = resolve_two_digit_year(
        int(year_text),
        reference_date.year,
        pivot_years=config.symbol.century_pivot_years,
    )

    minimum_year = config.symbol.minimum_contract_year
    maximum_year = reference_date.year + config.symbol.maximum_years_ahead
    if contract_year < minimum_year:
        raise SymbolParseError(
            f"symbol {raw!r} resolves to contract year {contract_year}, before the configured "
            f"earliest listed year {minimum_year}"
        )
    if contract_year > maximum_year:
        raise SymbolParseError(
            f"symbol {raw!r} resolves to contract year {contract_year}, more than "
            f"{config.symbol.maximum_years_ahead} year(s) after the reference date "
            f"{reference_date.isoformat()}"
        )

    return ParsedContractSymbol(
        raw=raw,
        normalized=normalized,
        root=root,
        month_code=month_code,
        year_2digit=int(year_text),
        contract_year=contract_year,
        contract_month=contract_month,
        reference_date=reference_date,
    )
