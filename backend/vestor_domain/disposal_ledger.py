"""Normalize ordinary share disposals and separately value trade and cash evidence."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction

from .events import ResultStatus
from .fx import FxConversion, FxRates
from .primitives import InputError, Problem, rounded_pennies
from .share_evidence import Fee, Sale, ShareEvidence, ShareRecord, Vest, WithholdingLink, validate_share_evidence
from .tax_year import TaxYear


@dataclass(frozen=True)
class DisposalFee:
    source: Fee
    gbp: Fraction | None
    fx: FxConversion | None
    warnings: tuple[Problem, ...] = ()


@dataclass(frozen=True)
class Disposal:
    sale: Sale
    tax_year_start: int | None
    gross_native: Fraction | None
    gross_gbp: Fraction | None
    proceeds_fx: FxConversion | None
    fees: tuple[DisposalFee, ...]
    eligible_fees_gbp: Fraction | None
    net_tax_proceeds_gbp: Fraction | None
    net_broker_proceeds_gbp: Fraction | None
    withholding_ids: tuple[str, ...]
    status: ResultStatus
    broker_status: ResultStatus
    warnings: tuple[Problem, ...]
    broker_warnings: tuple[Problem, ...]
    withholding_warnings: tuple[Problem, ...]


@dataclass(frozen=True)
class DisposalLedger:
    evidence: ShareEvidence
    disposals: tuple[Disposal, ...]


def _fee(fee: Fee, sale: Sale, rates: FxRates) -> DisposalFee:
    key = fee.source.event_id
    if fee.category is None:
        return DisposalFee(fee, None, None, (Problem("incomplete", key, "Confirm whether this expense is eligible for CGT."),))
    if fee.category == "cash_transfer":
        return DisposalFee(fee, None, None)
    if fee.amount is None or fee.on is None or fee.source.source_status == "unknown":
        return DisposalFee(fee, None, None, (Problem("incomplete", key, "Confirm the broker fee amount and date."),))
    if sale.trade_on is None or fee.on != sale.trade_on:
        return DisposalFee(fee, None, None, (Problem("incomplete", key, "Only trade-day fee valuations are supported."),))
    if fee.currency == "GBP":
        return DisposalFee(fee, Fraction(fee.amount), None)
    fx = rates.convert(fee.amount, on=fee.on, purpose="disposal_fee", rate_id=fee.rate_id,
                       source_status=fee.source.source_status)
    return DisposalFee(fee, fx.amount_gbp, fx, fx.warnings)


def _fee_estimated(line: DisposalFee) -> bool:
    return line.source.source.source_status == "forecast" or (line.fx is not None and line.fx.status == "estimated")


def _with_problems(status: ResultStatus, warnings: Iterable[Problem]) -> ResultStatus:
    problems = {warning.status for warning in warnings}
    if "input_error" in problems:
        return "input_error"
    if "unsupported" in problems:
        return "unsupported"
    if "incomplete" in problems:
        return "incomplete"
    return status


def _disposal(
    sale: Sale, fees: list[Fee], links: list[WithholdingLink], vest: Vest | None,
    rates: FxRates,
) -> Disposal:
    key = sale.source.event_id
    warnings: list[Problem] = []
    if sale.security.capacity != "personal" or sale.security.ordinary_listed is False or sale.uk_resident is False:
        warnings.append(Problem("unsupported", key, "Use an ordinary UK-resident trade in a personal capacity."))
    elif None in (sale.security.ordinary_listed, sale.uk_resident) or sale.source.source_status == "unknown":
        warnings.append(Problem("incomplete", key, "Confirm the trade source, security and UK residence."))
    if sale.vest_id is not None and (
        vest is None or vest.security.identity != sale.security.identity
        or (sale.trade_on is not None and vest.acquired_on is not None and sale.trade_on < vest.acquired_on)
    ):
        warnings.append(Problem("input_error", "vest_id", "Link the same-identity acquisition on or before the cover sale."))
    elif vest is not None and vest.acquired_on is None:
        warnings.append(Problem("incomplete", "vest_id", "Confirm the acquisition date for the cover sale."))

    year = None
    if sale.trade_on is not None:
        try:
            year = TaxYear.for_date(sale.trade_on).start_year
        except InputError:
            warnings.append(Problem("input_error", "trade_on", "Use a trade date in a representable UK tax year."))

    quantity, price = sale.quantity, sale.price_per_share
    gross = None
    fx = None
    gross_gbp = None
    if quantity is None or price is None or sale.trade_on is None:
        warnings.append(Problem("incomplete", key, "Confirm the trade date, quantity and price per share."))
    elif sale.source.source_status != "unknown":
        gross = Fraction(quantity) * Fraction(price)
        if sale.gross_amount is not None and gross != Fraction(sale.gross_amount) and (
            Fraction(rounded_pennies(gross), 100) != Fraction(sale.gross_amount)
        ):
            warnings.append(Problem("input_error", "gross_amount", "Reconcile reported gross proceeds with shares times price."))
            gross = None
        elif sale.currency == "GBP":
            gross_gbp = gross
        else:
            fx = rates.convert(price, quantity=quantity, on=sale.trade_on, purpose="disposal_proceeds",
                               rate_id=sale.rate_id, source_status=sale.source.source_status)
            gross_gbp = fx.amount_gbp
            warnings.extend(fx.warnings)

    fee_lines = tuple(_fee(fee, sale, rates) for fee in fees)
    if not sale.fees_confirmed:
        warnings.append(Problem("incomplete", "fees_confirmed", "Confirm completeness of trade fees or explicit absence."))
    for fee_line in fee_lines:
        if fee_line.source.category in (None, "eligible_dealing"):
            warnings.extend(fee_line.warnings)
    broker_warnings = tuple(warning for line in fee_lines if line.source.category == "other_broker"
                            for warning in line.warnings)

    eligible = None
    if sale.fees_confirmed and all(
        line.source.category is not None
        and (line.gbp is not None or line.source.category != "eligible_dealing")
        for line in fee_lines
    ):
        eligible = sum((line.gbp for line in fee_lines
                        if line.source.category == "eligible_dealing" and line.gbp is not None), Fraction(0))
    status: ResultStatus = "estimated" if (
        sale.source.source_status == "forecast" or (fx is not None and fx.status == "estimated")
        or any(line.source.category == "eligible_dealing" and _fee_estimated(line) for line in fee_lines)
    ) else "confirmed"
    status = _with_problems(status, warnings)

    net_tax = gross_gbp - eligible if not warnings and gross_gbp is not None and eligible is not None else None
    other_broker = sum((line.gbp for line in fee_lines
                        if line.source.category == "other_broker" and line.gbp is not None), Fraction(0))
    broker_status = status
    if status == "confirmed" and any(
        line.source.category == "other_broker" and _fee_estimated(line) for line in fee_lines
    ):
        broker_status = "estimated"
    broker_status = _with_problems(broker_status, (*warnings, *broker_warnings))
    withholding_ids = tuple(
        link.source.event_id for link in links
        if link.vest_id == sale.vest_id and sale.purpose == "sell_to_cover" and (
            link.remitted_on is None or sale.trade_on is None or link.remitted_on >= sale.trade_on
        )
    )
    withholding_warnings: tuple[Problem, ...] = ()
    if sale.purpose == "sell_to_cover" and not withholding_ids:
        withholding_warnings = (Problem("incomplete", key, "Supply separate linked withholding or remittance evidence."),)
    return Disposal(
        sale, year, gross, gross_gbp, fx, fee_lines, eligible, net_tax,
        net_tax - other_broker if net_tax is not None and not broker_warnings else None,
        withholding_ids, status, broker_status, tuple(dict.fromkeys(warnings)),
        broker_warnings, withholding_warnings,
    )


def calculate_disposal_ledger(records: Iterable[ShareRecord], rates: FxRates) -> DisposalLedger:
    """Resolve active trades before valuation. Ledger-level history gates matching."""
    evidence = validate_share_evidence(records)
    fees: dict[str, list[Fee]] = defaultdict(list)
    withholding: dict[str, list[WithholdingLink]] = defaultdict(list)
    vests = {}
    for record in evidence.active:
        if isinstance(record, Fee):
            fees[record.transaction_id].append(record)
        elif isinstance(record, WithholdingLink) and record.sale_id is not None:
            withholding[record.sale_id].append(record)
        elif isinstance(record, Vest):
            vests[record.source.event_id] = record
    disposals = tuple(
        _disposal(sale, fees[sale.source.event_id], withholding[sale.source.event_id],
                  vests.get(sale.vest_id) if sale.vest_id is not None else None, rates)
        for sale in evidence.active if isinstance(sale, Sale)
    )
    return DisposalLedger(evidence, disposals)
