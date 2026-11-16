"""Chronological Section 104 pools and exact realised GBP share gains."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from typing import Literal

from .disposal_ledger import Disposal, DisposalLedger, _with_problems
from .events import ResultStatus
from .primitives import Problem
from .priority_matching import AcquisitionBasis, PriorityMatches, PrioritySegment, identify_priority_matches
from .share_evidence import OpeningHolding, Purchase, Security, Vest


@dataclass(frozen=True)
class PoolState:
    quantity: Fraction
    cost_gbp: Fraction | None


@dataclass(frozen=True)
class PoolMovement:
    source_id: str
    security: Security
    on: date
    kind: Literal["opening", "acquisition", "disposal"]
    before: PoolState
    after: PoolState
    quantity: Fraction
    basis_gbp: Fraction | None
    status: ResultStatus


@dataclass(frozen=True)
class ShareGain:
    disposal: Disposal
    priority_segments: tuple[PrioritySegment, ...]
    pool_movement: PoolMovement | None
    matched_basis_gbp: Fraction | None
    gain_gbp: Fraction | None
    status: ResultStatus
    warnings: tuple[Problem, ...]


@dataclass(frozen=True)
class ShareGains:
    status: ResultStatus
    priority: PriorityMatches
    pool_movements: tuple[PoolMovement, ...]
    gains: tuple[ShareGain, ...]
    warnings: tuple[Problem, ...]

    @property
    def rule_version(self) -> str:
        return self.priority.rule_version


Identity = tuple[str, str, str, str]
_EMPTY = PoolState(Fraction(0), Fraction(0))


def _pool_movements(
    ledger: DisposalLedger, priority: PriorityMatches, bases: Mapping[str, AcquisitionBasis],
) -> tuple[tuple[PoolMovement, ...], dict[str, Problem]]:
    acquisitions = dict(priority.acquisition_remainders)
    disposals = dict(priority.disposal_remainders)
    if not disposals and not acquisitions and priority.status in ("input_error", "incomplete", "unsupported"):
        return (), {}
    movements = []
    pool: dict[Identity, PoolState] = {}
    estimated: set[Identity] = set()
    blocked: set[Identity] = set()
    issues: dict[str, Problem] = {}
    dated: list[tuple[date, int, str, OpeningHolding | Purchase | Vest | Disposal]] = []
    for source in ledger.evidence.active:
        key = source.source.event_id
        if isinstance(source, OpeningHolding) and source.as_of is not None:
            dated.append((source.as_of, 0, key, source))
        elif isinstance(source, (Vest, Purchase)) and source.acquired_on is not None and acquisitions.get(key):
            dated.append((source.acquired_on, 1, key, source))
    for row in ledger.disposals:
        sale = row.sale
        if sale.trade_on is not None and disposals.get(sale.source.event_id):
            dated.append((sale.trade_on, 2, sale.source.event_id, row))

    for on, _, key, record in sorted(dated, key=lambda item: item[:3]):
        security = record.sale.security if isinstance(record, Disposal) else record.security
        identity = security.identity
        before = pool.get(identity, _EMPTY)
        status: ResultStatus = "confirmed"
        kind: Literal["opening", "acquisition", "disposal"]
        basis: Fraction | None
        if isinstance(record, OpeningHolding):
            assert record.quantity is not None and record.cost_gbp is not None
            kind = "opening"
            quantity, basis = Fraction(record.quantity), Fraction(record.cost_gbp)
            after = PoolState(quantity, basis)
            if record.source.source_status == "forecast":
                estimated.add(identity)
        elif isinstance(record, (Vest, Purchase)):
            assert record.quantity is not None
            kind = "acquisition"
            quantity = acquisitions[key]
            supplied = bases.get(key)
            basis = None if supplied is None else supplied.gbp * quantity / Fraction(record.quantity)
            cost = None if before.cost_gbp is None or basis is None else before.cost_gbp + basis
            after = PoolState(before.quantity + quantity, cost)
            if record.source.source_status == "forecast" or (supplied is not None and supplied.status == "estimated"):
                estimated.add(identity)
        else:
            kind = "disposal"
            quantity = disposals[key]
            if identity in blocked or quantity > before.quantity:
                blocked.add(identity)
                issues[key] = Problem(
                    "unsupported", key, "The Section 104 pool cannot cover these shares. Later-acquisition fallback is outside scope.",
                )
                continue
            basis = None if before.cost_gbp is None else before.cost_gbp * quantity / before.quantity
            remaining = before.quantity - quantity
            cost = None if basis is None or before.cost_gbp is None else before.cost_gbp - basis
            if not remaining:
                cost = Fraction(0)
            after = PoolState(remaining, cost)

        if identity in blocked:
            continue
        if basis is None or after.cost_gbp is None:
            status = "incomplete"
        elif identity in estimated or priority.status == "estimated":
            status = "estimated"
        pool[identity] = after
        movements.append(PoolMovement(key, security, on, kind, before, after, quantity, basis, status))
        if not after.quantity:
            estimated.discard(identity)
    return tuple(movements), issues


def calculate_share_gains(ledger: DisposalLedger, bases: Mapping[str, AcquisitionBasis]) -> ShareGains:
    """Compute per-disposal gain after both priority rules and the Section 104 debit.

    Under TCGA s104 and HMRC CG51575, a residual part sale takes the same
    fraction of available GBP cost as the fraction of available shares sold.
    """
    priority = identify_priority_matches(ledger, bases)
    movements, pool_issues = _pool_movements(ledger, priority, bases)
    by_disposal = {row.source_id: row for row in movements if row.kind == "disposal"}
    segments: dict[str, list[PrioritySegment]] = defaultdict(list)
    for segment in priority.segments:
        segments[segment.disposal_id].append(segment)
    residual = dict(priority.disposal_remainders)
    gains = []
    for disposal in sorted(ledger.disposals, key=lambda row: (row.sale.trade_on or date.min, row.sale.source.event_id)):
        key = disposal.sale.source.event_id
        trace = tuple(segments[key])
        debit = by_disposal.get(key)
        warnings = list(disposal.warnings)
        if key not in residual:
            warnings.extend(priority.warnings)
        if key in pool_issues:
            warnings.append(pool_issues[key])
        costs = [row.basis_gbp for row in trace]
        if residual.get(key):
            costs.append(None if debit is None else debit.basis_gbp)
        basis = None
        if key in residual and all(cost is not None for cost in costs):
            basis = sum((cost for cost in costs if cost is not None), Fraction(0))
        if basis is None and not warnings:
            warnings.append(Problem("incomplete", key, "Confirm the full matched GBP acquisition basis."))
        status = _with_problems(disposal.status, warnings)
        if status == "confirmed" and (
            priority.status == "estimated"
            or any(row.status == "estimated" for row in trace)
            or (debit is not None and debit.status == "estimated")
        ):
            status = "estimated"
        gain = (
            disposal.net_tax_proceeds_gbp - basis
            if status in ("confirmed", "estimated") and disposal.net_tax_proceeds_gbp is not None and basis is not None
            else None
        )
        gains.append(ShareGain(disposal, trace, debit, basis, gain, status, tuple(dict.fromkeys(warnings))))

    all_warnings = tuple(dict.fromkeys((
        *priority.warnings, *pool_issues.values(), *(warning for row in gains for warning in row.warnings),
    )))
    overall: ResultStatus = "estimated" if any(row.status == "estimated" for row in gains) else priority.status
    return ShareGains(_with_problems(overall, all_warnings), priority, movements, tuple(gains), all_warnings)
