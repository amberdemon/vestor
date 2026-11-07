"""Synthetic manual GBP vest fixtures; no share/FX/withholding calculations."""
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from test_employment import calculate, pay, payroll, period
from vestor_domain import rsu as domain
from vestor_domain.employment import PayrollComponent
from vestor_domain.events import DatedMoney
from vestor_domain.primitives import InputError
from vestor_domain.tax_year import TaxRules, select_tax_rules

RULES = select_tax_rules(2026, "england", standard_treatment=True)
assert isinstance(RULES, TaxRules)


def vest(key="vest", amount="2000", on="2026-11-01", source="actual", replaces=None, **changes):
    return domain.RsuEvent(
        DatedMoney(key, date.fromisoformat(on), None if amount is None else Decimal(amount),
                   source, "Synthetic gross GBP vest evidence", replaces),
        **(dict(charge_date_confirmed=True, supported_award=True, included_in_payroll=False) | changes),
    )


def resolve(*events, employment=None, confirmed=True):
    return domain.calculate_rsu_income(
        RULES, events=events, coverage_confirmed=confirmed,
        employment=employment if employment is not None else calculate(salary=[period("salary", "80000")]),
    )


@pytest.mark.parametrize("percent", ["0", "45", "100"])
def test_gross_vests_are_independent_of_sold_to_cover_percentage(percent):
    result = resolve(vest("one", sold_to_cover_percent=Decimal(percent)), vest("two", on="2027-02-01"))
    assert result.status == "confirmed"
    assert result.taxable_gbp == 4000
    assert result.rule_version == RULES.version
    assert result.lines[0].source.money.source_note
    assert result.lines[0].explanation


def test_f10_boundaries_and_penny_precision():
    result = resolve(
        vest("before", on="2026-04-05"), vest("first", "2000.01", on="2026-04-06"),
        vest("last", "2000.02", on="2027-04-05"), vest("after", on="2027-04-06"),
    )
    assert result.taxable_gbp == Decimal("4000.03")
    assert [line.disposition for line in result.lines] == ["excluded", "included", "included", "excluded"]


@pytest.mark.parametrize("actual_date, expected", [("2026-11-01", 2100), ("2027-04-06", 0)])
def test_actual_replaces_explicit_forecast_before_year_filter(actual_date, expected):
    result = resolve(vest("forecast", source="forecast"), vest("actual", "2100", actual_date, replaces="forecast"))
    assert result.status == "confirmed"
    assert result.taxable_gbp == expected
    replaced, = [line for line in result.lines if line.disposition == "replaced"]
    assert replaced.replaced_by == "actual"


@pytest.mark.parametrize("changes,status", [
    ({"amount": None}, "incomplete"),  # F9a
    ({"source": "unknown"}, "incomplete"),
    ({"included_in_payroll": None}, "incomplete"),
    ({"charge_date_confirmed": False}, "incomplete"),
    ({"supported_award": None}, "incomplete"),
    ({"supported_award": False}, "unsupported"),
])
def test_missing_or_unsupported_evidence_suppresses_subtotal(changes, status):
    result = resolve(vest(**changes))
    assert result.status == status
    assert result.taxable_gbp is None
    assert result.warnings


def test_unknown_charge_date_cannot_be_excluded_using_reference_date():
    assert resolve(vest(on="2027-04-06", charge_date_confirmed=False)).status == "incomplete"


def test_absence_coverage_and_known_zero():
    assert resolve().taxable_gbp == 0
    assert resolve(confirmed=False).taxable_gbp is None
    assert resolve(vest(amount="0")).taxable_gbp == 0
    assert resolve(vest(source="forecast")).status == "estimated"


@pytest.mark.parametrize("events", [
    (vest(), vest()),
    (vest(replaces="missing"),),
    (vest("forecast", source="forecast"), vest("one", replaces="forecast"), vest("two", replaces="forecast")),
])
def test_duplicate_ids_and_invalid_replacements(events):
    result = resolve(*events)
    assert result.status == "input_error"
    assert result.taxable_gbp is None


def test_unlinked_matching_values_remain_separate():
    assert resolve(vest("one"), vest("two")).taxable_gbp == 4000


@pytest.mark.parametrize("components,changes,status", [
    ((PayrollComponent("vest", "rsu", Decimal("2000")),), {}, "confirmed"),
    ((PayrollComponent("vest", "rsu", Decimal("1900")),), {}, "incomplete"),
    ((PayrollComponent("other", "rsu", Decimal("2000")),), {}, "incomplete"),
    ((), {}, "incomplete"),
    (None, {}, "incomplete"),
    ((PayrollComponent("vest", "rsu", Decimal("2000")),), {"included_in_payroll": False, "payroll_ids": ()}, "incomplete"),
    ((PayrollComponent("vest", "rsu", Decimal("2000")),), {"source": "forecast"}, "incomplete"),
])
def test_payroll_reconciliation_both_directions(components, changes, status):
    employment = calculate(payroll=[payroll(pay("pay", "82000"), "2026-04-06", "2027-04-05", components=components)])
    record = vest(**(dict(included_in_payroll=True, payroll_ids=("pay",)) | changes))
    result = resolve(record, employment=employment)
    assert result.status == status
    if status == "confirmed":
        assert employment.gross_salary_gbp == 80000
        assert result.included_in_payroll_gbp == 2000
        assert employment.gross_salary_gbp + result.taxable_gbp == 82000
    else:
        assert result.taxable_gbp is None


