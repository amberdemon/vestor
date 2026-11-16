"""Same-day and following-30-day share identification before Section 104."""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from typing import Literal

from .disposal_ledger import Disposal, DisposalLedger
from .events import ResultStatus
from .primitives import InputError, Problem
from .share_evidence import Purchase, Vest

MatchRule = Literal["same_day", "following_30_days"]
RULES_VERSION = "uk-eng-ni-cgt-2026-27-v1"


@dataclass(frozen=True)
class AcquisitionBasis:
    """Total allowable GBP cost established by the upstream evidence."""

    gbp: Fraction
    status: Literal["confirmed", "estimated"]

    def __post_init__(self) -> None:
        if not isinstance(self.gbp, Fraction) or self.gbp < 0:
            raise InputError("basis_gbp", "Supply an exact nonnegative GBP basis.")
        if self.status not in ("confirmed", "estimated"):
            raise InputError("basis_status", "Use confirmed or estimated acquisition evidence.")


@dataclass(frozen=True)
class PrioritySegment:
    disposal_id: str
    disposed_on: date
    disposal_tax_year_start: int | None
    acquisition_id: str
    acquired_on: date
    quantity: Fraction
    basis_gbp: Fraction | None
    rule: MatchRule
    status: ResultStatus


@dataclass(frozen=True)
class PriorityMatches:
    status: ResultStatus
    segments: tuple[PrioritySegment, ...]
    acquisition_remainders: tuple[tuple[str, Fraction], ...]
    disposal_remainders: tuple[tuple[str, Fraction], ...]
    warnings: tuple[Problem, ...]
    rule_version: str = RULES_VERSION
    projected_identities: tuple[tuple[str, str, str, str], ...] = ()


@dataclass
class _Day:
    on: date
    acquisitions: list[Vest | Purchase]
    disposals: list[Disposal]
    acquired: Fraction
    sold: Fraction
    acquisition_remaining: Fraction
    disposal_remaining: Fraction


def _quantity(records: list[Vest | Purchase] | list[Disposal]) -> Fraction:
    return sum((
        Fraction(quantity) for record in records
        if (quantity := record.sale.quantity if isinstance(record, Disposal) else record.quantity) is not None
    ), Fraction(0))


def _reserve(
    disposal: _Day, acquisition: _Day, rule: MatchRule,
    bases: Mapping[str, AcquisitionBasis], *, projected_inventory: bool,
) -> list[PrioritySegment]:
    matched = min(disposal.disposal_remaining, acquisition.acquisition_remaining)
    if not matched:
        return []
    disposal.disposal_remaining -= matched
    acquisition.acquisition_remaining -= matched

    segments = []
    for row in disposal.disposals:
        assert row.sale.quantity is not None
        sold_share = Fraction(row.sale.quantity) / disposal.sold
        for lot in acquisition.acquisitions:
            assert lot.quantity is not None
            lot_share = Fraction(lot.quantity) / acquisition.acquired
            allocated = matched * sold_share * lot_share
            basis = bases.get(lot.source.event_id)
            status: ResultStatus
            if basis is None:
                status = "incomplete"
            elif projected_inventory or basis.status == "estimated":
                status = "estimated"
            else:
                status = "confirmed"
            segments.append(PrioritySegment(
                row.sale.source.event_id, disposal.on, row.tax_year_start, lot.source.event_id,
                acquisition.on, allocated, None if basis is None else allocated * basis.gbp / Fraction(lot.quantity),
                rule, status,
            ))
    return segments


