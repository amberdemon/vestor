"""Versioned, qualified annual CGT estimates from ordinary UK share gains."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from fractions import Fraction

from .disposal_ledger import _with_problems
from .events import ResultStatus
from .primitives import InputError, Problem, validate_gbp
from .priority_matching import RULES_VERSION
from .share_evidence import ShareSource, _confirmation
from .share_gains import ShareGain, ShareGains
from .tax_year import TaxYear


@dataclass(frozen=True)
class CgtRules:
    tax_year: TaxYear
    version: str
    annual_exempt_amount_gbp: Fraction
    basic_rate_band_gbp: Fraction
    basic_rate: Fraction
    higher_rate: Fraction
    verified_on: date
    source_urls: tuple[str, ...]


RULES = CgtRules(
    TaxYear(2026), RULES_VERSION, Fraction(3000), Fraction(37700), Fraction(18, 100), Fraction(24, 100),
    date(2026, 11, 14),
    (
        "https://www.gov.uk/government/publications/budget-2026-overview-of-tax-legislation-and-rates-ootlar/annex-a-rates-and-allowances",
        "https://www.gov.uk/capital-gains-tax/losses",
        "https://www.gov.uk/hmrc-internal-manuals/capital-gains-manual/cg21204",
    ),
)


@dataclass(frozen=True)
class CapitalEvidence:
    """Complete externally resolved ordinary gains and allowable losses outside the ledger."""

    source: ShareSource
    other_gains_gbp: Decimal | None
    other_current_losses_gbp: Decimal | None
    available_brought_forward_gbp: Decimal | None

    def __post_init__(self) -> None:
        validate_gbp(self.other_gains_gbp, field="other_gains_gbp")
        validate_gbp(self.other_current_losses_gbp, field="other_current_losses_gbp")
        validate_gbp(self.available_brought_forward_gbp, field="available_brought_forward_gbp")


@dataclass(frozen=True)
class BandEvidence:
    source: ShareSource
    unused_basic_band_gbp: Decimal | None = None
    taxable_income_gbp: Decimal | None = None
    basic_band_extension_gbp: Decimal | None = None

    def __post_init__(self) -> None:
        validate_gbp(self.unused_basic_band_gbp, field="unused_basic_band_gbp")
        validate_gbp(self.taxable_income_gbp, field="taxable_income_gbp")
        validate_gbp(self.basic_band_extension_gbp, field="basic_band_extension_gbp")
        if self.unused_basic_band_gbp is not None and (
            self.taxable_income_gbp is not None or self.basic_band_extension_gbp is not None
        ):
            raise InputError("band", "Supply either a confirmed unused band or confirmed income and band extension.")

    def unused_band(self, rules: CgtRules) -> Fraction | None:
        if self.source.source_status != "actual":
            return None
        if self.unused_basic_band_gbp is not None:
            return Fraction(self.unused_basic_band_gbp)
        if self.taxable_income_gbp is None or self.basic_band_extension_gbp is None:
            return None
        return max(Fraction(0), rules.basic_rate_band_gbp + Fraction(self.basic_band_extension_gbp)
                   - Fraction(self.taxable_income_gbp))


@dataclass(frozen=True)
class CgtInputs:
    start_year: int | None
    jurisdiction: str | None
    ordinary_treatment: bool | None
    eligible_for_aea: bool | None
    share_coverage_confirmed: bool
    capital: CapitalEvidence | None
    band: BandEvidence | None

    def __post_init__(self) -> None:
        if self.start_year is not None:
            TaxYear(self.start_year)
        _confirmation(self.ordinary_treatment, "ordinary_treatment")
        _confirmation(self.eligible_for_aea, "eligible_for_aea")
        if type(self.share_coverage_confirmed) is not bool:
            raise InputError("share_coverage_confirmed", "Confirm whether the selected year covers all share disposals.")


@dataclass(frozen=True)
class CgtEstimate:
    gross_gains_gbp: Fraction
    current_losses_gbp: Fraction
    current_losses_used_gbp: Fraction
    excess_current_losses_gbp: Fraction
    brought_forward_used_gbp: Fraction
    brought_forward_remaining_gbp: Fraction
    annual_exemption_used_gbp: Fraction
    taxable_gains_gbp: Fraction
    unused_basic_band_gbp: Fraction
    basic_rate_gains_gbp: Fraction
    higher_rate_gains_gbp: Fraction
    basic_rate: Fraction
    higher_rate: Fraction
    tax_gbp: Fraction


@dataclass(frozen=True)
class AnnualCgt:
    status: ResultStatus
    source: CgtInputs
    rules: CgtRules | None
    disposals: tuple[ShareGain, ...]
    known_share_gains_gbp: Fraction
    known_share_losses_gbp: Fraction
    estimate: CgtEstimate | None
    warnings: tuple[Problem, ...]


def _estimate(
    gains: Fraction, losses: Fraction, brought_forward: Fraction, unused_band: Fraction, rules: CgtRules,
) -> CgtEstimate:
    current_used = min(gains, losses)
    after_current = gains - current_used
    prior_used = min(brought_forward, max(Fraction(0), after_current - rules.annual_exempt_amount_gbp))
    exempt = min(rules.annual_exempt_amount_gbp, after_current - prior_used)
    taxable = after_current - prior_used - exempt
    lower = min(unused_band, taxable)
    higher = taxable - lower
    return CgtEstimate(
        gains, losses, current_used, losses - current_used, prior_used, brought_forward - prior_used,
        exempt, taxable, unused_band, lower, higher, rules.basic_rate, rules.higher_rate,
        lower * rules.basic_rate + higher * rules.higher_rate,
    )


def calculate_annual_cgt(shares: ShareGains, raw: CgtInputs) -> AnnualCgt:
    """Aggregate the disposal year. Unresolved annual evidence suppresses tax only."""
    rows = tuple(row for row in shares.gains if row.disposal.tax_year_start == raw.start_year)
    known = [row.gain_gbp for row in rows if row.gain_gbp is not None]
    gains = sum((amount for amount in known if amount > 0), Fraction(0))
    losses = -sum((amount for amount in known if amount < 0), Fraction(0))

    warnings: list[Problem] = []
    rules = RULES if raw.start_year == RULES.tax_year.start_year else None
    if raw.start_year is None:
        warnings.append(Problem("incomplete", "start_year", "Select the tax year."))
    elif rules is None:
        warnings.append(Problem("unsupported", "start_year", "The annual CGT estimate supports 2026/27 only."))
    if raw.jurisdiction is None:
        warnings.append(Problem("incomplete", "jurisdiction", "Confirm the tax jurisdiction."))
    elif raw.jurisdiction not in ("england", "northern_ireland"):
        warnings.append(Problem("unsupported", "jurisdiction", "The annual estimate supports England and Northern Ireland."))
    for field, confirmed in (
        ("ordinary_treatment", raw.ordinary_treatment), ("eligible_for_aea", raw.eligible_for_aea),
    ):
        if confirmed is not True:
            warnings.append(Problem("incomplete" if confirmed is None else "unsupported", field,
                                    "Confirm ordinary supported UK treatment and full annual exemption eligibility."))
    if not raw.share_coverage_confirmed:
        warnings.append(Problem("incomplete", "share_coverage_confirmed", "Confirm all share disposals for the selected year."))
    if shares.priority.status in ("input_error", "incomplete", "unsupported") and (
        not shares.priority.disposal_remainders and not shares.priority.acquisition_remainders
    ):
        warnings.extend(shares.priority.warnings)
    for row in shares.gains:
        if row.disposal.tax_year_start in (None, raw.start_year) and row.gain_gbp is None:
            warnings.extend(row.warnings or (Problem("incomplete", row.disposal.sale.source.event_id,
                                                     "Complete the disposal gain and confirm its tax year."),))

    capital = raw.capital
    if capital is None or capital.source.source_status == "unknown" or None in (
        capital.other_gains_gbp, capital.other_current_losses_gbp, capital.available_brought_forward_gbp,
    ):
        warnings.append(Problem("incomplete", "capital", "Confirm other ordinary gains and allowable losses, including explicit zero amounts."))
    band = raw.band.unused_band(RULES) if raw.band is not None else None
    if band is None:
        warnings.append(Problem("incomplete", "band", "Supply externally confirmed unused band, or taxable income and extension."))

    estimate = None
    if not warnings:
        assert rules is not None and capital is not None and band is not None
        assert capital.other_gains_gbp is not None and capital.other_current_losses_gbp is not None
        assert capital.available_brought_forward_gbp is not None
        estimate = _estimate(gains + Fraction(capital.other_gains_gbp), losses + Fraction(capital.other_current_losses_gbp),
                             Fraction(capital.available_brought_forward_gbp), band, rules)
    return AnnualCgt(_with_problems("estimated", warnings), raw, rules, rows, gains, losses, estimate,
                     tuple(dict.fromkeys(warnings)))
