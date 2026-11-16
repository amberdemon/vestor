"""Source-linked payroll settlements and observed cash, independent of tax calculations."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import Literal

from .disposal_ledger import Disposal, DisposalLedger, _with_problems
from .events import ResultStatus, _require_text
from .fx import FxConversion, FxRates
from .primitives import InputError, Problem, rounded_pennies
from .share_evidence import (
    Currency, ShareSource, Vest, WithholdingLink, _confirmation, _currency, _date, _decimal, _optional_id,
)

PayrollKind = Literal["liability", "withholding", "repayment", "reported_owed"]
PayrollMethod = Literal["payroll", "broker_cover", "employer_repayment"]
PayrollComponent = Literal["income_tax", "national_insurance", "combined"]


@dataclass(frozen=True)
class PayrollEntry:
    source: ShareSource
    vest_id: str
    on: date | None
    currency: Currency
    kind: PayrollKind
    amount: Decimal | None
    method: PayrollMethod
    liability_id: str | None = None
    withholding_link_id: str | None = None
    settled: bool | None = None
    transaction_ref: str | None = None
    component: PayrollComponent | None = None

    def __post_init__(self) -> None:
        _require_text(self.vest_id, "vest_id")
        _date(self.on, "on")
        _currency(self.currency, None)
        _decimal(self.amount, "amount")
        _confirmation(self.settled, "settled")
        _optional_id(self.liability_id, "liability_id")
        _optional_id(self.withholding_link_id, "withholding_link_id")
        _optional_id(self.transaction_ref, "transaction_ref")
        if self.component not in ("income_tax", "national_insurance", "combined", None) or (
            self.component is not None and self.kind != "liability"
        ):
            raise InputError("component", "Classify the payroll charge on the liability record.")
        if self.kind not in ("liability", "withholding", "repayment", "reported_owed"):
            raise InputError("kind", "Choose a payroll evidence kind.")
        if self.method not in ("payroll", "broker_cover", "employer_repayment"):
            raise InputError("method", "Choose the identified payroll payment method.")
        if self.kind in ("liability", "reported_owed"):
            if self.method != "payroll" or any(value is not None for value in (
                self.withholding_link_id, self.settled, self.transaction_ref,
            )):
                raise InputError("kind", "Liability and reported balance are independent of payment execution.")
        elif self.kind == "repayment" and self.method != "employer_repayment":
            raise InputError("method", "Use employer repayment for this entry.")
        elif self.kind == "withholding" and self.method == "employer_repayment":
            raise InputError("method", "Use payroll or broker cover for withholding.")
        if self.kind == "liability" and self.liability_id is not None:
            raise InputError("liability_id", "A liability is its own source record.")
        if self.method != "broker_cover" and self.withholding_link_id is not None:
            raise InputError("withholding_link_id", "Only broker cover references a cover remittance link.")


@dataclass(frozen=True)
class BrokerTransfer:
    source: ShareSource
    transaction_ref: str | None
    executed_on: date | None
    received_on: date | None
    sent_usd: Decimal | None
    fee_usd: Decimal | None
    fee_gbp: Decimal | None
    received_gbp: Decimal | None
    rate_id: str | None
    reference_rate_id: str | None = None

    def __post_init__(self) -> None:
        for field in ("executed_on", "received_on"):
            _date(getattr(self, field), field)
        for field in ("sent_usd", "fee_usd", "fee_gbp", "received_gbp"):
            _decimal(getattr(self, field), field)
        for field in ("transaction_ref", "rate_id", "reference_rate_id"):
            _optional_id(getattr(self, field), field)
        if self.executed_on is not None and self.received_on is not None and self.received_on < self.executed_on:
            raise InputError("received_on", "Receipt cannot precede transfer execution.")
        if self.sent_usd is not None and self.fee_usd is not None and self.fee_usd > self.sent_usd:
            raise InputError("fee_usd", "The deducted USD fee cannot exceed the amount sent.")


@dataclass(frozen=True)
class BrokerBalance:
    source: ShareSource
    on: date | None
    currency: Currency
    amount: Decimal | None

    def __post_init__(self) -> None:
        _date(self.on, "on")
        _currency(self.currency, None)
        _decimal(self.amount, "amount")


CashRecord = BrokerTransfer | BrokerBalance
SettlementRecord = PayrollEntry | CashRecord


@dataclass(frozen=True)
class PayrollSettlement:
    liability: PayrollEntry
    entries: tuple[PayrollEntry, ...]
    withheld: Fraction
    repaid: Fraction
    reported_owed: Fraction | None
    reconciliation_difference: Fraction | None
    status: ResultStatus
    warnings: tuple[Problem, ...]

    @property
    def withheld_gbp(self) -> Fraction | None:
        return self.withheld if self.liability.currency == "GBP" else None

    @property
    def repaid_gbp(self) -> Fraction | None:
        return self.repaid if self.liability.currency == "GBP" else None

    @property
    def reported_owed_gbp(self) -> Fraction | None:
        return self.reported_owed if self.liability.currency == "GBP" else None

    @property
    def reconciliation_difference_gbp(self) -> Fraction | None:
        return self.reconciliation_difference if self.liability.currency == "GBP" else None


@dataclass(frozen=True)
class TransferSettlement:
    source: BrokerTransfer
    execution_fx: FxConversion
    reference_fx: FxConversion | None
    actual_received_gbp: Fraction | None
    expected_received_gbp: Fraction | None
    receipt_difference_gbp: Fraction | None
    fx_spread_gbp: Fraction | None
    status: ResultStatus
    warnings: tuple[Problem, ...]


@dataclass(frozen=True)
class CoverCash:
    disposal: Disposal
    remittance_ids: tuple[str, ...]
    net_broker_proceeds_gbp: Fraction | None
    after_linked_remittance_gbp: Fraction | None
    warnings: tuple[Problem, ...]


@dataclass(frozen=True)
class Settlement:
    sources: tuple[SettlementRecord, ...]
    replacements: tuple[tuple[str, str], ...]
    payroll: tuple[PayrollSettlement, ...]
    transfers: tuple[TransferSettlement, ...]
    balances: tuple[BrokerBalance, ...]
    cover_cash: tuple[CoverCash, ...]
    payroll_status: ResultStatus
    cash_status: ResultStatus
    payroll_warnings: tuple[Problem, ...]
    cash_warnings: tuple[Problem, ...]


def _active(
    sources: tuple[SettlementRecord, ...], existing_ids: set[str], share_replacements: dict[str, str],
) -> tuple[tuple[SettlementRecord, ...], dict[str, str]]:
    indexed = {entry.source.event_id: entry for entry in sources}
    if len(indexed) != len(sources) or existing_ids.intersection(indexed):
        raise InputError("event_id", "Use unique identifiers across share and settlement records.")
    replacements: dict[str, str] = {}
    for key, actual in indexed.items():
        forecast_id = actual.source.replaces_forecast_id
        if forecast_id is None:
            continue
        forecast = indexed.get(forecast_id)
        if (
            forecast is None or type(forecast) is not type(actual)
            or forecast.source.source_status != "forecast" or forecast_id in replacements
        ):
            raise InputError("replaces_forecast_id", "Link a single compatible settlement forecast.")
        if isinstance(actual, PayrollEntry) and isinstance(forecast, PayrollEntry) and (
            actual.kind != forecast.kind or actual.method != forecast.method
            or actual.vest_id != share_replacements.get(forecast.vest_id, forecast.vest_id)
            or actual.currency != forecast.currency
            or (actual.component or "combined") != (forecast.component or "combined")
        ):
            raise InputError("replaces_forecast_id", "Link the same vest, method, currency and evidence kind.")
        if isinstance(actual, BrokerBalance) and isinstance(forecast, BrokerBalance) and (
            actual.currency != forecast.currency or actual.on != forecast.on
        ):
            raise InputError("replaces_forecast_id", "Link the same dated balance and currency.")
        if isinstance(actual, BrokerTransfer) and isinstance(forecast, BrokerTransfer) and (
            actual.transaction_ref is not None and forecast.transaction_ref is not None
            and actual.transaction_ref != forecast.transaction_ref
        ):
            raise InputError("replaces_forecast_id", "Link the same broker transfer reference.")
        replacements[forecast_id] = key
    for forecast_id, actual_id in replacements.items():
        forecast, actual = indexed[forecast_id], indexed[actual_id]
        if isinstance(forecast, PayrollEntry) and isinstance(actual, PayrollEntry):
            parent, link = forecast.liability_id, forecast.withholding_link_id
            if (
                actual.liability_id != (replacements.get(parent, parent) if parent is not None else None)
                or actual.withholding_link_id != (share_replacements.get(link, link) if link is not None else None)
            ):
                raise InputError("replaces_forecast_id", "The replacement must refer to the same payroll obligations.")
    return tuple(entry for key, entry in indexed.items() if key not in replacements), replacements


def _payroll(
    liability: PayrollEntry,
    children: list[PayrollEntry],
    cover_links: dict[str, WithholdingLink],
    vest_ids: set[str],
    duplicate_refs: set[str],
    coverage: bool,
) -> tuple[PayrollSettlement, tuple[PayrollEntry, ...]]:
    warnings: list[Problem] = []
    valid_payments = []
    reported: list[PayrollEntry] = []
    key = liability.source.event_id
    if liability.vest_id not in vest_ids:
        warnings.append(Problem("input_error", key, "Link the active vest for this payroll liability."))
    for entry in (liability, *children):
        if entry.amount is None or entry.on is None or entry.source.source_status == "unknown":
            warnings.append(Problem("incomplete", entry.source.event_id, "Confirm the amount, date and source status."))
            continue
        if entry is liability:
            continue
        if entry.currency != liability.currency or entry.vest_id != liability.vest_id:
            warnings.append(Problem("input_error", entry.source.event_id, "Use the liability’s vest and currency."))
            continue
        if liability.on is not None and entry.on < liability.on:
            warnings.append(Problem("input_error", entry.source.event_id, "Use a settlement date on or after the liability date."))
            continue
        if entry.kind == "reported_owed":
            reported.append(entry)
            continue
        if entry.transaction_ref is None or entry.settled is not True:
            warnings.append(Problem("incomplete", entry.source.event_id, "Confirm the unique payment reference and settled status."))
            continue
        if entry.transaction_ref in duplicate_refs:
            warnings.append(Problem("input_error", entry.source.event_id, "Reconcile duplicate payment references."))
            continue
        if entry.method == "broker_cover":
            link = cover_links.get(entry.withholding_link_id or "")
            if link is None or link.vest_id != entry.vest_id:
                warnings.append(Problem("input_error", entry.source.event_id, "Link the cover remittance for this vest."))
                continue
            if link.remitted_on is None or link.remitted_on != entry.on or (
                entry.source.source_status == "actual" and link.source.source_status != "actual"
            ):
                warnings.append(Problem("incomplete", entry.source.event_id, "Confirm the dated cover remittance evidence."))
                continue
        valid_payments.append(entry)

    withheld = sum((Fraction(entry.amount) for entry in valid_payments
                    if entry.kind == "withholding" and entry.amount is not None), Fraction(0))
    repaid = sum((Fraction(entry.amount) for entry in valid_payments
                  if entry.kind == "repayment" and entry.amount is not None), Fraction(0))
    owed = None
    reported_on = None
    if len(reported) == 1 and reported[0].amount is not None:
        owed = Fraction(reported[0].amount)
        reported_on = reported[0].on
    else:
        warnings.append(Problem("input_error" if reported else "incomplete", key, "Supply one separately reported outstanding balance, including zero."))
    if not coverage:
        warnings.append(Problem("incomplete", key, "Confirm coverage of payroll liabilities and payment entries."))
    difference = None
    if not warnings and liability.amount is not None and owed is not None and reported_on is not None:
        paid_as_of = sum((Fraction(entry.amount) for entry in valid_payments
                          if entry.amount is not None and entry.on is not None and entry.on <= reported_on),
                         Fraction(0))
        difference = Fraction(liability.amount) - paid_as_of - owed
    if difference:
        warnings.append(Problem("incomplete", key, "Reconcile settled payments and the separately reported balance."))
    status = _status((liability, *children), warnings)
    return PayrollSettlement(liability, tuple(children), withheld, repaid, owed, difference, status, tuple(warnings)), tuple(valid_payments)


def _transfer(row: BrokerTransfer, rates: FxRates, duplicate_refs: set[str]) -> TransferSettlement:
    key = row.source.event_id
    execution = rates.convert(row.sent_usd, on=row.executed_on, purpose="cash_settlement",
                              rate_id=row.rate_id, source_status=row.source.source_status)
    reference = None
    if row.reference_rate_id is not None:
        reference = rates.convert(row.sent_usd, on=row.executed_on, purpose="cash_settlement",
                                  rate_id=row.reference_rate_id, source_status=row.source.source_status)
    warnings = list(execution.warnings)
    if reference is not None:
        warnings.extend(reference.warnings)
    if row.transaction_ref is None:
        warnings.append(Problem("incomplete", key, "Confirm the transfer reference."))
    elif row.transaction_ref in duplicate_refs:
        warnings.append(Problem("input_error", key, "Reconcile duplicate transfer references."))
    actual = None
    if row.source.source_status == "actual" and row.received_on is not None and row.received_gbp is not None:
        actual = Fraction(row.received_gbp)
    if actual is None:
        warnings.append(Problem("incomplete", key, "Confirm the evidenced GBP receipt and its date."))
    expected = spread = difference = None
    quote = execution.rate
    if (
        execution.amount_gbp is not None and quote is not None and quote.gbp_per_usd is not None
        and row.fee_usd is not None and row.fee_gbp is not None
    ):
        expected = execution.amount_gbp - Fraction(row.fee_usd) * Fraction(quote.gbp_per_usd) - Fraction(row.fee_gbp)
        if expected < 0:
            expected = None
            warnings.append(Problem("input_error", key, "The fixed fees exceed the converted amount."))
        if reference is not None and reference.amount_gbp is not None and reference.rate is not None and (
            reference.rate.gbp_per_usd is not None
        ):
            spread = reference.amount_gbp - execution.amount_gbp - Fraction(row.fee_usd) * (
                Fraction(reference.rate.gbp_per_usd) - Fraction(quote.gbp_per_usd)
            )
    else:
        warnings.append(Problem("incomplete", key, "Supply execution FX and both fixed fees, including explicit zero."))
    if expected is not None and actual is not None and execution.status == "confirmed":
        difference = actual - expected
        if difference and actual != Fraction(rounded_pennies(expected), 100):
            warnings.append(Problem("incomplete", key, "Reconcile actual GBP received with execution FX and fees."))
    status = _status((row,), warnings)
    if status == "confirmed" and (execution.status == "estimated" or (reference is not None and reference.status == "estimated")):
        status = "estimated"
    return TransferSettlement(row, execution, reference, actual, expected, difference, spread, status, tuple(warnings))


def _duplicate_refs(refs: Iterable[str | None]) -> set[str]:
    seen = set()
    duplicates = set()
    for ref in refs:
        if ref is None:
            continue
        if ref in seen:
            duplicates.add(ref)
        seen.add(ref)
    return duplicates


def _status(records: Iterable[SettlementRecord], warnings: Iterable[Problem]) -> ResultStatus:
    baseline: ResultStatus = "estimated" if any(record.source.source_status == "forecast" for record in records) else "confirmed"
    return _with_problems(baseline, warnings)


def calculate_settlement(
    ledger: DisposalLedger, payroll_entries: Iterable[PayrollEntry], cash_entries: Iterable[CashRecord],
    rates: FxRates, *, payroll_coverage: bool, cash_coverage: bool,
) -> Settlement:
    """Reconcile explicitly dated payments and receipts without modifying tax evidence."""
    if type(payroll_coverage) is not bool or type(cash_coverage) is not bool:
        raise InputError("coverage", "Confirm the scope of payroll and cash evidence.")
    sources: tuple[SettlementRecord, ...] = (*payroll_entries, *cash_entries)
    active, replacements = _active(
        sources, {record.source.event_id for record in ledger.evidence.records}, dict(ledger.evidence.replacements),
    )
    vest_ids = {record.source.event_id for record in ledger.evidence.active if isinstance(record, Vest)}
    cover_links = {record.source.event_id: record for record in ledger.evidence.active if isinstance(record, WithholdingLink)}
    valid_links = {link for sale in ledger.disposals for link in sale.withholding_ids}
    cover_links = {key: link for key, link in cover_links.items() if key in valid_links}
    payroll = [entry for entry in active if isinstance(entry, PayrollEntry)]
    liabilities = {entry.source.event_id: entry for entry in payroll if entry.kind == "liability"}
    children: dict[str, list[PayrollEntry]] = defaultdict(list)
    payroll_warnings = []
    if not payroll_coverage:
        payroll_warnings.append(Problem("incomplete", "payroll_coverage", "Confirm all relevant payroll settlement entries."))
    for entry in payroll:
        if entry.kind == "liability":
            continue
        if entry.liability_id is None or entry.liability_id not in liabilities:
            payroll_warnings.append(Problem("input_error", entry.source.event_id, "Link the active payroll liability."))
        else:
            children[entry.liability_id].append(entry)
    duplicates = _duplicate_refs(entry.transaction_ref for entry in payroll)

    groups = []
    remittances: dict[str, list[PayrollEntry]] = defaultdict(list)
    charges: dict[str, set[PayrollComponent]] = defaultdict(set)
    for key, liability in liabilities.items():
        component = liability.component or "combined"
        prior = charges[liability.vest_id]
        if component in prior or "combined" in prior or (component == "combined" and prior):
            payroll_warnings.append(Problem("input_error", key, "Reconcile overlapping tax and NI liabilities for this vest."))
        prior.add(component)
        group, payments = _payroll(liability, children[key], cover_links, vest_ids, duplicates, payroll_coverage)
        groups.append(group)
        payroll_warnings.extend(group.warnings)
        for payment in payments:
            if payment.withholding_link_id is not None:
                remittances[payment.withholding_link_id].append(payment)

    wires = [row for row in active if isinstance(row, BrokerTransfer)]
    wire_duplicates = _duplicate_refs(row.transaction_ref for row in wires)
    transfers = tuple(_transfer(row, rates, wire_duplicates) for row in wires)
    balances = tuple(row for row in active if isinstance(row, BrokerBalance))
    cash_warnings = [warning for row in transfers for warning in row.warnings]
    if not cash_coverage:
        cash_warnings.append(Problem("incomplete", "cash_coverage", "Confirm the scope of cash and transfer evidence."))
    for balance in balances:
        if balance.on is None or balance.amount is None or balance.source.source_status == "unknown":
            cash_warnings.append(Problem("incomplete", balance.source.event_id, "Confirm the dated broker balance."))

    cover_cash = tuple(
        _cover_cash(sale, remittances, payroll_coverage and not payroll_warnings)
        for sale in ledger.disposals if sale.sale.purpose == "sell_to_cover"
    )
    cash_warnings.extend(warning for row in cover_cash for warning in row.warnings)
    cash_status = _status((row for row in active if not isinstance(row, PayrollEntry)), cash_warnings)
    if cash_status == "confirmed" and any(row.status == "estimated" for row in transfers):
        cash_status = "estimated"
    return Settlement(sources, tuple(replacements.items()), tuple(groups), transfers, balances, cover_cash,
                      _status(payroll, payroll_warnings), cash_status, tuple(payroll_warnings), tuple(cash_warnings))


def _cover_cash(
    sale: Disposal, remittances: dict[str, list[PayrollEntry]], coverage: bool,
) -> CoverCash:
    payments = tuple(payment for link_id in sale.withholding_ids for payment in remittances[link_id])
    refs = tuple(payment.source.event_id for payment in payments)
    net = sale.net_broker_proceeds_gbp
    after = None
    warnings: tuple[Problem, ...] = ()
    if (
        coverage and net is not None and sale.broker_status == "confirmed" and sale.sale.currency == "GBP"
        and all(row.source.currency == "GBP" for row in sale.fees if row.source.category != "cash_transfer")
        and payments and all(payment.currency == "GBP" and payment.source.source_status == "actual" for payment in payments)
    ):
        after = net - sum((Fraction(payment.amount) for payment in payments if payment.amount is not None), Fraction(0))
        if after < 0:
            after = None
            warnings = (Problem("incomplete", sale.sale.source.event_id, "Linked remittance exceeds the evidenced broker proceeds."),)
    else:
        warnings = (Problem("incomplete", sale.sale.source.event_id, "Confirm same-currency GBP broker proceeds and linked remittances."),)
    return CoverCash(sale, refs, net, after, warnings)