def identify_priority_matches(ledger: DisposalLedger, bases: Mapping[str, AcquisitionBasis]) -> PriorityMatches:
    """Allocate exact day-weighted shares in TCGA ss105 and 106A order.

    Earlier disposal days take the earliest still eligible acquisitions, after
    every day's same-day reservation. Residues retain original row identities.
    """
    known_lots = {record.source.event_id for record in ledger.evidence.records
                  if isinstance(record, (Vest, Purchase))}
    if any(key not in known_lots for key in bases):
        raise InputError("acquisition_id", "Link each GBP basis to an acquisition in the ledger.")

    warnings = list(ledger.evidence.warnings)
    if ledger.evidence.status in ("unsupported", "input_error", "incomplete"):
        return PriorityMatches(
            ledger.evidence.status, (), (), (),
            tuple(sorted(set(warnings), key=lambda item: (item.status, item.field, item.message))),
        )

    Key = tuple[tuple[str, str, str, str], date]
    acquisitions: dict[Key, list[Vest | Purchase]] = defaultdict(list)
    disposals: dict[Key, list[Disposal]] = defaultdict(list)
    for raw in ledger.evidence.active:
        if isinstance(raw, (Vest, Purchase)):
            assert raw.acquired_on is not None and raw.quantity is not None
            acquisitions[raw.security.identity, raw.acquired_on].append(raw)
            if raw.source.event_id not in bases:
                warnings.append(Problem("incomplete", raw.source.event_id, "Supply the allowable GBP acquisition basis."))
    for disposal in ledger.disposals:
        sale = disposal.sale
        assert sale.trade_on is not None and sale.quantity is not None
        disposals[sale.security.identity, sale.trade_on].append(disposal)

    timelines: dict[tuple[str, str, str, str], list[_Day]] = defaultdict(list)
    for identity, on in sorted(acquisitions.keys() | disposals.keys()):
        lots = sorted(acquisitions.get((identity, on), ()), key=lambda row: row.source.event_id)
        sales = sorted(disposals.get((identity, on), ()), key=lambda row: row.sale.source.event_id)
        acquired, sold = _quantity(lots), _quantity(sales)
        timelines[identity].append(_Day(on, lots, sales, acquired, sold, acquired, sold))

    segments = []
    projected = {
        raw.security.identity for raw in ledger.evidence.active
        if isinstance(raw, (Vest, Purchase)) and raw.source.source_status == "forecast"
    }
    projected.update(
        row.sale.security.identity for row in ledger.disposals if row.sale.source.source_status == "forecast"
    )
    for identity, days in timelines.items():
        for day in days:
            segments.extend(_reserve(day, day, "same_day", bases, projected_inventory=identity in projected))
    for identity, days in timelines.items():
        acquisition_days = [day for day in days if day.acquisition_remaining]
        dates = [day.on for day in acquisition_days]
        for day in days:
            index = bisect_right(dates, day.on)
            while day.disposal_remaining and index < len(acquisition_days):
                acquisition = acquisition_days[index]
                if (acquisition.on - day.on).days > 30:
                    break
                segments.extend(_reserve(
                    day, acquisition, "following_30_days", bases, projected_inventory=identity in projected,
                ))
                index += 1

    acquisition_remainders: list[tuple[str, Fraction]] = []
    disposal_remainders: list[tuple[str, Fraction]] = []
    for days in timelines.values():
        for day in days:
            acquisition_remainders.extend(
                (row.source.event_id, Fraction(row.quantity) * day.acquisition_remaining / day.acquired)
                for row in day.acquisitions if row.quantity is not None
            )
            disposal_remainders.extend(
                (row.sale.source.event_id, Fraction(row.sale.quantity) * day.disposal_remaining / day.sold)
                for row in day.disposals if row.sale.quantity is not None
            )
    status: ResultStatus = ledger.evidence.status
    if warnings:
        status = "incomplete"
    elif any(bases[key].status == "estimated" for key, unused in acquisition_remainders if key in bases):
        status = "estimated"
    return PriorityMatches(
        status, tuple(segments), tuple(acquisition_remainders), tuple(disposal_remainders),
        tuple(sorted(set(warnings), key=lambda item: (item.status, item.field, item.message))),
        projected_identities=tuple(sorted(projected)),
    )
