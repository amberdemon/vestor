"""Exact, dated USD-to-GBP conversions using explicitly linked manual rates."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import Literal, get_args

from .events import ResultStatus, SourceStatus, _source_status
from .primitives import InputError, Problem, display_gbp, rounded_pennies
from .share_evidence import ShareSource, _date, _decimal, _optional_id

FxPurpose = Literal[
    "vest_income", "acquisition_basis", "disposal_proceeds",
    "acquisition_fee", "disposal_fee", "cash_settlement",
]


def _purpose(value: FxPurpose) -> None:
    if value not in get_args(FxPurpose):
        raise InputError("purpose", "Choose a supported conversion purpose.")


@dataclass(frozen=True)
class FxRate:
    """GBP per one USD. The pair is written as units, GBP/USD."""

    source: ShareSource
    on: date | None
    purpose: FxPurpose
    gbp_per_usd: Decimal | None
    pair: Literal["GBP/USD"]

    def __post_init__(self) -> None:
        _date(self.on, "on")
        _purpose(self.purpose)
        if self.pair != "GBP/USD":
            raise InputError("pair", "Supply the rate in GBP per one USD.")
        _decimal(self.gbp_per_usd, "gbp_per_usd", positive=True)


@dataclass(frozen=True)
class FxConversion:
    status: ResultStatus
    on: date | None
    purpose: FxPurpose
    requested_rate_id: str | None
    rate: FxRate | None
    amount_usd: Fraction | None
    amount_gbp: Fraction | None
    warnings: tuple[Problem, ...] = ()

    @property
    def display_gbp(self) -> str | None:
        return None if self.amount_gbp is None else display_gbp(self.amount_gbp)

    @property
    def rounding_discrepancy_gbp(self) -> Fraction | None:
        if self.amount_gbp is None:
            return None
        return Fraction(rounded_pennies(self.amount_gbp), 100) - self.amount_gbp


class FxRates:
    """Index original quotes by ID and resolve explicit, compatible replacements."""

    def __init__(self, rates: Iterable[FxRate]) -> None:
        self.rates = tuple(rates)
        self._by_id = {rate.source.event_id: rate for rate in self.rates}
        if len(self._by_id) != len(self.rates):
            raise InputError("rate_id", "Use each rate identifier once.")
        self._replacements: dict[str, FxRate] = {}
        for rate in self.rates:
            forecast_id = rate.source.replaces_forecast_id
            if forecast_id is None:
                continue
            forecast = self._by_id.get(forecast_id)
            if (
                forecast is None or forecast.source.source_status != "forecast"
                or forecast_id in self._replacements or forecast.on is None
                or rate.on != forecast.on or rate.purpose != forecast.purpose
            ):
                raise InputError("replaces_forecast_id", "Link one forecast with the same rate date and purpose.")
            self._replacements[forecast_id] = rate

    def convert(
        self,
        usd: Decimal | None,
        *,
        on: date | None,
        purpose: FxPurpose,
        rate_id: str | None,
        quantity: Decimal | None = Decimal(1),
        source_status: SourceStatus = "actual",
    ) -> FxConversion:
        """Use the supplied event date and purpose. Fee eligibility is separate.

        HMRC CG78310 requires separate GBP values at acquisition and disposal.
        M2 requires a specific evidenced rate without any fallback lookup.
        """
        _decimal(usd, "usd")
        _decimal(quantity, "quantity")
        _date(on, "on")
        _purpose(purpose)
        _optional_id(rate_id, "rate_id")
        _source_status(source_status)
        amount = None if usd is None or quantity is None else Fraction(usd) * Fraction(quantity)
        rate = None if rate_id is None else self._replacements.get(rate_id, self._by_id.get(rate_id))
        if rate is not None and (rate.purpose != purpose or (
            on is not None and rate.on is not None and rate.on != on
        )):
            return FxConversion("input_error", on, purpose, rate_id, rate, amount, None, (
                Problem("input_error", "rate_id", "Use a rate for this conversion date and purpose."),
            ))
        if (
            rate is None or rate.on is None or rate.gbp_per_usd is None or on is None
            or amount is None or "unknown" in (source_status, rate.source.source_status)
        ):
            return FxConversion("incomplete", on, purpose, rate_id, rate, amount, None, (
                Problem("incomplete", "fx", "Confirm the USD amount, date and linked rate evidence."),
            ))
        status: ResultStatus = (
            "estimated" if "forecast" in (source_status, rate.source.source_status) else "confirmed"
        )
        return FxConversion(status, on, purpose, rate_id, rate, amount, amount * Fraction(rate.gbp_per_usd))
