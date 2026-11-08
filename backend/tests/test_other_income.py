"""Synthetic M1.8 evidence fixtures; no savings/dividend tax calculation."""
from datetime import date
from decimal import Decimal

import pytest

from test_pensions import adjustment, pension
from test_employment import calculate, period
from vestor_domain import other_income as domain
from vestor_domain.events import DatedMoney
from vestor_domain.primitives import InputError
from vestor_domain.tax_year import TaxRules, select_tax_rules

RULES = select_tax_rules(2026, "england", standard_treatment=True)
assert isinstance(RULES, TaxRules)


def income(key="interest", amount="1000", on="2026-11-01", source="actual", replaces=None, **kwargs):
    return domain.OtherIncome(
        DatedMoney(key, date.fromisoformat(on), None if amount is None else Decimal(amount),
                   source, "Synthetic other-income evidence", replaces),
        **(dict(category="interest", basis="dated", coverage_ids=(key,),
                treatment="taxable", treatment_confirmed=True, allocation_confirmed=True) | kwargs),
    )


def resolve(*entries, confirmed=True):
    return domain.calculate_other_income(RULES, entries=entries, coverage_confirmed=confirmed)


def test_taxable_allowances_do_not_remove_income_but_isa_exemption_does():
    result = resolve(income(), income("dividend", "500", category="dividends"),
                     income("isa", "200", treatment="exempt", exemption_reason="ISA interest"))
    assert result.status == "confirmed"
    assert result.taxable_gbp == 1500
    assert result.lines[2].amount_gbp == 0
    assert result.lines[2].disposition == "excluded"
    assert "ISA interest" in result.lines[2].explanation
    assert result.lines[0].source.money.source_note
    assert result.rule_version == RULES.version
    assert result.tax_year == RULES.tax_year.dates


@pytest.mark.parametrize(("on", "expected"), [("2026-04-05", 0), ("2026-04-06", 1000),
                                               ("2027-04-05", 1000), ("2027-04-06", 0)])
def test_dated_receipt_boundaries(on, expected):
    assert resolve(income(on=on)).taxable_gbp == expected


@pytest.mark.parametrize("category", ["uk_trading", "uk_property"])
def test_manual_taxable_profit_allocates_by_assessment_year_not_record_date(category):
    current = income(category=category, basis="tax_year", assessment_year=2026, on="2027-10-01")
    prior = income("prior", category=category, basis="tax_year", assessment_year=2025)
    result = resolve(current, prior)
    assert result.status == "confirmed"
    assert result.taxable_gbp == 1000
    assert result.lines[1].source.money.on == date(2027, 10, 1)


def test_tax_year_interest_total_is_not_annualised_or_prorated():
    result = resolve(income(basis="tax_year", assessment_year=2026, source="forecast"))
    assert result.taxable_gbp == 1000
    assert result.status == "estimated"


@pytest.mark.parametrize("changes", [dict(amount=None), dict(source="unknown"),
    dict(treatment="unknown"), dict(treatment_confirmed=None), dict(allocation_confirmed=False)])
def test_unknown_values_treatment_or_allocation_suppress_total(changes):
    result = resolve(income(**changes))
    assert result.status == "incomplete"
    assert result.taxable_gbp is None
    assert result.warnings


def test_uncertain_allocation_outside_year_cannot_hide_income():
    result = resolve(income(on="2025-01-01", allocation_confirmed=False))
    assert result.status == "incomplete"
    assert result.lines[0].disposition == "unresolved"


@pytest.mark.parametrize("changes", [dict(category="other"), dict(treatment_confirmed=False)])
def test_unsupported_treatment_is_not_guessed(changes):
    result = resolve(income(**changes), income("unknown", amount=None))
    assert result.status == "unsupported"
    assert result.taxable_gbp is None


def test_explicit_absence_and_coverage():
    assert resolve().taxable_gbp == 0
    assert resolve(confirmed=False).status == "incomplete"


def test_actual_replaces_forecast_before_year_filtering():
    forecast = income("forecast", source="forecast", on="2027-04-05")
    actual = income("actual", on="2027-04-06", replaces="forecast", coverage_ids=("forecast",))
    result = resolve(forecast, actual)
    assert result.status == "confirmed"
    assert result.taxable_gbp == 0
    assert result.lines[0].disposition == "replaced"
    assert result.lines[0].replaced_by == "actual"


@pytest.mark.parametrize("changes", [dict(category="dividends"), dict(coverage_ids=("unrelated",))])
def test_actual_replacement_must_reconcile_category_and_coverage(changes):
    result = resolve(income(source="forecast"), income("actual", replaces="interest", **changes))
    assert result.status == "input_error"
    assert result.taxable_gbp is None


@pytest.mark.parametrize("category", ["interest", "dividends"])
def test_consolidated_annual_and_dated_income_cannot_overlap_even_across_categories(category):
    result = resolve(income(basis="tax_year", assessment_year=2026, coverage_ids=("bank-a", "bank-b")),
                     income("detail", category=category, coverage_ids=("bank-b",)))
    assert result.status == "input_error"
    assert result.taxable_gbp is None


def test_separate_dates_in_same_stream_and_unlinked_equal_records_remain_separate():
    assert resolve(income(coverage_ids=("bank",)),
                   income("second", on="2026-12-01", coverage_ids=("bank",))).taxable_gbp == 2000
    assert resolve(income(), income("other-bank")).taxable_gbp == 2000


@pytest.mark.parametrize("changes", [dict(amount="-1"), dict(amount="0.001"),
    dict(treatment="exempt", exemption_reason=None), dict(coverage_ids=()),
    dict(coverage_ids=("bank", "bank")), dict(basis="dated", assessment_year=2026),
    dict(category="uk_trading"), dict(basis="tax_year"), dict(assessment_year=True, basis="tax_year")])
def test_invalid_inputs_raise_field_errors(changes):
    with pytest.raises(InputError):
        income(**changes)


def test_repeated_event_id_is_rejected():
    assert resolve(income(), income()).status == "input_error"


def test_exact_pennies_and_gift_aid_remain_separate_without_second_deduction():
    other = resolve(income(amount="1000.01"), income("dividend", "500.02", category="dividends"))
    contributions = pension(calculate(salary=[period("salary", "80000")]),
                            adjustments=[adjustment("donation", "gift_aid", "800", qualifies=True)])
    assert other.taxable_gbp == Decimal("1500.03")
    assert contributions.ani_deduction_gbp == 1000
    assert other.taxable_gbp == Decimal("1500.03")  # Income does not also subtract the donation.


def test_dated_actual_cannot_replace_a_whole_year_total():
    result = resolve(income("annual", basis="tax_year", assessment_year=2026, source="forecast"),
                     income("receipt", replaces="annual", coverage_ids=("annual",)))
    assert result.status == "input_error"
    assert result.taxable_gbp is None


def test_actual_assessment_year_correction_replaces_before_allocation():
    result = resolve(income("forecast", category="uk_property", basis="tax_year",
                           assessment_year=2026, source="forecast"),
                     income("actual", category="uk_property", basis="tax_year",
                           assessment_year=2027, replaces="forecast", coverage_ids=("forecast",)))
    assert result.status == "confirmed"
    assert result.taxable_gbp == 0
    assert result.lines[0].disposition == "replaced"
