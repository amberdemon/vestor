from dataclasses import replace
from datetime import date
from decimal import Decimal
from fractions import Fraction

import pytest

from test_priority_matching import OPEN, buy, sell, source
from test_share_gains import calculate
from vestor_domain.annual_cgt import BandEvidence, CapitalEvidence, CgtInputs, calculate_annual_cgt


def d(value):
    return Decimal(value)


def evidence(**changes):
    base = CgtInputs(
        2026, "england", True, True, True,
        CapitalEvidence(source("capital"), d("2000"), d("2000"), d("2000")),
        BandEvidence(source("band"), taxable_income_gbp=d("36700"), basic_band_extension_gbp=d("0")),
    )
    return replace(base, **changes)


def shares(gross=10500, *, on=date(2026, 9, 1)):
    return calculate((OPEN, replace(sell("sale", on, 100), price_per_share=d(gross) / 100)), {})


def test_contract_case_12_loss_order_and_split_band():
    result = calculate_annual_cgt(shares(), evidence())
    assert result.status == "estimated"
    assert result.known_share_gains_gbp == 10000
    estimate = result.estimate
    assert estimate.current_losses_used_gbp == 2000
    assert estimate.brought_forward_used_gbp == 2000
    assert estimate.annual_exemption_used_gbp == 3000
    assert estimate.taxable_gains_gbp == 5000
    assert (estimate.basic_rate_gains_gbp, estimate.higher_rate_gains_gbp) == (1000, 4000)
    assert estimate.tax_gbp == 1140


def test_case_13_brought_forward_losses_are_preserved_below_allowance():
    capital = CapitalEvidence(source("capital"), d(0), d(200), d(2000))
    result = calculate_annual_cgt(shares(4500), evidence(capital=capital))
    estimate = result.estimate
    assert estimate.brought_forward_used_gbp == 800
    assert estimate.brought_forward_remaining_gbp == 1200
    assert estimate.tax_gbp == 0


def test_band_extension_does_not_treat_ani_as_taxable_income():
    capital = CapitalEvidence(source("capital"), d(0), d(0), d(0))
    band = BandEvidence(source("band"), taxable_income_gbp=d(38200), basic_band_extension_gbp=d(2000))
    estimate = calculate_annual_cgt(shares(8500), evidence(capital=capital, band=band)).estimate
    assert estimate.unused_basic_band_gbp == 1500
    assert estimate.tax_gbp == 1110


@pytest.mark.parametrize("change", [
    {"share_coverage_confirmed": False},
    {"eligible_for_aea": None},
    {"ordinary_treatment": None},
    {"capital": None},
    {"band": None},
    {"capital": CapitalEvidence(source("capital"), d(0), d(0), None)},
])
def test_incomplete_annual_evidence_preserves_known_disposal_values(change):
    result = calculate_annual_cgt(shares(), evidence(**change))
    assert result.status == "incomplete" and result.estimate is None
    assert result.known_share_gains_gbp == 10000


def test_ordinary_rates_are_exact_rationals():
    estimate = calculate_annual_cgt(shares(), evidence()).estimate
    assert estimate.basic_rate == Fraction(18, 100)
    assert estimate.higher_rate == Fraction(24, 100)


def test_zero_disposals_requires_explicit_evidence_and_returns_zero():
    no_shares = calculate((), {})
    cap = CapitalEvidence(source("capital"), d(0), d(0), d(0))
    band = BandEvidence(source("band"), unused_basic_band_gbp=d(0))
    result = calculate_annual_cgt(no_shares, evidence(capital=cap, band=band))
    assert result.disposals == () and result.estimate.tax_gbp == 0
    assert calculate_annual_cgt(no_shares, evidence(capital=None, band=band)).estimate is None


def test_current_year_loss_used_before_exemption_and_unused_loss_is_retained():
    cap = CapitalEvidence(source("capital"), d(100), d(30), d(400))
    result = calculate_annual_cgt(shares(300), evidence(capital=cap))
    assert result.known_share_losses_gbp == 200
    estimate = result.estimate
    assert estimate.current_losses_used_gbp == 100
    assert estimate.excess_current_losses_gbp == 130
    assert estimate.brought_forward_remaining_gbp == 400
    assert estimate.annual_exemption_used_gbp == estimate.tax_gbp == 0


def test_5_april_sale_uses_6_april_acquisition_and_retains_its_year():
    fifth, sixth = date(2027, 4, 5), date(2027, 4, 6)
    lot = buy("buy", sixth, 20, 200)
    sales = (replace(sell("prior", fifth, 10), price_per_share=d(600)),
             replace(sell("later", sixth, 10), price_per_share=d(700)))
    result = calculate_annual_cgt(calculate((OPEN, lot, *sales), {"buy": 200}), evidence())
    assert tuple(row.disposal.sale.source.event_id for row in result.disposals) == ("prior",)
    assert result.known_share_gains_gbp == 5900


@pytest.mark.parametrize("change", [
    {"start_year": 2027}, {"jurisdiction": "scotland"}, {"eligible_for_aea": False},
    {"ordinary_treatment": False},
])
def test_unsupported_scope_blocks_annual_tax(change):
    result = calculate_annual_cgt(shares(), evidence(**change))
    assert result.status == "unsupported" and result.estimate is None


def test_forecast_band_is_not_externally_confirmed():
    band = BandEvidence(source("band", "forecast"), unused_basic_band_gbp=d(2000))
    result = calculate_annual_cgt(shares(), evidence(band=band))
    assert result.status == "incomplete" and result.estimate is None


def test_empty_disposal_list_from_rejected_ledger_is_not_annual_absence():
    sale = sell("duplicate", date(2026, 9, 1), 1)
    result = calculate_annual_cgt(calculate((OPEN, sale, sale), {}), evidence())
    assert result.status == "input_error" and result.estimate is None
