from dataclasses import replace
from datetime import date
from decimal import Decimal
from fractions import Fraction

import pytest

from test_ani import inputs
from test_employment import pay, payroll
from test_rsu import vest as manual_vest
from vestor_domain.employment import PayrollComponent
from vestor_domain.fx import FxRate, FxRates
from vestor_domain.primitives import InputError
from vestor_domain.share_evidence import Grant, OpeningHolding, Sale, Security, ShareSource, Vest, validate_share_evidence
from vestor_domain.vest_valuation import (
    VestValuationInput, calculate_ani_with_vests, value_vest,
)


ON = date(2026, 4, 6)
SECURITY = Security("issuer", "A", "owner", "personal", True)


def source(key, status="actual"):
    return ShareSource(key, status, "synthetic vest evidence")


def evidence(on=ON, **kwargs):
    grant = Grant(source("grant"), SECURITY, date(2025, 1, 1), "ordinary_rsu")
    vest = Vest(source("m2-vest"), SECURITY, "grant", on, on, on, Decimal("100"),
                Decimal("10"), "income", "basis", True)
    return VestValuationInput(vest, grant, included_in_payroll=False, **kwargs)


def rates(on=ON, income="0.80", basis="0.80", status="actual"):
    return FxRates((
        FxRate(source("income", status), on, "vest_income", Decimal(income), "GBP/USD"),
        FxRate(source("basis", status), on, "acquisition_basis", Decimal(basis), "GBP/USD"),
    ))


def test_f4_gross_income_and_separate_acquisition_basis():
    raw = evidence(gross_usd=Decimal("1000"), basis_method="market_value")
    value = value_vest(raw, rates())
    assert value.employment_gbp == 800 and value.employment_status == "estimated"
    assert value.basis_gbp == 800 and value.acquisition_quantity == 100
    assert calculate_ani_with_vests(inputs(), (value,)).ani_gbp == 80800


def test_f9_missing_income_fx_leaves_independent_basis_visible():
    raw = evidence(basis_method="market_value", confirmed_basis_gbp=Decimal("810"))
    value = value_vest(raw, FxRates(()))
    assert value.employment_gbp is None and value.employment_status == "incomplete"
    assert value.basis_gbp == 810
    result = calculate_ani_with_vests(inputs(), (value,))
    assert result.status == "incomplete" and result.ani_gbp is None


def test_confirmed_payroll_wins_and_is_counted_once_via_named_component():
    raw = replace(evidence(
        confirmed_payroll_gbp=Decimal("820"), confirmed_basis_gbp=Decimal("810"),
        basis_method="market_value",
    ), included_in_payroll=True, payroll_ids=("pay",))
    value = value_vest(raw, rates())
    assert value.employment_gbp == 820 and value.employment_status == "confirmed"
    assert value.estimated_income.amount_gbp == 800
    assert value.payroll_difference_gbp == 20
    assert value.basis_gbp == 810
    salary = payroll(pay("pay", "10000"), "2026-04-06", "2027-04-05",
                     components=(PayrollComponent("m2-vest", "rsu", Decimal("820")),))
    result = calculate_ani_with_vests(replace(inputs(), salary_periods=(), salary_payments=(salary,)), (value,))
    assert result.ani_gbp == 10000


def test_forecast_conversion_uses_exact_subpenny_income():
    raw = evidence(basis_method="market_value")
    raw = replace(raw, vest=replace(raw.vest, quantity=Decimal("1"), fmv_usd_per_share=Decimal("0.01")))
    value = value_vest(raw, rates(income="0.50"))
    assert value.employment_gbp == Fraction(1, 200)
    result = calculate_ani_with_vests(inputs(), (value,))
    assert result.ani_gbp == 80000 + Fraction(1, 200)


def test_actual_manual_forecast_replacement_resolves_before_year_filter():
    on = date(2027, 4, 6)
    raw = evidence(on, confirmed_payroll_gbp=Decimal("800"), replaces_manual_forecast_id="manual")
    result = calculate_ani_with_vests(
        inputs(rsu_events=(manual_vest("manual", "780", "2027-04-05", "forecast"),)),
        (value_vest(raw, rates(on)),),
    )
    assert result.ani_gbp == 80000
    assert any(line.disposition == "replaced" for line in result.rsu.lines)


