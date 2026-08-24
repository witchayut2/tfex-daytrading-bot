"""Loading official TFEX holiday data from versioned storage (`CLAUDE_TFEX.md` section 8).

The platform ships **no holiday dates**. Inventing them would be the single most dangerous
shortcut available here: a wrong holiday set moves the last business day of the month, which
moves the last trading day, which moves the expiry gate. Section 2 forbids silently
continuing with stale exchange metadata, so an unloaded year raises rather than defaults.

Storage layout::

    backend/data/tfex/holidays/2026.json

See ``backend/data/tfex/holidays/README.md`` for the file schema and the import procedure.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from app.tfex.calendar.models import HolidayCalendarYear
from app.tfex.errors import CalendarDataInvalidError, CalendarDataUnavailableError

__all__ = ["DEFAULT_HOLIDAY_DIRECTORY", "HolidayStore", "load_holiday_year_file"]

DEFAULT_HOLIDAY_DIRECTORY = Path(__file__).resolve().parents[3] / "data" / "tfex" / "holidays"

SUPPORTED_SCHEMA_VERSION = 1
_YEAR_FILE_PATTERN = re.compile(r"^(\d{4})\.json$")


def load_holiday_year_file(path: Path) -> HolidayCalendarYear:
    """Load and validate one year file.

    Raises:
        CalendarDataUnavailableError: the file does not exist.
        CalendarDataInvalidError: the file is unreadable, malformed, or fails validation.
    """
    if not path.is_file():
        raise CalendarDataUnavailableError(f"no calendar data file at {path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CalendarDataInvalidError(f"cannot read calendar data at {path}: {exc}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CalendarDataInvalidError(f"calendar data at {path} is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise CalendarDataInvalidError(f"calendar data at {path} must be a JSON object")

    version = payload.get("schema_version", 1)
    if version != SUPPORTED_SCHEMA_VERSION:
        raise CalendarDataInvalidError(
            f"calendar data at {path} declares schema_version {version!r}; this build "
            f"supports {SUPPORTED_SCHEMA_VERSION}"
        )

    try:
        year_data = HolidayCalendarYear.model_validate(payload)
    except ValidationError as exc:
        raise CalendarDataInvalidError(f"calendar data at {path} is invalid:\n{exc}") from exc

    match = _YEAR_FILE_PATTERN.match(path.name)
    if match and int(match.group(1)) != year_data.year:
        raise CalendarDataInvalidError(
            f"calendar data file {path.name} declares year {year_data.year}; the filename and "
            f"the content must agree"
        )
    return year_data


class HolidayStore:
    """Lazily-loaded, cached access to per-year calendar files.

    Caching is deliberate and one-way: a year is read from disk once per process. Calendar
    answers must not change underneath a running replay because someone edited a file.
    """

    def __init__(
        self,
        directory: Path | str | None = None,
        *,
        preloaded: Iterable[HolidayCalendarYear] | None = None,
    ) -> None:
        self._directory = Path(directory) if directory is not None else DEFAULT_HOLIDAY_DIRECTORY
        self._cache: dict[int, HolidayCalendarYear] = {}
        for year_data in preloaded or ():
            self._cache[year_data.year] = year_data

    @property
    def directory(self) -> Path:
        return self._directory

    def path_for(self, year: int) -> Path:
        return self._directory / f"{year}.json"

    def is_loaded(self, year: int) -> bool:
        return year in self._cache

    def available_years(self) -> tuple[int, ...]:
        """Years that are cached or present on disk. Cheap enough to call for diagnostics."""
        years = set(self._cache)
        if self._directory.is_dir():
            for entry in self._directory.iterdir():
                match = _YEAR_FILE_PATTERN.match(entry.name)
                if match and entry.is_file():
                    years.add(int(match.group(1)))
        return tuple(sorted(years))

    def year(self, year: int) -> HolidayCalendarYear:
        """Return the calendar for ``year``.

        Raises:
            CalendarDataUnavailableError: official data for that year has not been imported.
                Callers must surface this rather than falling back to a weekday rule.
        """
        cached = self._cache.get(year)
        if cached is not None:
            return cached

        path = self.path_for(year)
        if not path.is_file():
            raise CalendarDataUnavailableError(
                f"official TFEX calendar data for {year} has not been imported "
                f"(expected {path}). Import it before any date-sensitive operation; see "
                f"data/tfex/holidays/README.md."
            )
        loaded = load_holiday_year_file(path)
        self._cache[year] = loaded
        return loaded

    def require_years(self, years: Iterable[int]) -> None:
        """Fail fast for a whole span, so a backtest cannot start and break in the middle."""
        missing = []
        for year in sorted(set(years)):
            try:
                self.year(year)
            except CalendarDataUnavailableError:
                missing.append(year)
        if missing:
            raise CalendarDataUnavailableError(
                f"official TFEX calendar data is missing for {missing}; "
                f"available years: {list(self.available_years())}"
            )

    def freshness_report(self, as_of: datetime) -> dict[int, bool]:
        """Map of loaded year -> whether its provenance is stale at ``as_of``."""
        return {year: data.provenance.is_stale(as_of) for year, data in sorted(self._cache.items())}
