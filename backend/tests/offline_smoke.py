"""Synthetic offline release proof, run inside the runtime with --network none."""
import json
import re
import subprocess
import time
import urllib.request

server = subprocess.Popen(
    ["python", "-m", "uvicorn", "vestor_api:app", "--host", "127.0.0.1", "--port", "8000", "--no-access-log"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
base = "http://127.0.0.1:8000"
try:
    for attempt in range(100):
        try:
            with urllib.request.urlopen(base + "/api/health", timeout=1) as response:
                assert json.load(response) == {"status": "ok"}
            break
        except OSError:
            time.sleep(0.1)
    else:
        raise AssertionError("Runtime did not start")
    with urllib.request.urlopen(base, timeout=2) as response:
        html = response.read().decode()
    assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)
    assert assets
    for asset in assets:
        with urllib.request.urlopen(base + asset, timeout=2) as response:
            assert response.status == 200 and response.read()
    payload = {
        "start_year": 2026, "jurisdiction": "england", "standard_treatment": True,
        "salary_periods": [{
            "period_id": "salary", "dates": {"start": "2026-04-06", "end": "2027-04-05"},
            "annual_gbp": "80000", "source_status": "forecast", "source_note": "Synthetic offline fixture",
        }],
        "payroll_reductions": [{
            "reduction_id": "sacrifice", "pay_id": "salary", "method": "salary_sacrifice",
            "treatment": "apply", "source_status": "forecast", "source_note": "Synthetic qualifying election",
            "qualifies": True, "percent": "2", "base": "full_pay",
            "elected_on": "2026-04-01", "effective_on": "2026-04-06",
        }],
        "bonus_coverage_confirmed": True, "pension_coverage_confirmed": True,
        "benefit_coverage_confirmed": True, "rsu_coverage_confirmed": True,
        "other_income_coverage_confirmed": True, "target_gbp": "100000",
    }
    request = urllib.request.Request(
        base + "/api/calculate", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        result = json.load(response)
    assert result["status"] == "estimated"
    assert result["ani_gbp"]["display_gbp"] == "78400.00"
    assert result["personal_allowance_gbp"]["display_gbp"] == "12570.00"
    assert result["headroom_gbp"]["display_gbp"] == "21600.00"
    print("PASS disconnected runtime health, HTML, all bundled JS/CSS assets, and synthetic F1 API calculation.")

    security = {
        "issuer_id": "fictional-issuer", "share_class": "ordinary-A",
        "owner_id": "fictional-owner", "capacity": "personal", "ordinary_listed": True,
    }

    def source(key):
        return {"event_id": key, "source_status": "actual", "source_note": "Synthetic offline F4 fixture"}

    ledger = {
        "ani": payload,
        "grants": [{"source": source("grant"), "security": security,
                    "awarded_on": "2025-05-01", "treatment": "ordinary_rsu"}],
        "vests": [{
            "vest": {"source": source("vest"), "security": security, "grant_id": "grant",
                     "vested_on": "2026-05-10", "acquired_on": "2026-05-10", "charge_on": "2026-05-10",
                     "quantity": "100", "fmv_usd_per_share": "10", "uk_resident": True},
            "included_in_payroll": False, "basis_method": "market_value",
            "confirmed_payroll_gbp": "800", "confirmed_basis_gbp": "800",
        }],
        "opening_holdings": [{"source": source("opening"), "security": security, "as_of": "2026-04-05",
                              "quantity": "0", "cost_gbp": "0", "history_confirmed": True,
                              "coverage_through": "2026-07-20"}],
        "sales": [{"source": source("sale"), "security": security, "trade_on": "2026-06-20",
                   "quantity": "100", "gross_amount": "1200", "currency": "USD",
                   "purpose": "voluntary", "price_per_share": "12", "rate_id": "sale-rate",
                   "uk_resident": True, "fees_confirmed": True}],
        "fees": [{"source": source("fee"), "transaction_id": "sale", "on": "2026-06-20",
                  "amount": "10", "currency": "GBP", "category": "eligible_dealing"}],
        "rates": [{"source": source("sale-rate"), "on": "2026-06-20", "purpose": "disposal_proceeds",
                   "gbp_per_usd": "0.75", "pair": "GBP/USD"}],
    }
    request = urllib.request.Request(
        base + "/api/v2/calculate", data=json.dumps(ledger).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        result = json.load(response)
    assert result["ani"]["ani_gbp"]["display_gbp"] == "79200.00"
    disposal, = result["share_gains"]["gains"]
    assert disposal["gain_gbp"] == {"numerator": "90", "denominator": "1", "display_gbp": "90.00"}
    assert disposal["matched_basis_gbp"]["display_gbp"] == "800.00"
    assert result["annual_cgt"]["estimate"] is None
    print("PASS disconnected M2 F4 calculation, ANI integration, exact gain and incomplete annual CGT.")
finally:
    server.terminate()
    server.wait(timeout=5)
