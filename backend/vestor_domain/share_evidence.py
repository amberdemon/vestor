"""Immutable share evidence and physical inventory checks for the M2 contract."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import Literal

from .events import ResultStatus, SourceStatus, _require_text, _source_status
from .primitives import InputError, Problem, ProblemStatus

Currency = Literal["GBP", "USD"]


def _date(value: object, field: str) -> None:
    if value is not None and type(value) is not date:
        raise InputError(field, "Use a date-only value or mark it unknown.")


def _decimal(value: Decimal | None, field: str, *, positive: bool = False) -> None:
    if value is not None and (
        not isinstance(value, Decimal) or not value.is_finite() or value.is_signed()
        or (positive and value.is_zero())
    ):
        rule = "positive" if positive else "nonnegative"
        raise InputError(field, f"Use a finite {rule} Decimal or mark it unknown.")


def _optional_id(value: str | None, field: str) -> None:
    if value is not None:
        _require_text(value, field)


def _currency(value: Currency, rate_id: str | None) -> None:
    if value not in ("GBP", "USD"):
        raise InputError("currency", "Use GBP or USD.")
    _optional_id(rate_id, "rate_id")
    if value == "GBP" and rate_id is not None:
        raise InputError("rate_id", "GBP evidence does not require a conversion rate.")


@dataclass(frozen=True)
class ShareSource:
    event_id: str
    source_status: SourceStatus
    source_note: str
    replaces_forecast_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.event_id, "event_id")
        _source_status(self.source_status)
        _require_text(self.source_note, "source_note")
        if self.replaces_forecast_id is not None:
            _require_text(self.replaces_forecast_id, "replaces_forecast_id")
            if self.source_status != "actual" or self.event_id == self.replaces_forecast_id:
                raise InputError("replaces_forecast_id", "Only an actual can replace a different forecast.")


@dataclass(frozen=True)
class Security:
    issuer_id: str
    share_class: str
    owner_id: str
    capacity: str
    ordinary_listed: bool | None = None

    @property
    def identity(self) -> tuple[str, str, str, str]:
        return self.issuer_id, self.share_class, self.owner_id, self.capacity

    def __post_init__(self) -> None:
        _require_text(self.issuer_id, "issuer_id")
        _require_text(self.share_class, "share_class")
        _require_text(self.owner_id, "owner_id")
        _require_text(self.capacity, "capacity")
        _confirmation(self.ordinary_listed, "ordinary_listed")


def _confirmation(value: bool | None, field: str) -> None:
    if value is not None and type(value) is not bool:
        raise InputError(field, "Use true, false or null.")


@dataclass(frozen=True)
class Grant:
    source: ShareSource
    security: Security
    awarded_on: date | None
    treatment: Literal["ordinary_rsu", "unsupported"] | None

    def __post_init__(self) -> None:
        _date(self.awarded_on, "awarded_on")
        if self.treatment not in ("ordinary_rsu", "unsupported", None):
            raise InputError("treatment", "Specify the supported award treatment or mark it unknown.")


@dataclass(frozen=True)
class Vest:
    source: ShareSource
    security: Security
    grant_id: str
    vested_on: date | None
    acquired_on: date | None
    charge_on: date | None
    quantity: Decimal | None
    fmv_usd_per_share: Decimal | None
    income_rate_id: str | None = None
    basis_rate_id: str | None = None
    uk_resident: bool | None = None

    def __post_init__(self) -> None:
        _require_text(self.grant_id, "grant_id")
        _date(self.vested_on, "vested_on")
        _date(self.acquired_on, "acquired_on")
        _date(self.charge_on, "charge_on")
        _decimal(self.quantity, "quantity", positive=True)
        _decimal(self.fmv_usd_per_share, "fmv_usd_per_share")
        _optional_id(self.income_rate_id, "income_rate_id")
        _optional_id(self.basis_rate_id, "basis_rate_id")
        _confirmation(self.uk_resident, "uk_resident")


@dataclass(frozen=True)
class Purchase:
    source: ShareSource
    security: Security
    acquired_on: date | None
    quantity: Decimal | None
    gross_amount: Decimal | None
    currency: Currency
    rate_id: str | None = None
    uk_resident: bool | None = None

    def __post_init__(self) -> None:
        _date(self.acquired_on, "acquired_on")
        _decimal(self.quantity, "quantity", positive=True)
        _decimal(self.gross_amount, "gross_amount")
        _currency(self.currency, self.rate_id)
        _confirmation(self.uk_resident, "uk_resident")


@dataclass(frozen=True)
class Sale:
    source: ShareSource
    security: Security
    trade_on: date | None
    quantity: Decimal | None
    gross_amount: Decimal | None
    currency: Currency
    purpose: Literal["voluntary", "sell_to_cover"]
    vest_id: str | None = None
    settlement_on: date | None = None
    rate_id: str | None = None
    uk_resident: bool | None = None

    def __post_init__(self) -> None:
        _date(self.trade_on, "trade_on")
        _date(self.settlement_on, "settlement_on")
        if self.trade_on is not None and self.settlement_on is not None and self.settlement_on < self.trade_on:
            raise InputError("settlement_on", "Settlement cannot precede the trade.")
        _decimal(self.quantity, "quantity", positive=True)
        _decimal(self.gross_amount, "gross_amount")
        _currency(self.currency, self.rate_id)
        if self.purpose not in ("voluntary", "sell_to_cover"):
            raise InputError("purpose", "Use voluntary or sell_to_cover.")
        _optional_id(self.vest_id, "vest_id")
        if (self.purpose == "sell_to_cover") != (self.vest_id is not None):
            raise InputError("vest_id", "Link a vest for a sell-to-cover trade.")
        _confirmation(self.uk_resident, "uk_resident")


@dataclass(frozen=True)
class Fee:
    source: ShareSource
    transaction_id: str
    on: date | None
    amount: Decimal | None
    currency: Currency
    rate_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.transaction_id, "transaction_id")
        _date(self.on, "on")
        _decimal(self.amount, "amount")
        _currency(self.currency, self.rate_id)


@dataclass(frozen=True)
class WithholdingLink:
    source: ShareSource
    vest_id: str
    sale_id: str | None
    remitted_on: date | None

    def __post_init__(self) -> None:
        _require_text(self.vest_id, "vest_id")
        _optional_id(self.sale_id, "sale_id")
        _date(self.remitted_on, "remitted_on")


@dataclass(frozen=True)
class OpeningHolding:
    """Closing pool and physical holding at as_of, with prehistory reconciled."""

    source: ShareSource
    security: Security
    as_of: date | None
    quantity: Decimal | None
    cost_gbp: Decimal | None
    history_confirmed: bool
    coverage_through: date | None

    def __post_init__(self) -> None:
        _date(self.as_of, "as_of")
        _date(self.coverage_through, "coverage_through")
        _decimal(self.quantity, "quantity")
        _decimal(self.cost_gbp, "cost_gbp")
        if self.quantity == 0 and self.cost_gbp not in (0, None):
            raise InputError("cost_gbp", "An empty pool must have zero cost.")
        if type(self.history_confirmed) is not bool:
            raise InputError("history_confirmed", "Confirm whether the opening history is reconciled.")
        if self.as_of is not None and self.coverage_through is not None and self.coverage_through < self.as_of:
            raise InputError("coverage_through", "Coverage cannot end before the opening holding.")


ShareRecord = Grant | Vest | Purchase | Sale | Fee | WithholdingLink | OpeningHolding
Transaction = Vest | Purchase | Sale


@dataclass(frozen=True)
class ShareEvidence:
    status: ResultStatus
    records: tuple[ShareRecord, ...]
    active: tuple[ShareRecord, ...]
    replacements: tuple[tuple[str, str], ...]
    warnings: tuple[Problem, ...]


def _compatible(actual: ShareRecord, forecast: ShareRecord) -> bool:
    if isinstance(actual, (Grant, Vest, Purchase, Sale, OpeningHolding)):
        if not isinstance(forecast, (Grant, Vest, Purchase, Sale, OpeningHolding)):
            return False
        if actual.security.identity != forecast.security.identity:
            return False
    if isinstance(actual, Sale) and isinstance(forecast, Sale):
        return actual.purpose == forecast.purpose
    return type(actual) is type(forecast)


def _links(active: dict[str, ShareRecord]) -> list[Problem]:
    warnings = []
    cover_quantities: dict[str, Fraction] = defaultdict(Fraction)
    for record in active.values():
        if isinstance(record, Vest):
            grant = active.get(record.grant_id)
            if not isinstance(grant, Grant) or grant.security.identity != record.security.identity:
                warnings.append(Problem("input_error", "grant_id", "Link an active grant for the same share identity."))
            elif grant.awarded_on and record.vested_on and grant.awarded_on > record.vested_on:
                warnings.append(Problem("input_error", "vested_on", "A vest cannot precede the award."))
        elif isinstance(record, Sale) and record.vest_id is not None:
            vest = active.get(record.vest_id)
            if not isinstance(vest, Vest) or vest.security.identity != record.security.identity or (
                record.trade_on is not None and vest.acquired_on is not None and record.trade_on != vest.acquired_on
            ):
                warnings.append(Problem("input_error", "vest_id", "Link an active acquisition with the same identity and trade date."))
            elif vest.quantity is not None and record.quantity is not None:
                cover_quantities[record.vest_id] += Fraction(record.quantity)
                if cover_quantities[record.vest_id] > Fraction(vest.quantity):
                    warnings.append(Problem("input_error", "quantity", "Total sell-to-cover quantity exceeds the linked vest."))
        elif isinstance(record, Fee):
            if not isinstance(active.get(record.transaction_id), (Vest, Purchase, Sale)):
                warnings.append(Problem("input_error", "transaction_id", "Link an active acquisition or sale."))
        elif isinstance(record, WithholdingLink):
            if not isinstance(active.get(record.vest_id), Vest):
                warnings.append(Problem("input_error", "vest_id", "Link an active vest."))
            if record.sale_id is not None:
                sale = active.get(record.sale_id)
                if not isinstance(sale, Sale) or sale.purpose != "sell_to_cover" or sale.vest_id != record.vest_id:
                    warnings.append(Problem("input_error", "sale_id", "Link an active cover sale for this vest."))
                elif sale.trade_on and record.remitted_on and record.remitted_on < sale.trade_on:
                    warnings.append(Problem("input_error", "remitted_on", "Remittance cannot precede its linked cover sale."))
    return warnings


def _inventory(active: tuple[ShareRecord, ...]) -> list[Problem]:
    warnings = []
    openings: dict[tuple[str, str, str, str], OpeningHolding] = {}
    transactions: dict[tuple[str, str, str, str], list[Transaction]] = defaultdict(list)
    for record in active:
        if isinstance(record, OpeningHolding):
            if record.security.identity in openings:
                warnings.append(Problem("input_error", "security", "Use one opening holding per share identity."))
            openings[record.security.identity] = record
            if None in (record.as_of, record.quantity, record.cost_gbp) or not record.history_confirmed:
                warnings.append(Problem("incomplete", "opening_holding", "Confirm the opening quantity, cost and prehistory."))
        elif isinstance(record, (Vest, Purchase, Sale)):
            transactions[record.security.identity].append(record)
    for identity, events in transactions.items():
        opening = openings.get(identity)
        if opening is None:
            warnings.append(Problem("incomplete", "opening_holding", "Supply a reconciled opening holding for this share identity."))
            continue
        if opening.as_of is None or opening.quantity is None or opening.cost_gbp is None or not opening.history_confirmed:
            continue
        changes: dict[date, Fraction] = defaultdict(Fraction)
        dates_known = True
        for transaction in events:
            on = transaction.trade_on if isinstance(transaction, Sale) else transaction.acquired_on
            if on is None or transaction.quantity is None:
                warnings.append(Problem("incomplete", transaction.source.event_id, "Confirm the transaction date and quantity."))
                dates_known = False
                continue
            if on <= opening.as_of:
                warnings.append(Problem("input_error", transaction.source.event_id, "Transaction must follow the opening snapshot."))
                dates_known = False
                continue
            quantity = Fraction(transaction.quantity)
            changes[on] += -quantity if isinstance(transaction, Sale) else quantity
            if isinstance(transaction, Sale) and (
                opening.coverage_through is None or (opening.coverage_through - on).days < 30
            ):
                warnings.append(Problem("incomplete", transaction.source.event_id, "Confirm history through 30 days after the sale."))
        if dates_known:
            balance = Fraction(opening.quantity)
            for on in sorted(changes):
                balance += changes[on]
                if balance < 0:
                    confirmed_through_sale = opening.coverage_through is not None and opening.coverage_through >= on
                    status: ProblemStatus = "unsupported" if confirmed_through_sale else "incomplete"
                    warnings.append(Problem(status, "quantity", "Sale exceeds evidenced physical holdings."))
                    break
    return warnings


def validate_share_evidence(records: Iterable[ShareRecord]) -> ShareEvidence:
    """Resolve replacements before checking links, scope and physical positions."""
    originals = tuple(records)
    by_id = {record.source.event_id: record for record in originals}
    if len(by_id) != len(originals):
        return ShareEvidence("input_error", originals, (), (), (
            Problem("input_error", "event_id", "Each event identifier must occur once."),
        ))
    replacements: dict[str, str] = {}
    for key, record in by_id.items():
        forecast_id = record.source.replaces_forecast_id
        if forecast_id is None:
            continue
        forecast = by_id.get(forecast_id)
        if (
            forecast is None or forecast.source.source_status != "forecast"
            or forecast_id in replacements or not _compatible(record, forecast)
        ):
            return ShareEvidence("input_error", originals, (), (), (
                Problem("input_error", "replaces_forecast_id", "Link one compatible forecast per actual replacement."),
            ))
        replacements[forecast_id] = key
    active = {key: record for key, record in by_id.items() if key not in replacements}
    events = tuple(active.values())
    warnings = _links(active)
    for key, record in active.items():
        if record.source.source_status == "unknown":
            warnings.append(Problem("incomplete", key, "Confirm the record source status."))
        if isinstance(record, (Grant, Vest, Sale, Purchase, OpeningHolding)):
            if record.security.capacity != "personal" or record.security.ordinary_listed is False:
                warnings.append(Problem("unsupported", key, "Use ordinary listed shares held in a personal capacity."))
            elif record.security.ordinary_listed is None:
                warnings.append(Problem("incomplete", key, "Confirm the security type."))
        if isinstance(record, Grant):
            if record.treatment == "unsupported":
                warnings.append(Problem("unsupported", key, "The award treatment is outside the supported scope."))
            elif record.treatment is None or record.awarded_on is None:
                warnings.append(Problem("incomplete", key, "Confirm award treatment and date."))
        if isinstance(record, (Vest, Sale, Purchase)):
            if record.uk_resident is False:
                warnings.append(Problem("unsupported", key, "Non-UK residence is outside the supported scope."))
            elif record.uk_resident is None:
                warnings.append(Problem("incomplete", key, "Confirm UK residence on the transaction date."))
        if isinstance(record, Vest):
            vest_dates = (record.vested_on, record.acquired_on, record.charge_on)
            if None in vest_dates:
                warnings.append(Problem("incomplete", key, "Confirm vest, acquisition and charge dates."))
            elif len(set(vest_dates)) != 1:
                warnings.append(Problem("unsupported", key, "Different vest, acquisition and charge dates are outside this scope."))
        if isinstance(record, (Sale, Purchase)) and record.gross_amount is None:
            warnings.append(Problem("incomplete", key, "Confirm the gross transaction amount."))
        if isinstance(record, Fee) and (record.amount is None or record.on is None):
            warnings.append(Problem("incomplete", key, "Confirm the fee amount and date."))
    warnings.extend(_inventory(events))
    problems = {warning.status for warning in warnings}
    status: ResultStatus
    if "input_error" in problems:
        status = "input_error"
    elif "unsupported" in problems:
        status = "unsupported"
    elif "incomplete" in problems:
        status = "incomplete"
    else:
        status = "estimated" if any(record.source.source_status == "forecast" for record in events) else "confirmed"
    return ShareEvidence(status, originals, events, tuple(replacements.items()), tuple(warnings))
