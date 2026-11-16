from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from test_ani import inputs
from test_api import wire
from vestor_api import app


def source(key):
    return {"event_id": key, "source_status": "actual", "source_note": "Synthetic source"}


SECURITY = {"issuer_id": "issuer", "share_class": "A", "owner_id": "owner",
            "capacity": "personal", "ordinary_listed": True}


def model():
    return {
        "ani": wire(inputs()),
        "grants": [{"source": source("grant"), "security": SECURITY, "awarded_on": "2025-05-01",
                    "treatment": "ordinary_rsu"}],
        "vests": [{
            "vest": {"source": source("vest"), "security": SECURITY, "grant_id": "grant",
                     "vested_on": "2026-05-10", "acquired_on": "2026-05-10", "charge_on": "2026-05-10",
                     "quantity": "100", "fmv_usd_per_share": "10", "uk_resident": True},
            "included_in_payroll": False, "confirmed_payroll_gbp": "800",
            "basis_method": "market_value", "confirmed_basis_gbp": "800",
        }],
        "opening_holdings": [{"source": source("opening"), "security": SECURITY, "as_of": "2026-04-05",
                              "quantity": "0", "cost_gbp": "0", "history_confirmed": True,
                              "coverage_through": "2026-07-20"}],
        "sales": [{"source": source("sale"), "security": SECURITY, "trade_on": "2026-06-20",
                   "settlement_on": "2026-06-22", "quantity": "100", "gross_amount": "1200", "currency": "USD",
                   "purpose": "voluntary", "price_per_share": "12", "rate_id": "sale-rate",
                   "uk_resident": True, "fees_confirmed": True}],
        "fees": [{"source": source("fee"), "transaction_id": "sale", "on": "2026-06-20",
                  "amount": "10", "currency": "GBP", "category": "eligible_dealing"}],
        "rates": [{"source": source("sale-rate"), "on": "2026-06-20", "purpose": "disposal_proceeds",
                   "gbp_per_usd": "0.750000000000000000000000000001", "pair": "GBP/USD"}],
        "annual": {"ordinary_treatment": True, "eligible_for_aea": True, "share_coverage_confirmed": True,
                   "capital": {"source": source("other"), "other_gains_gbp": "0",
                               "other_current_losses_gbp": "0", "available_brought_forward_gbp": "0"},
                   "band": {"source": source("band"), "unused_basic_band_gbp": "0"}},
        "payroll_coverage": True,
        "cash_coverage": True,
    }


def test_m2_f4_returns_one_ani_and_exact_share_basis_trace():
    payload = model()
    with TestClient(app) as client:
        response = client.post("/api/v2/calculate", json=payload)
        assert response.status_code == 200, response.text
        assert response.json() == client.post("/api/v2/calculate", json=payload).json()
    result = response.json()
    assert result["version"] == "2"
    assert result["ani"]["ani_gbp"]["display_gbp"] == "80800.00"
    gain = result["share_gains"]["gains"][0]
    assert gain["gain_gbp"]["display_gbp"] == "90.00"
    assert gain["gain_gbp"]["denominator"] != "1"
    assert gain["pool_movement"]["basis_gbp"]["display_gbp"] == "800.00"
    assert gain["pool_movement"]["quantity"] == {"numerator": "100", "denominator": "1"}
    assert result["annual_cgt"]["estimate"]["tax_gbp"]["display_gbp"] == "0.00"
    assert result["settlement"]["cash_status"] == "confirmed"


@pytest.mark.parametrize(("collection", "field", "value"), [
    ("sales", "quantity", True),
    ("sales", "quantity", "-1"),
    ("sales", "quantity", "NaN"),
    ("sales", "quantity", {}),
    ("sales", "quantity", []),
    ("sales", "price_per_share", 1.293),
    ("sales", "trade_on", "2026-06-31"),
    ("sales", "rate_id", "PRIVATE invalid ref"),
    ("rates", "gbp_per_usd", "1e-1"),
    ("rates", "gbp_per_usd", "1" * 1000),
    ("fees", "PRIVATE-unknown-key", "PRIVATE rejected value"),
])
def test_m2_rejects_malformed_input_without_echo(collection, field, value):
    payload = deepcopy(model())
    payload[collection][0][field] = value
    with TestClient(app) as client:
        response = client.post("/api/v2/calculate", json=payload)
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"].startswith(f"inputs.{collection}.0")
    assert "PRIVATE" not in response.text


def test_incomplete_band_does_not_hide_known_gains_or_ani():
    payload = model()
    payload["annual"]["band"] = None
    with TestClient(app) as client:
        response = client.post("/api/v2/calculate", json=payload)
    assert response.status_code == 200
    result = response.json()
    assert result["annual_cgt"]["status"] == "incomplete"
    assert result["annual_cgt"]["estimate"] is None
    assert result["share_gains"]["gains"][0]["gain_gbp"]["display_gbp"] == "90.00"
    assert result["ani"]["ani_gbp"]["display_gbp"] == "80800.00"