def test_payroll_component_without_vest_evidence_blocks_subtotal():
    employment = calculate(payroll=[payroll(
        pay("pay", "82000"), "2026-04-06", "2027-04-05",
        components=(PayrollComponent("missing", "rsu", Decimal("2000")),),
    )])
    assert resolve(employment=employment).status == "incomplete"


def test_outside_year_payroll_conflicts_with_in_year_vest():
    employment = calculate(payroll=[payroll(
        pay("pay", "82000", on="2027-04-06"), "2026-04-06", "2027-04-05",
        components=(PayrollComponent("vest", "rsu", Decimal("2000")),),
    )])
    assert resolve(vest(included_in_payroll=True, payroll_ids=("pay",)), employment=employment).status == "incomplete"


def test_replaced_payroll_and_vest_components_do_not_count():
    employment = calculate(payroll=[
        payroll(pay("old-pay", "82000", source="forecast"), "2026-04-06", "2027-04-05",
                components=(PayrollComponent("forecast", "rsu", Decimal("2000")),)),
        payroll(pay("actual-pay", "82100", replaces="old-pay"), "2026-04-06", "2027-04-05",
                components=(PayrollComponent("actual", "rsu", Decimal("2100")),)),
    ])
    result = resolve(vest("forecast", source="forecast"), vest("actual", "2100", replaces="forecast",
        included_in_payroll=True, payroll_ids=("actual-pay",)), employment=employment)
    assert result.status == "confirmed"
    assert result.taxable_gbp == 2100
    assert employment.gross_salary_gbp == 80000


@pytest.mark.parametrize("amount", ["-1", "1.001", "NaN"])
def test_negative_or_invalid_gbp_is_rejected(amount):
    with pytest.raises(InputError):
        vest(amount=amount)


@pytest.mark.parametrize("changes", [
    {"included_in_payroll": "false"}, {"charge_date_confirmed": "true"},
    {"supported_award": "true"}, {"payroll_ids": ("pay", "pay")},
    {"sold_to_cover_percent": Decimal("100.0001")}, {"sold_to_cover_percent": 45.0},
    {"label": " "},
])
def test_invalid_event_evidence_is_rejected(changes):
    with pytest.raises(InputError):
        vest(**changes)


def test_mismatched_employment_rules_rejected():
    employment = replace(calculate(salary=[period("salary", "80000")]), rule_version="other")
    assert resolve(vest(), employment=employment).status == "input_error"


def test_unsupported_award_takes_precedence_over_missing_date_and_value():
    assert resolve(vest(amount=None, charge_date_confirmed=False, supported_award=False)).status == "unsupported"


def test_payroll_cannot_include_a_vest_with_a_later_taxable_date():
    employment = calculate(payroll=[payroll(
        pay("pay", "82000", on="2026-10-01"), "2026-04-06", "2027-04-05",
        components=(PayrollComponent("vest", "rsu", Decimal("2000")),),
    )])
    assert resolve(vest(included_in_payroll=True, payroll_ids=("pay",)), employment=employment).status == "incomplete"


def test_split_payroll_components_match_named_amounts_exactly():
    employment = calculate(payroll=[
        payroll(pay("one", "41000", on="2026-12-01"), "2026-04-06", "2026-11-01",
                components=(PayrollComponent("vest", "rsu", Decimal("1000")),)),
        payroll(pay("two", "41000"), "2026-11-02", "2027-04-05",
                components=(PayrollComponent("vest", "rsu", Decimal("1000")),)),
    ])
    result = resolve(vest(included_in_payroll=True, payroll_ids=("one", "two")), employment=employment)
    assert result.status == "confirmed"
    assert result.taxable_gbp == result.included_in_payroll_gbp == 2000
    assert employment.gross_salary_gbp == 80000


def test_actual_corrected_into_year_replaces_outside_forecast():
    result = resolve(vest("forecast", on="2027-04-06", source="forecast"),
                     vest("actual", "2100", on="2027-04-05", replaces="forecast"))
    assert result.status == "confirmed"
    assert result.taxable_gbp == 2100


def test_missing_actual_value_does_not_fall_back_to_estimate():
    result = resolve(vest("forecast", source="forecast"), vest("actual", amount=None, replaces="forecast"))
    assert result.status == "incomplete"
    assert result.taxable_gbp is None
    assert any(line.replaced_by == "actual" for line in result.lines)


def test_unneeded_payroll_link_is_not_silently_ignored():
    assert resolve(vest(payroll_ids=("missing",))).status == "incomplete"


def test_component_exceeding_payroll_total_suppresses_rsu_income():
    employment = calculate(payroll=[payroll(
        pay("pay", "1000"), "2026-04-06", "2027-04-05",
        components=(PayrollComponent("vest", "rsu", Decimal("2000")),),
    )])
    assert resolve(vest(included_in_payroll=True, payroll_ids=("pay",)), employment=employment).taxable_gbp is None
