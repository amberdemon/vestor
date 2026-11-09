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
finally:
    server.terminate()
    server.wait(timeout=5)
