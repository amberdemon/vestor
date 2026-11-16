"""Orchestrate M1 ANI and M2 domains over one transient set of source evidence."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from decimal import Decimal
from fractions import Fraction

from .ani import AniInputs, AniResult
from .annual_cgt import AnnualCgt, BandEvidence, CapitalEvidence, CgtInputs, calculate_annual_cgt
from .disposal_ledger import DisposalLedger, calculate_disposal_ledger
from .fx import FxConversion, FxRate, FxRates
from .primitives import InputError, Problem
from .priority_matching import AcquisitionBasis
from .settlement import (
    BrokerBalance, BrokerTransfer, PayrollEntry, Settlement, SettlementRecord, calculate_settlement,
)
from .share_evidence import (
    Fee, Grant, OpeningHolding, Purchase, Sale, ShareRecord, Vest, WithholdingLink, validate_share_evidence,
)
from .share_gains import ShareGains, calculate_share_gains
from .vest_valuation import BasisMethod, VestValuation, VestValuationInput, calculate_ani_with_vests, value_vest


@dataclass(frozen=True)
class VestInput:
    vest: Vest
    included_in_payroll: bool | None = None
    payroll_ids: tuple[str, ...] = ()
    gross_usd: Decimal | None = None
    confirmed_payroll_gbp: Decimal | None = None
    basis_method: BasisMethod | None = None
    confirmed_basis_gbp: Decimal | None = None
    manual_vest_id: str | None = None
    replaces_manual_forecast_id: str | None = None
    acquisition_fees_confirmed: bool = False

    def link_grant(self, grant: Grant) -> VestValuationInput:
        return VestValuationInput(
            self.vest, grant, self.included_in_payroll, self.payroll_ids, self.gross_usd,
            self.confirmed_payroll_gbp, self.basis_method, self.confirmed_basis_gbp,
            self.manual_vest_id, self.replaces_manual_forecast_id,
        )


@dataclass(frozen=True)
class AnnualEvidence:
    ordinary_treatment: bool | None = None
    eligible_for_aea: bool | None = None
    share_coverage_confirmed: bool = False
    capital: CapitalEvidence | None = None
    band: BandEvidence | None = None


@dataclass(frozen=True)
class M2Inputs:
    ani: AniInputs
    grants: tuple[Grant, ...] = ()
    vests: tuple[VestInput, ...] = ()
    opening_holdings: tuple[OpeningHolding, ...] = ()
    purchases: tuple[Purchase, ...] = ()
    sales: tuple[Sale, ...] = ()
    fees: tuple[Fee, ...] = ()
    withholding_links: tuple[WithholdingLink, ...] = ()
    rates: tuple[FxRate, ...] = ()
    annual: AnnualEvidence = AnnualEvidence()
    payroll_entries: tuple[PayrollEntry, ...] = ()
    transfers: tuple[BrokerTransfer, ...] = ()
    broker_balances: tuple[BrokerBalance, ...] = ()
    payroll_coverage: bool = False
    cash_coverage: bool = False


@dataclass(frozen=True)
class AcquisitionValuation:
    acquisition_id: str
    cost_gbp: Fraction | None
    basis: AcquisitionBasis | None
    acquisition_fx: FxConversion | None
    fee_fx: tuple[FxConversion, ...]
    fee_ids: tuple[str, ...]
    warnings: tuple[Problem, ...]


@dataclass(frozen=True)
class M2Result:
    version: str
    ani: AniResult
    vests: tuple[VestValuation, ...]
    rates: tuple[FxRate, ...]
    ledger: DisposalLedger
    acquisitions: tuple[AcquisitionValuation, ...]
    share_gains: ShareGains
    annual_cgt: AnnualCgt
    settlement: Settlement


def _acquisition(
    record: Purchase | Vest, detail: VestInput | None, valuation: VestValuation | None,
    fees: list[Fee], rates: FxRates,
) -> AcquisitionValuation:
    key = record.source.event_id
    fx = None
    cost = None
    estimated = record.source.source_status == "forecast"
    warnings: list[Problem] = []
    if record.acquired_on is None or record.quantity is None or record.source.source_status == "unknown":
        warnings.append(Problem("incomplete", key, "Confirm the acquisition date, quantity and source."))
    if record.security.capacity != "personal" or record.security.ordinary_listed is False or record.uk_resident is False:
        warnings.append(Problem("unsupported", key, "Use only supported ordinary share acquisitions."))
    elif record.security.ordinary_listed is None or record.uk_resident is None:
        warnings.append(Problem("incomplete", key, "Confirm ordinary listed shares and UK residence."))
    if isinstance(record, Purchase):
        if record.currency == "GBP" and record.gross_amount is not None:
            cost = Fraction(record.gross_amount)
        elif record.currency == "USD":
            fx = rates.convert(record.gross_amount, on=record.acquired_on, purpose="acquisition_basis",
                               rate_id=record.rate_id, source_status=record.source.source_status)
            cost = fx.amount_gbp
            warnings.extend(fx.warnings)
            estimated |= fx.status == "estimated"
        confirmed = record.fees_confirmed
        included = False
    else:
        assert detail is not None and valuation is not None
        cost = valuation.basis_gbp
        fx = valuation.acquisition_fx
        warnings.extend(valuation.basis_warnings)
        estimated |= valuation.basis_status == "estimated"
        confirmed = detail.acquisition_fees_confirmed
        included = detail.confirmed_basis_gbp is not None
    if not confirmed and not included:
        warnings.append(Problem("incomplete", key, "Confirm coverage of allowable acquisition expenses."))
    if cost is None:
        warnings.append(Problem("incomplete", key, "Supply the allowable acquisition cost and evidence."))

    fee_fx = []
    expenses = Fraction(0)
    for fee in fees:
        if fee.category is None:
            warnings.append(Problem("incomplete", fee.source.event_id, "Classify the acquisition expense."))
        if fee.category != "eligible_dealing" or included:
            # The confirmed GBP amount is the total allowable acquisition basis.
            continue
        if fee.on is None or fee.on != record.acquired_on or fee.amount is None or fee.source.source_status == "unknown":
            warnings.append(Problem("incomplete", fee.source.event_id, "Confirm the eligible expense and acquisition date."))
            continue
        estimated |= fee.source.source_status == "forecast"
        if fee.currency == "GBP":
            expenses += Fraction(fee.amount)
        else:
            conversion = rates.convert(fee.amount, on=fee.on, purpose="acquisition_fee", rate_id=fee.rate_id,
                                       source_status=fee.source.source_status)
            fee_fx.append(conversion)
            warnings.extend(conversion.warnings)
            estimated |= conversion.status == "estimated"
            if conversion.amount_gbp is not None:
                expenses += conversion.amount_gbp
    basis = None if warnings or cost is None else AcquisitionBasis(cost + expenses, "estimated" if estimated else "confirmed")
    return AcquisitionValuation(key, cost, basis, fx, tuple(fee_fx),
                                tuple(fee.source.event_id for fee in fees), tuple(warnings))


def calculate_m2(raw: M2Inputs) -> M2Result:
    records: tuple[ShareRecord, ...] = (
        *raw.grants, *(item.vest for item in raw.vests), *raw.opening_holdings,
        *raw.purchases, *raw.sales, *raw.fees, *raw.withholding_links,
    )
    settlement_records: tuple[SettlementRecord, ...] = (*raw.payroll_entries, *raw.transfers, *raw.broker_balances)
    sources = [
        *(record.source for record in records), *(rate.source for rate in raw.rates),
        *(entry.source for entry in settlement_records),
    ]
    if raw.annual.capital is not None:
        sources.append(raw.annual.capital.source)
    if raw.annual.band is not None:
        sources.append(raw.annual.band.source)
    if len({source.event_id for source in sources}) != len(sources):
        raise InputError("event_id", "Use one unique identifier per evidence record.")
    rates = FxRates(raw.rates)
    ledger = calculate_disposal_ledger(records, rates)
    grants = {grant.source.event_id: grant for grant in raw.grants}
    details = {item.vest.source.event_id: item for item in raw.vests}
    valuations = {}
    for key, item in details.items():
        grant = grants.get(item.vest.grant_id)
        if grant is None:
            raise InputError("grant_id", "Link the supplied vest to its grant.")
        valuations[key] = value_vest(item.link_grant(grant), rates)

    replacements = dict(ledger.evidence.replacements)
    ani = calculate_ani_with_vests(raw.ani, valuations.values(), grant_replacements=replacements)
    fees: dict[str, list[Fee]] = defaultdict(list)
    for record in ledger.evidence.active:
        if isinstance(record, Fee):
            fees[record.transaction_id].append(record)
    acquisitions = tuple(
        _acquisition(record, details.get(record.source.event_id), valuations.get(record.source.event_id),
                     fees[record.source.event_id], rates)
        for record in ledger.evidence.active if isinstance(record, (Purchase, Vest))
    )
    bases = {item.acquisition_id: item.basis for item in acquisitions if item.basis is not None}
    # Match inventory independently of optional cash evidence. Acquisition and
    # disposal valuations already carry the restrictions on their tax expenses.
    inventory = validate_share_evidence(
        record for record in records if not isinstance(record, (Fee, WithholdingLink))
    )
    gains = calculate_share_gains(replace(ledger, evidence=inventory), bases)
    annual = calculate_annual_cgt(gains, CgtInputs(
        raw.ani.start_year, raw.ani.jurisdiction, raw.annual.ordinary_treatment,
        raw.annual.eligible_for_aea, raw.annual.share_coverage_confirmed, raw.annual.capital, raw.annual.band,
    ))
    settlement = calculate_settlement(
        ledger, raw.payroll_entries, (*raw.transfers, *raw.broker_balances), rates,
        payroll_coverage=raw.payroll_coverage, cash_coverage=raw.cash_coverage,
    )
    return M2Result("2", ani, tuple(valuations.values()), raw.rates, ledger, acquisitions, gains, annual, settlement)