def test_same_day_cover_leaves_gross_vested_income_unchanged():
    raw = evidence(confirmed_payroll_gbp=Decimal("800"), basis_method="market_value")
    cover = Sale(source("cover"), SECURITY, ON, Decimal("45"), Decimal("450"), "USD",
                 "sell_to_cover", "m2-vest", uk_resident=True)
    opening = OpeningHolding(source("opening"), SECURITY, date(2026, 4, 5), Decimal(0), Decimal(0),
                             True, date(2026, 5, 6))
    assert validate_share_evidence((opening, raw.grant, raw.vest, cover)).status == "confirmed"
    value = value_vest(raw, rates())
    assert value.acquisition_quantity - cover.quantity == 55
    assert calculate_ani_with_vests(inputs(), (value,)).rsu.taxable_gbp == 800


def test_linked_manual_actual_is_canonical_and_conflicting_payroll_is_rejected():
    base = inputs(rsu_events=(manual_vest("manual", "820", ON.isoformat()),))
    raw = evidence(confirmed_payroll_gbp=Decimal("820"), manual_vest_id="manual")
    assert calculate_ani_with_vests(base, (value_vest(raw, rates()),)).ani_gbp == 80820
    conflict = replace(raw, confirmed_payroll_gbp=Decimal("819"))
    with pytest.raises(InputError, match="Reconcile charge date"):
        calculate_ani_with_vests(base, (value_vest(conflict, rates()),))


def test_inconsistent_stated_usd_blocks_modelled_values():
    raw = evidence(gross_usd=Decimal("999.99"), basis_method="market_value")
    value = value_vest(raw, rates())
    assert value.employment_gbp is value.basis_gbp is None
    assert value.employment_status == value.basis_status == "input_error"
    result = calculate_ani_with_vests(inputs(), (value,))
    assert result.ani_gbp is None and result.status == "input_error"
    assert any(warning.field == "gross_usd" for warning in result.warnings)


def test_chapter_5_actual_basis_requires_qualifying_amount_independent_from_payroll():
    raw = evidence(confirmed_payroll_gbp=Decimal("820"), basis_method="nil_price_chapter_5")
    value = value_vest(raw, rates())
    assert value.employment_gbp == 820
    assert value.basis_gbp is None and value.basis_status == "incomplete"
    value = value_vest(replace(raw, confirmed_basis_gbp=Decimal("810")), rates())
    assert value.basis_gbp == 810 and value.basis_status == "confirmed"


def test_missing_charge_date_blocks_ani_even_when_reference_date_is_outside_year():
    raw = evidence(date(2027, 4, 6), confirmed_payroll_gbp=Decimal("800"))
    raw = replace(raw, vest=replace(raw.vest, charge_on=None))
    result = calculate_ani_with_vests(inputs(), (value_vest(raw, FxRates(())),))
    assert result.ani_gbp is None and result.status == "incomplete"


def test_inconsistent_usd_blocks_ani_even_when_confirmed_payroll_is_supplied():
    raw = evidence(gross_usd=Decimal("999.99"), confirmed_payroll_gbp=Decimal("820"),
                   basis_method="market_value", confirmed_basis_gbp=Decimal("810"))
    value = value_vest(raw, rates())
    assert value.source.confirmed_payroll_gbp == 820
    assert value.basis_gbp == 810
    result = calculate_ani_with_vests(inputs(), (value,))
    assert result.ani_gbp is None and result.status == "input_error"
    assert any(warning.field == "gross_usd" for warning in result.warnings)


def test_explicit_canonical_manual_forecast_keeps_its_entered_pennies():
    raw = evidence(manual_vest_id="manual")
    raw = replace(raw, vest=replace(raw.vest, source=source("m2-vest", "forecast"),
                                  quantity=Decimal("1"), fmv_usd_per_share=Decimal("0.01")))
    value = value_vest(raw, rates(income="0.50"))
    manual = manual_vest("manual", "0.01", ON.isoformat(), "forecast")
    assert value.employment_gbp == Fraction(1, 200)
    assert calculate_ani_with_vests(inputs(rsu_events=(manual,)), (value,)).ani_gbp == 80000 + Fraction(1, 100)


def test_missing_acquisition_date_leaves_known_payroll_charge_intact():
    raw = evidence(confirmed_payroll_gbp=Decimal("820"), basis_method="market_value",
                   confirmed_basis_gbp=Decimal("810"))
    value = value_vest(replace(raw, vest=replace(raw.vest, acquired_on=None)), rates())
    assert value.employment_gbp == 820 and value.employment_status == "confirmed"
    assert value.basis_gbp is None and value.basis_status == "incomplete"
    assert calculate_ani_with_vests(inputs(), (value,)).ani_gbp == 80820
