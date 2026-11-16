"""Value ordinary share-settled vests and reconcile them through M1 ANI."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import Literal

from .ani import AniInputs, AniResult, calculate_ani
from .events import DatedMoney, ResultStatus
from .fx import FxConversion, FxRates
from .primitives import InputError, Problem, display_gbp, rounded_pennies, validate_gbp
from .rsu import RsuEvent
from .share_evidence import Grant, Vest, _confirmation, _optional_id

BasisMethod = Literal["market_value", "nil_price_chapter_5"]


@dataclass(frozen=True)
class VestValuationInput:
    vest: Vest
    grant: Grant
    included_in_payroll: bool | None = None
    payroll_ids: tuple[str, ...] = ()
    gross_usd: Decimal | None = None
    confirmed_payroll_gbp: Decimal | None = None
    basis_method: BasisMethod | None = None
    confirmed_basis_gbp: Decimal | None = None
    manual_vest_id: str | None = None
    replaces_manual_forecast_id: str | None = None

    def __post_init__(self) -> None:
        if self.vest.grant_id != self.grant.source.event_id or self.vest.security.identity != self.grant.security.identity:
            raise InputError("grant_id", "Link the grant for this share identity.")
        validate_gbp(self.gross_usd, field="gross_usd")
        validate_gbp(self.confirmed_payroll_gbp, field="confirmed_payroll_gbp")
        validate_gbp(self.confirmed_basis_gbp, field="confirmed_basis_gbp")
        _confirmation(self.included_in_payroll, "included_in_payroll")
        _optional_id(self.manual_vest_id, "manual_vest_id")
        _optional_id(self.replaces_manual_forecast_id, "replaces_manual_forecast_id")
        if self.basis_method not in ("market_value", "nil_price_chapter_5", None):
            raise InputError("basis_method", "Select the evidenced basis method.")
        if self.vest.source.source_status != "actual" and (
            self.confirmed_payroll_gbp is not None or self.confirmed_basis_gbp is not None
        ):
            raise InputError("source_status", "Confirmed GBP evidence requires an actual vest.")
        if self.manual_vest_id is not None and (
            self.replaces_manual_forecast_id is not None or self.vest.source.replaces_forecast_id is not None
        ):
            raise InputError("manual_vest_id", "Choose either a linked manual vest or a forecast replacement.")
        if self.replaces_manual_forecast_id is not None and self.vest.source.replaces_forecast_id is not None:
            raise InputError("replaces_manual_forecast_id", "Link only one forecast for this replacement.")
        if self.replaces_manual_forecast_id is not None and self.vest.source.source_status != "actual":
            raise InputError("replaces_manual_forecast_id", "Only an actual vest can replace a forecast.")


@dataclass(frozen=True)
class VestValuation:
    source: VestValuationInput
    estimated_income: FxConversion
    acquisition_fx: FxConversion
    employment_status: ResultStatus
    employment_gbp: Fraction | None
    basis_status: ResultStatus
    basis_gbp: Fraction | None
    employment_warnings: tuple[Problem, ...]
    basis_warnings: tuple[Problem, ...]

    @property
    def acquisition_quantity(self) -> Decimal | None:
        return self.source.vest.quantity

    @property
    def payroll_difference_gbp(self) -> Fraction | None:
        payroll = self.source.confirmed_payroll_gbp
        model = self.estimated_income.amount_gbp
        return None if payroll is None or model is None else Fraction(payroll) - model


def _scope(raw: VestValuationInput) -> Problem | None:
    vest, grant = raw.vest, raw.grant
    dates = {on for on in (vest.vested_on, vest.acquired_on, vest.charge_on) if on is not None}
    if (
        vest.uk_resident is False or vest.security.capacity != "personal"
        or False in (vest.security.ordinary_listed, grant.security.ordinary_listed)
        or grant.treatment == "unsupported" or len(dates) > 1
    ):
        return Problem("unsupported", vest.source.event_id, "Use an ordinary UK vest with a simultaneous charge and acquisition.")
    if (
        vest.vested_on is None or vest.charge_on is None
        or None in (vest.uk_resident, vest.security.ordinary_listed, grant.security.ordinary_listed,
                                  grant.treatment, grant.awarded_on)
        or "unknown" in (vest.source.source_status, grant.source.source_status)
    ):
        return Problem("incomplete", vest.source.event_id, "Confirm award treatment, vest dates and residence.")
    if grant.awarded_on is not None and vest.vested_on is not None and grant.awarded_on > vest.vested_on:
        return Problem("input_error", vest.source.event_id, "The vest date precedes the grant.")
    return None


def value_vest(raw: VestValuationInput, rates: FxRates) -> VestValuation:
    """Use gross vest shares. Keep payroll evidence distinct from acquisition basis.

    ERSM20194 example 1; CG56321 and CG56384 for the two basis methods.
    """
    vest = raw.vest
    income_fx = rates.convert(vest.fmv_usd_per_share, on=vest.charge_on, purpose="vest_income",
                              rate_id=vest.income_rate_id, quantity=vest.quantity,
                              source_status=vest.source.source_status)
    basis_fx = rates.convert(vest.fmv_usd_per_share, on=vest.acquired_on, purpose="acquisition_basis",
                             rate_id=vest.basis_rate_id, quantity=vest.quantity,
                             source_status=vest.source.source_status)
    common = _scope(raw)
    gross_problem = None
    if (raw.gross_usd is not None and income_fx.amount_usd is not None
        and rounded_pennies(income_fx.amount_usd) != Fraction(raw.gross_usd) * 100):
        gross_problem = Problem("input_error", "gross_usd", "Reconcile gross USD with shares times FMV at penny precision.")

    employment_status: ResultStatus = income_fx.status
    employment = income_fx.amount_gbp
    employment_warnings = income_fx.warnings
    if common is not None:
        employment_status, employment, employment_warnings = common.status, None, (common,)
    elif gross_problem is not None:
        employment_status, employment, employment_warnings = gross_problem.status, None, (gross_problem,)
    elif raw.confirmed_payroll_gbp is not None:
        employment_status, employment = "confirmed", Fraction(raw.confirmed_payroll_gbp)
        employment_warnings = ()
    elif employment is not None:
        employment_status = "estimated"

    basis_status, basis, basis_warnings = _basis(raw, basis_fx, common, gross_problem)
    return VestValuation(raw, income_fx, basis_fx, employment_status, employment,
                         basis_status, basis, employment_warnings, basis_warnings)


def _basis(
    raw: VestValuationInput, fx: FxConversion, common: Problem | None, gross_problem: Problem | None,
) -> tuple[ResultStatus, Fraction | None, tuple[Problem, ...]]:
    if common is not None:
        return common.status, None, (common,)
    if raw.basis_method is None or raw.vest.quantity is None or raw.vest.acquired_on is None:
        return "incomplete", None, (Problem("incomplete", "basis_method", "Confirm the acquisition method, date and quantity."),)
    if raw.confirmed_basis_gbp is not None:
        return "confirmed", Fraction(raw.confirmed_basis_gbp), ()
    if gross_problem is not None:
        return gross_problem.status, None, (gross_problem,)
    if raw.basis_method == "nil_price_chapter_5" and raw.vest.source.source_status == "actual":
        return "incomplete", None, (Problem("incomplete", "confirmed_basis_gbp", "Supply the independently evidenced qualifying section 119A amount."),)
    return fx.status, fx.amount_gbp, fx.warnings


@dataclass(frozen=True)
class _ValuedRsuEvent(RsuEvent):
    exact_amount: Fraction | None = None
    estimated: bool = False
    problems: tuple[Problem, ...] = ()

    @property
    def taxable_gbp(self) -> Fraction | None:
        return self.exact_amount

    @property
    def valuation_estimated(self) -> bool:
        return self.estimated

    @property
    def valuation_warnings(self) -> tuple[Problem, ...]:
        return self.problems


def _rsu_event(value: VestValuation) -> RsuEvent:
    raw, vest = value.source, value.source.vest
    amount = value.employment_gbp
    replacement = raw.replaces_manual_forecast_id or vest.source.replaces_forecast_id
    money = DatedMoney(
        vest.source.event_id, vest.charge_on or vest.vested_on or date.min,
        None if amount is None else Decimal(display_gbp(amount)), vest.source.source_status,
        vest.source.source_note, replacement,
    )
    return _ValuedRsuEvent(
        money, vest.charge_on is not None, value.employment_status != "unsupported",
        raw.included_in_payroll, raw.payroll_ids, exact_amount=amount,
        estimated=value.employment_status == "estimated",
        problems=value.employment_warnings if amount is None else (),
    )


def calculate_ani_with_vests(
    raw: AniInputs, values: Iterable[VestValuation], *, grant_replacements: Mapping[str, str] | None = None,
) -> AniResult:
    """Bridge one explicit canonical component per vest into the M1 engine."""
    manual = {record.money.event_id: record for record in raw.rsu_events}
    values = tuple(values)
    by_id = {value.source.vest.source.event_id: value for value in values}
    if len(by_id) != len(values):
        raise InputError("event_id", "Each valued vest must have a unique identifier.")
    claimed: set[str] = set()
    generated = []
    for value in values:
        source = value.source
        event = _rsu_event(value)
        manual_id = source.manual_vest_id
        manual_replacement = source.replaces_manual_forecast_id
        replacement = source.vest.source.replaces_forecast_id
        if manual_replacement is not None and manual_replacement not in manual:
            raise InputError("replaces_manual_forecast_id", "Link an existing manual forecast.")
        if replacement is not None:
            forecast = by_id.get(replacement)
            if (
                forecast is None or forecast.source.manual_vest_id is not None
                or forecast.source.vest.security.identity != source.vest.security.identity
                or (grant_replacements or {}).get(forecast.source.vest.grant_id, forecast.source.vest.grant_id)
                != source.vest.grant_id
            ):
                raise InputError("replaces_forecast_id", "Link a valued forecast vest for the same grant and share identity.")
        if manual_id is None:
            generated.append(event)
            continue
        record = manual.get(manual_id)
        if (
            record is None or manual_id in claimed
            or (event.money.event_id != manual_id and event.money.event_id in manual)
        ):
            raise InputError("manual_vest_id", "Link each vest to one unique existing manual record.")
        if (
            value.employment_status in ("unsupported", "input_error")
            or not record.charge_date_confirmed or not event.charge_date_confirmed
            or event.money.on != record.money.on
            or event.money.source_status != record.money.source_status
            or event.included_in_payroll != record.included_in_payroll
            or set(event.payroll_ids) != set(record.payroll_ids)
            or (value.employment_status == "confirmed" and event.taxable_gbp != record.taxable_gbp)
            or (value.employment_status == "estimated" and record.money.source_status == "forecast"
                and event.money.amount_gbp != record.money.amount_gbp)
        ):
            raise InputError("manual_vest_id", "Reconcile charge date, source, taxable GBP and payroll links with the manual record.")
        claimed.add(manual_id)
    return calculate_ani(replace(raw, rsu_events=raw.rsu_events + tuple(generated)))
