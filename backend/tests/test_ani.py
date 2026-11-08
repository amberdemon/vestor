from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction

import pytest

from test_benefits import benefit
from test_employment import pay, payroll, period
from test_other_income import income
from test_rsu import vest
from vestor_domain.employment import PayrollComponent
from test_pensions import adjustment, sacrifice, net_pay
from vestor_domain.ani import AniInputs, calculate_ani, display_gbp


def inputs(salary="80000", **kwargs):
    return AniInputs(2026, "england", True, salary_periods=(period("salary", salary),),
                     bonus_coverage_confirmed=True, pension_coverage_confirmed=True,
                     benefit_coverage_confirmed=True, rsu_coverage_confirmed=True,
                     other_income_coverage_confirmed=True, **kwargs)


@pytest.mark.parametrize("salary,bonus,reductions,adjustments,expected,allowance", [
    ("80000", (), (sacrifice("sac", "salary", percent="2"),), (), 78400, 12570),
    ("95000", (pay("bonus", "10000"),), (), (), 105000, 10070),
    ("95000", (pay("bonus", "10000"),), (sacrifice("sac", "bonus", amount="5500"),), (), 99500, 12570),
    ("100000", (pay("bonus", "1000"),), (sacrifice("sac", "bonus", amount="1000"),), (), 100000, 12570),
    ("100000", (pay("bonus", "1000"),), (), (adjustment("ras", "relief_at_source", "800", qualifies=True),), 100000, 12570),
    ("99999", (), (), (), 99999, 12570),
    ("100000", (), (), (), 100000, 12570),
    ("100001.99", (), (), (), Fraction(10000199, 100), 12570),
    ("100002", (), (), (), 100002, 12569),
    ("125140", (), (), (), 125140, 0),
    ("125141", (), (), (), 125141, 0),
])
def test_integrated_fixtures(salary, bonus, reductions, adjustments, expected, allowance):
    result = calculate_ani(inputs(salary, bonuses=bonus, payroll_reductions=reductions, adjustments=adjustments))
    assert result.ani_gbp == expected
    assert result.personal_allowance_gbp == allowance
    assert result.headroom_gbp == 100000 - expected


def test_net_income_and_ani_steps_are_separate():
    result = calculate_ani(inputs("101000", adjustments=(
        adjustment("gross", "gross_pension", "500", qualifies=True),
        adjustment("gift", "gift_aid", "800", qualifies=True),
        adjustment("employer", "employer", "9000"),
    )))
    assert result.net_income_gbp == 100500
    assert result.ani_gbp == 99500
    assert result.row("gross_pension").amount_gbp == -500
    assert result.row("gift_aid").amount_gbp == -1000


def test_reflected_net_pay_is_not_deducted_twice():
    raw = replace(inputs(), salary_periods=(), salary_payments=(
        payroll(pay("pay", "100000", basis="after_reductions"), "2026-04-06", "2027-04-05"),
    ), payroll_reductions=(net_pay("net", "pay", "1000", treatment="reflected"),))
    assert calculate_ani(raw).ani_gbp == 100000


def test_bonus_year_boundaries():
    result = calculate_ani(inputs(bonuses=tuple(pay(str(i), amount, on) for i, (amount, on) in enumerate([
        ("2000", "2026-03-31"), ("3000", "2026-04-06"), ("500", "2027-04-05"), ("4000", "2027-04-06"),
    ]))))
    assert result.ani_gbp == 83500


@pytest.mark.parametrize("change,status", [
    ({"rsu_coverage_confirmed": False}, "incomplete"),
    ({"jurisdiction": "scotland"}, "unsupported"),
    ({"start_year": 2025}, "unsupported"),
    ({"standard_treatment": None}, "incomplete"),
])
def test_suppression(change, status):
    result = calculate_ani(replace(inputs(), **change))
    assert result.status == status
    assert result.ani_gbp is result.personal_allowance_gbp is result.headroom_gbp is None


