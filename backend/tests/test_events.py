import json
from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import Decimal

import pytest

from vestor_domain.events import DatedMoney, resolve_events
from vestor_domain.primitives import InputError, parse_gbp, parse_percent
from vestor_domain.tax_year import TaxRules, select_tax_rules


@pytest.mark.parametrize(("parse", "raw", "expected"), [
    (parse_gbp, "0", "0"),
    (parse_gbp, "0.10", "0.10"),
    (parse_gbp, "123456789012345678901234567890.01", "123456789012345678901234567890.01"),
    (parse_percent, "0.0001", "0.0001"),
    (parse_percent, "100.0000", "100.0000"),
])
def test_input_decimal_is_exact(parse, raw, expected):
    assert str(parse(raw)) == expected


@pytest.mark.parametrize(("parse", "raw"), [
    (parse_gbp, -0.1), (parse_gbp, Decimal("0.10")), (parse_gbp, "-0.01"),
    (parse_gbp, "0.001"), (parse_gbp, "1e2"), (parse_gbp, "NaN"),
    (parse_gbp, "Infinity"), (parse_gbp, "1_000"), (parse_gbp, "£2"),
    (parse_gbp, "1,000"), (parse_gbp, " 1 "), (parse_percent, "100.0001"),
    (parse_percent, "0.00001"), (parse_percent, "-1"),
])
def test_bad_decimal_input_is_a_field_error(parse, raw):
    with pytest.raises(InputError):
        parse(raw)


def event(event_id="forecast", **changes):
    return replace(DatedMoney(
        event_id=event_id, on=date(2027, 4, 5), amount_gbp=Decimal("125.10"),
        source_status="forecast", source_note="Expected date",
    ), **changes)


def rules():
    selected = select_tax_rules(2026, "england", standard_treatment=True)
    assert isinstance(selected, TaxRules)
    return selected


def test_dated_money_round_trips_exactly_as_json():
    original = event()
    wire = json.loads(json.dumps(original.to_wire()))
    assert wire["amount_gbp"] == "125.10"
    assert wire["on"] == "2027-04-05"
    assert DatedMoney.from_wire(wire) == original
    assert DatedMoney.from_wire(wire).to_wire() == wire
    with pytest.raises(FrozenInstanceError):
        original.amount_gbp = Decimal("1")


@pytest.mark.parametrize("changes", [
    {"event_id": " "}, {"on": "2027-04-05"}, {"amount_gbp": 1.5},
    {"amount_gbp": Decimal("-1")}, {"amount_gbp": Decimal("0.001")},
    {"source_status": "estimated"}, {"source_note": " "},
    {"replaces_forecast_id": "some_other_event"},
])
def test_invalid_direct_event_construction_is_rejected(changes):
    with pytest.raises(InputError):
        event(**changes)


@pytest.mark.parametrize(("actual_date", "reason"), [
    (date(2027, 4, 5), "included"),
    (date(2027, 4, 6), "excluded"),
])
def test_explicit_actual_replaces_forecast_before_tax_year_filtering(actual_date, reason):
    forecast = event()
    actual = event(
        "actual", on=actual_date, amount_gbp=Decimal("130.00"),
        source_status="actual", source_note="Payroll", replaces_forecast_id="forecast",
    )
    result = resolve_events([forecast, actual], rules(), coverage_confirmed=True)
    assert result.status == "confirmed"
    lines = {line.event_id: line for line in result.breakdown}
    assert lines["forecast"].disposition == "replaced"
    assert lines["forecast"].replaced_by == "actual"
    assert lines["actual"].disposition == reason
    wire = result.to_wire()
    assert wire["rule_version"] == "uk-eng-ni-2026-27-v1"
    chronological = [actual, forecast] if reason == "included" else [forecast, actual]
    assert wire["source_events"] == [item.to_wire() for item in chronological]
    assert wire == resolve_events([actual, forecast], rules(), coverage_confirmed=True).to_wire()


def test_matching_dates_and_amounts_do_not_link_independent_events():
    forecast = event()
    actual = event("actual", source_status="actual", source_note="Payroll")
    result = resolve_events([forecast, actual], rules(), coverage_confirmed=True)
    assert result.status == "estimated"
    assert [line.disposition for line in result.breakdown] == ["included", "included"]


@pytest.mark.parametrize("mode", ["duplicate_id", "missing_target", "wrong_target", "duplicate_link"])
def test_ambiguous_or_invalid_identity_is_an_input_error(mode):
    forecast = event()
    actual = event("actual", source_status="actual", replaces_forecast_id="forecast")
    records = {
        "duplicate_id": [forecast, forecast],
        "missing_target": [actual],
        "wrong_target": [event(source_status="actual"), actual],
        "duplicate_link": [forecast, actual, replace(actual, event_id="second_actual")],
    }
    result = resolve_events(records[mode], rules(), coverage_confirmed=True)
    assert result.status == "input_error"
    assert result.breakdown == ()
    assert result.warnings


def test_unknown_current_input_is_incomplete_and_zero_is_known():
    unknown = event("unknown", source_status="actual", amount_gbp=None)
    zero = event("zero", source_status="actual", amount_gbp=Decimal("0"))
    incomplete = resolve_events([unknown, zero], rules(), coverage_confirmed=True)
    assert incomplete.status == "incomplete"
    assert incomplete.to_wire()["value"] is None
    assert incomplete.warnings
    assert resolve_events([zero], rules(), coverage_confirmed=True).status == "confirmed"
    assert resolve_events([zero], rules(), coverage_confirmed=False).status == "incomplete"


def test_unknown_source_is_incomplete_even_with_amount():
    result = resolve_events([event(source_status="unknown")], rules(), coverage_confirmed=True)
    assert result.status == "incomplete"


def test_valid_internal_integral_decimal_with_positive_exponent_round_trips():
    original = event(amount_gbp=Decimal("1E+2"))
    assert original.to_wire()["amount_gbp"] == "100"
    assert DatedMoney.from_wire(original.to_wire()) == original
