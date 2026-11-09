from fastapi.testclient import TestClient

from vestor_api import app


def test_health():
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# Route parity and independent fixture values: all arithmetic stays in the domain.
from copy import deepcopy
from dataclasses import replace

import pytest
from test_ani import inputs
from test_employment import pay
from test_pensions import sacrifice
from vestor_domain.ani import calculate_ani


def wire(raw):
    return calculate_ani(raw).to_wire()["inputs"]


@pytest.mark.parametrize("raw,expected", [
    (inputs(payroll_reductions=(sacrifice("sac", "salary", percent="2"),)), "78400.00"),
    (inputs("95000", bonuses=(pay("bonus", "10000"),)), "105000.00"),
    (inputs("95000", bonuses=(pay("bonus", "10000"),), payroll_reductions=(sacrifice("sac", "bonus", amount="5500"),)), "99500.00"),
])
def test_calculation_route_matches_domain_and_worked_fixture(raw, expected):
    with TestClient(app) as client:
        response = client.post("/api/calculate", json=wire(raw))
    assert response.status_code == 200
    assert response.json() == calculate_ani(raw).to_wire()
    assert response.json()["ani_gbp"]["display_gbp"] == expected


@pytest.mark.parametrize("path,value", [
    (("salary_periods", 0, "annual_gbp"), 80000.5),
    (("salary_periods", 0, "annual_gbp"), "8e4"),
    (("salary_periods", 0, "annual_gbp"), "80000.001"),
    (("salary_periods", 0, "dates", "start"), "2026-04-06T00:00:00Z"),
    (("salary_periods", 0, "dates", "end"), "2026-02-30"),
    (("standard_treatment",), "true"),
    (("bonus_coverage_confirmed",), 1),
    (("start_year",), True),
    (("target_gbp",), "PRIVATE-REJECTED-VALUE"),
    (("salary_periods", 0, "source_status"), "bogus"),
])
def test_strict_route_rejects_ambiguous_types_without_echo(path, value):
    payload = deepcopy(wire(inputs()))
    parent = payload
    for segment in path[:-1]:
        parent = parent[segment]
    parent[path[-1]] = value
    with TestClient(app) as client:
        response = client.post("/api/calculate", json=payload)
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"].startswith("inputs.")
    assert "PRIVATE-REJECTED-VALUE" not in response.text
    assert "input" not in response.json()["errors"][0]


def test_invalid_json_and_extra_fields_do_not_echo_inputs():
    with TestClient(app) as client:
        for body in ['{"private-secret":', '{"private-secret": "PRIVATE-REJECTED-VALUE"}', '[]']:
            response = client.post("/api/calculate", content=body, headers={"Content-Type": "application/json"})
            assert response.status_code == 422
            assert "PRIVATE-REJECTED-VALUE" not in response.text
            assert "private-secret" not in response.text


@pytest.mark.parametrize("raw,status", [
    (replace(inputs(), jurisdiction="scotland"), "unsupported"),
    (replace(inputs(), standard_treatment=None), "incomplete"),
    (replace(inputs(), rsu_coverage_confirmed=False), "incomplete"),
])
def test_unknown_unsupported_are_explicit_without_totals(raw, status):
    with TestClient(app) as client:
        result = client.post("/api/calculate", json=wire(raw)).json()
    assert result["status"] == status
    assert result["ani_gbp"] is result["personal_allowance_gbp"] is result["headroom_gbp"] is None
    assert result["warnings"]


def test_all_nested_domain_records_cross_the_api_without_reinterpretation():
    from test_benefits import benefit
    from test_employment import payroll
    from test_other_income import income
    from test_pensions import adjustment, net_pay
    from test_rsu import vest
    from vestor_domain.employment import PayrollComponent
    from decimal import Decimal
    raw = replace(inputs(), salary_periods=(), salary_payments=(payroll(
        pay("pay", "90000", basis="after_reductions", reflected_methods=("net_pay", "salary_sacrifice")),
        "2026-04-06", "2027-04-05", components=(
            PayrollComponent("vest", "rsu", Decimal("8000")),
            PayrollComponent("medical", "benefit", Decimal("2000"))),
    ),), payroll_reductions=(net_pay("net", "pay", "1000", treatment="reflected"),),
        benefits=(benefit("medical", basis="payrolled", taxable_gbp=Decimal("2000"),
            source_status="actual", included_in_payroll=True, payroll_ids=("pay",)),),
        rsu_events=(vest("vest", "8000", included_in_payroll=True, payroll_ids=("pay",)),),
        other_income=(income(),), adjustments=(
            adjustment("gift", "gift_aid", "800", qualifies=True),
            adjustment("ras", "relief_at_source", "800", qualifies=True),))
    with TestClient(app) as client:
        response = client.post("/api/calculate", json=wire(raw))
    assert response.status_code == 200
    assert response.json() == calculate_ani(raw).to_wire()
    assert response.json()["ani_gbp"]["display_gbp"] == "89000.00"


def test_domain_configuration_error_maps_to_control_path():
    payload = wire(inputs())
    payload['start_year'] = 10000
    with TestClient(app) as client:
        response = client.post('/api/calculate', json=payload)
    assert response.status_code == 422
    assert response.json()['errors'][0]['field'] == 'inputs.start_year'


def test_semantic_source_error_maps_to_control_without_echoing_identity():
    raw = inputs(payroll_reductions=(sacrifice('PRIVATE-SOURCE-IDENTITY', 'salary', amount='90000'),))
    with TestClient(app) as client:
        response = client.post('/api/calculate', json=wire(raw))
    assert response.status_code == 422
    assert response.json()['errors'][0]['field'] == 'inputs.payroll_reductions.0.reduction_id'
    assert 'PRIVATE-SOURCE-IDENTITY' not in response.text


def test_semantic_collection_error_maps_to_section():
    payload = wire(inputs())
    payload['salary_periods'].append({**payload['salary_periods'][0], 'period_id': 'second'})
    with TestClient(app) as client:
        response = client.post('/api/calculate', json=payload)
    assert response.status_code == 422
    assert any(error['field'] == 'inputs.salary_periods' for error in response.json()['errors'])