def test_target_is_independent_and_optional():
    raw = inputs("105000", target_gbp=Decimal("110000"))
    assert calculate_ani(raw).headroom_gbp == 5000
    assert calculate_ani(raw).personal_allowance_gbp == 10070
    assert calculate_ani(replace(raw, target_gbp=None)).headroom_gbp is None


def test_rounding_is_exact_signed_and_independent_of_decimal_context():
    with localcontext() as context:
        context.prec = 2
        assert display_gbp(Fraction(1, 200)) == "0.01"
        assert display_gbp(Fraction(-1, 200)) == "-0.01"
        assert display_gbp(Fraction(10000199, 100)) == "100001.99"


def test_order_invariance_and_evidence_wire_format():
    raw = inputs(bonuses=(pay("b", "500"), pay("a", "1000")))
    first = calculate_ani(raw).to_wire()
    assert first == calculate_ani(replace(raw, bonuses=tuple(reversed(raw.bonuses)))).to_wire()
    assert first["rules"]["version"] == "uk-eng-ni-2026-27-v1"
    assert first["ani_gbp"]["display_gbp"] == "81500.00"


def test_f3_renewal_and_other_income_example():
    result = calculate_ani(inputs(benefits=(
        benefit("old", end="2026-10-31"),
        benefit("new", start="2026-11-01", taxable_gbp=Decimal("3000")),
    )))
    assert result.ani_gbp == 80000 + Fraction(969600, 365)
    assert display_gbp(result.ani_gbp) == "82656.44"
    result = calculate_ani(inputs(other_income=(income(), income("dividend", "500", category="dividends"),
        income("isa", "200", treatment="exempt", exemption_reason="ISA interest"))))
    assert result.ani_gbp == 81500


def test_all_components_reconcile_raw_payroll_and_actual_replacements():
    raw = replace(inputs(), salary_periods=(), salary_payments=(payroll(
        pay("pay", "100000", basis="after_reductions"), "2026-04-06", "2027-04-05",
        components=(PayrollComponent("bonus", "bonus", Decimal("10000")),
                    PayrollComponent("vest", "rsu", Decimal("8000")),
                    PayrollComponent("medical", "benefit", Decimal("2000"))),
    ),), bonuses=(pay("bonus", "10000", basis="after_reductions"),),
        rsu_events=(vest("forecast", "7000", source="forecast"),
                    vest("vest", "8000", replaces="forecast", included_in_payroll=True, payroll_ids=("pay",))),
        benefits=(benefit("medical-forecast"),
                  benefit("medical", basis="payrolled", taxable_gbp=Decimal("2000"),
                          source_status="actual", included_in_payroll=True, payroll_ids=("pay",),
                          replaces_forecast_ids=("medical-forecast",))),
        other_income=(income(),), adjustments=(
            adjustment("gift", "gift_aid", "800", qualifies=True),
            adjustment("ras", "relief_at_source", "800", qualifies=True),
            adjustment("gross", "gross_pension", "500", qualifies=True),
        ), payroll_reductions=(net_pay("net", "pay", "1000", treatment="reflected"),))
    result = calculate_ani(raw)
    assert result.status == "confirmed"
    assert result.row("taxable_salary").amount_gbp == 80000
    assert result.taxable_income_gbp == 101000
    assert result.net_income_gbp == 100500
    assert result.ani_gbp == 98500
    assert len([line for line in result.rsu.lines if line.disposition == "included"]) == 1
    assert result.rsu.lines[0].replaced_by == "vest"
    assert any(line.replaced_by == "medical" for line in result.benefits.lines)