def test_duplicate_identity_rejected_without_echoing_source():
    payload = model()
    payload["sales"][0]["source"]["event_id"] = "sensitive-id"
    payload["fees"][0]["source"]["event_id"] = "sensitive-id"
    with TestClient(app) as client:
        response = client.post("/api/v2/calculate", json=payload)
    assert response.status_code == 422
    assert "sensitive-id" not in response.text


def test_5_6_april_match_serializes_sources_and_keeps_disposal_year():
    payload = model()
    opening = payload["opening_holdings"][0]
    opening.update(quantity="100", cost_gbp="500", coverage_through="2027-05-06")
    vest = payload["vests"][0]["vest"]
    vest.update(vested_on="2027-04-06", acquired_on="2027-04-06", charge_on="2027-04-06")
    payload["sales"][0].update(trade_on="2027-04-05", settlement_on="2027-04-06")
    payload["fees"][0]["on"] = "2027-04-05"
    payload["rates"][0].update(on="2027-04-05", gbp_per_usd="0.75")
    with TestClient(app) as client:
        response = client.post("/api/v2/calculate", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["ani"]["ani_gbp"]["display_gbp"] == "80000.00"
    segment = result["share_gains"]["priority"]["segments"][0]
    assert segment["rule"] == "following_30_days"
    assert segment["disposal_tax_year_start"] == 2026
    assert (segment["disposal_id"], segment["acquisition_id"]) == ("sale", "vest")
    assert segment["basis_gbp"]["display_gbp"] == "800.00"
    assert result["annual_cgt"]["known_share_gains_gbp"]["display_gbp"] == "90.00"


def test_unknown_transfer_fee_does_not_block_share_match():
    payload = model()
    payload["fees"].append({"source": source("wire-fee"), "transaction_id": "sale",
                            "on": None, "amount": None, "currency": "GBP", "category": "cash_transfer"})
    with TestClient(app) as client:
        response = client.post("/api/v2/calculate", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["share_gains"]["gains"][0]["gain_gbp"]["display_gbp"] == "90.00"


def test_dated_usd_purchase_and_expense_become_exact_acquisition_basis():
    payload = model()
    payload["vests"] = []
    payload["grants"] = []
    payload["purchases"] = [{
        "source": source("purchase"), "security": SECURITY, "acquired_on": "2026-05-10",
        "quantity": "100", "gross_amount": "1000", "currency": "USD",
        "rate_id": "purchase-rate", "uk_resident": True, "fees_confirmed": True,
    }]
    payload["fees"].append({"source": source("acq-fee"), "transaction_id": "purchase",
                            "on": "2026-05-10", "amount": "10", "currency": "USD",
                            "rate_id": "fee-rate", "category": "eligible_dealing"})
    for key, purpose in (("purchase-rate", "acquisition_basis"), ("fee-rate", "acquisition_fee")):
        payload["rates"].append({"source": source(key), "on": "2026-05-10", "purpose": purpose,
                                 "gbp_per_usd": "0.80", "pair": "GBP/USD"})
    with TestClient(app) as client:
        response = client.post("/api/v2/calculate", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["acquisitions"][0]["basis"]["gbp"]["display_gbp"] == "808.00"
    assert result["share_gains"]["gains"][0]["gain_gbp"]["display_gbp"] == "82.00"


def test_wire_preserves_payroll_difference_and_fx_rounding_disclosure():
    payload = model()
    payload["vests"][0]["confirmed_payroll_gbp"] = "820"
    payload["vests"][0]["vest"]["income_rate_id"] = "income-rate"
    payload["rates"].append({"source": source("income-rate"), "on": "2026-05-10",
                             "purpose": "vest_income", "gbp_per_usd": "0.80", "pair": "GBP/USD"})
    with TestClient(app) as client:
        response = client.post("/api/v2/calculate", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["vests"][0]["payroll_difference_gbp"]["display_gbp"] == "20.00"
    assert result["vests"][0]["acquisition_quantity"] == "100"
    fx = result["ledger"]["disposals"][0]["proceeds_fx"]
    assert fx["rounding_discrepancy_gbp"]["numerator"].startswith("-")


@pytest.mark.parametrize(("acquired_on", "status"), [("2026-05-10", "unknown"), (None, "actual")])
def test_gbp_purchase_requires_known_source_and_acquisition_date(acquired_on, status):
    payload = model()
    payload["vests"] = []
    payload["grants"] = []
    payload["purchases"] = [{
        "source": {**source("purchase"), "source_status": status}, "security": SECURITY,
        "acquired_on": acquired_on, "quantity": "100", "gross_amount": "800", "currency": "GBP",
        "uk_resident": True, "fees_confirmed": True,
    }]
    with TestClient(app) as client:
        response = client.post("/api/v2/calculate", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["acquisitions"][0]["basis"] is None
    assert result["acquisitions"][0]["warnings"]
    assert result["share_gains"]["gains"][0]["gain_gbp"] is None