@pytest.mark.parametrize("raw,status", [
    (inputs(rsu_events=(vest(amount=None),)), "incomplete"),
    (inputs(benefits=(benefit(taxability="unknown", taxable_gbp=None),)), "incomplete"),
    (inputs(rsu_events=(vest(supported_award=False),), other_income=(income(amount=None),)), "unsupported"),
])
def test_material_evidence_blocks_final_values(raw, status):
    result = calculate_ani(raw)
    assert result.status == status
    assert result.ani_gbp is result.personal_allowance_gbp is result.headroom_gbp is None
    assert result.row("taxable_salary").amount_gbp == 80000


def test_taper_uses_unrounded_fraction_and_rounding_discrepancy_is_disclosed():
    # Two separately displayed deduction rows each round 1.25p to 1p,
    # while their combined 2.5p rounds to 3p.
    raw = inputs("100002", adjustments=(
        adjustment("a", "gift_aid", "0.01", qualifies=True),
        adjustment("b", "relief_at_source", "0.01", qualifies=True)))
    result = calculate_ani(raw)
    assert result.ani_gbp == Fraction(100002) - Fraction(1, 40)
    assert result.personal_allowance_gbp == 12570
    assert result.rounding_discrepancy_gbp == 0  # ANI rounds to .98, as do rows.
    raw = inputs("100002", adjustments=(adjustment("a", "gift_aid", "0.01", qualifies=True),),
                 benefits=(benefit("tiny", start="2027-04-05", taxable_gbp=Decimal("2.19")),))
    result = calculate_ani(raw)
    assert result.rounding_discrepancy_gbp == Fraction(-1, 100)
    assert result.to_wire()["rounding_discrepancy_gbp"]["display_gbp"] == "-0.01"
    assert not any(w.field == "display_rounding" for w in result.warnings)
    # This daily forecast gives ANI 100001.995890..., whose display is 100002.
    # Rounding ANI before the statutory taper would incorrectly lose £1.
    raw = replace(inputs(), salary_periods=(period("prior", "0", end="2027-04-04"),
                                           period("last", "36500728.50", start="2027-04-05")))
    result = calculate_ani(raw)
    assert display_gbp(result.ani_gbp) == "100002.00"
    assert result.personal_allowance_gbp == 12570


@pytest.mark.parametrize("amount", ["0", "0.01", "500", "999.99"])
def test_valid_sacrifice_reduces_ani_by_exact_amount_once(amount):
    baseline = inputs(bonuses=(pay("bonus", "1000"),))
    reduced = replace(baseline, payroll_reductions=(sacrifice("sac", "bonus", amount=amount),))
    assert calculate_ani(baseline).ani_gbp - calculate_ani(reduced).ani_gbp == Decimal(amount)


def test_global_source_identity_cannot_be_counted_in_two_categories():
    from vestor_domain.primitives import InputError
    with pytest.raises(InputError, match="unique across"):
        calculate_ani(inputs(bonuses=(pay("same", "1000"),), rsu_events=(vest("same"),)))


def test_forecast_adjustment_does_not_relabel_actual_payroll():
    raw = replace(inputs(), salary_periods=(), salary_payments=(
        payroll(pay("pay", "80000"), "2026-04-06", "2027-04-05"),),
        adjustments=(adjustment("gift", "gift_aid", "800", source="forecast", qualifies=True),))
    result = calculate_ani(raw)
    assert result.status == "estimated"
    assert result.row("taxable_salary").status == "confirmed"
    assert result.row("gift_aid").status == "estimated"
    assert result.row("relief_at_source").status == "confirmed"


def test_nested_identifier_order_does_not_change_wire_evidence():
    raw = inputs(other_income=(income(coverage_ids=("second", "first")),),
                 bonuses=(pay("bonus", "100", basis="after_reductions", reflected_methods=("net_pay", "salary_sacrifice")),))
    reversed_raw = replace(raw,
        other_income=(replace(raw.other_income[0], coverage_ids=("first", "second")),),
        bonuses=(replace(raw.bonuses[0], reflected_methods=("salary_sacrifice", "net_pay")),))
    assert calculate_ani(raw).to_wire() == calculate_ani(reversed_raw).to_wire()
