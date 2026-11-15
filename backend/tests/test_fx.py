from dataclasses import replace
from datetime import date
from decimal import Decimal, localcontext
from fractions import Fraction

import pytest

from vestor_domain.events import DatedMoney
from vestor_domain.fx import FxRate, FxRates
from vestor_domain.primitives import InputError
from vestor_domain.share_evidence import ShareSource


ACQUIRED = date(2026, 4, 5)
SOLD = date(2026, 4, 6)


def rate(key="rate", on=ACQUIRED, purpose="acquisition_basis", value="0.70", status="actual",
         replaces=None):
    return FxRate(ShareSource(key, status, "synthetic dated quote", replaces), on, purpose,
                  None if value is None else Decimal(value), "GBP/USD")


def test_fx_only_gain_preserves_original_dated_rates_and_f6():
    acquire = rate()
    dispose = rate("sale", SOLD, "disposal_proceeds", "0.80")
    rates = FxRates((acquire, dispose))
    cost = rates.convert(Decimal("10"), quantity=Decimal("10"), on=ACQUIRED,
                         purpose="acquisition_basis", rate_id="rate")
    proceeds = rates.convert(Decimal("100"), on=SOLD, purpose="disposal_proceeds", rate_id="sale")
    assert cost.status == proceeds.status == "confirmed"
    assert cost.amount_usd == proceeds.amount_usd == 100
    assert cost.rate == acquire and proceeds.rate == dispose
    assert proceeds.amount_gbp - cost.amount_gbp == 10


def test_fractional_price_shares_rate_are_exact_under_low_decimal_precision():
    quote = rate(value="0.8123456789")
    with localcontext() as ctx:
        ctx.prec = 4
        result = FxRates((quote,)).convert(Decimal("12.3456789"), quantity=Decimal("0.00123456"),
            on=ACQUIRED, purpose=quote.purpose, rate_id="rate")
    assert result.amount_gbp == Fraction(123456789, 10**7) * Fraction(123456, 10**8) * Fraction(8123456789, 10**10)
    assert result.display_gbp == "0.01"


def test_rounding_is_final_only_and_exposes_discrepancy():
    result = FxRates((rate(value="0.5"),)).convert(Decimal("0.01"), on=ACQUIRED,
             purpose="acquisition_basis", rate_id="rate")
    assert result.amount_gbp == Fraction(1, 200)
    assert result.display_gbp == "0.01"
    assert result.rounding_discrepancy_gbp == Fraction(1, 200)


@pytest.mark.parametrize(("changes", "field"), [
    ({"gbp_per_usd": Decimal("0")}, "gbp_per_usd"),
    ({"gbp_per_usd": Decimal("-0.7")}, "gbp_per_usd"),
    ({"gbp_per_usd": Decimal("NaN")}, "gbp_per_usd"),
    ({"gbp_per_usd": Decimal("Infinity")}, "gbp_per_usd"),
    ({"gbp_per_usd": 0.7}, "gbp_per_usd"),
    ({"pair": "USD/GBP"}, "pair"),
    ({"purpose": "other"}, "purpose"),
])
def test_invalid_quote_evidence(changes, field):
    with pytest.raises(InputError) as error:
        replace(rate(), **changes)
    assert error.value.field == field


@pytest.mark.parametrize(("quote", "on", "purpose", "key", "expected"), [
    (rate(), ACQUIRED, "acquisition_basis", None, "incomplete"),
    (rate(), ACQUIRED, "acquisition_basis", "absent", "incomplete"),
    (rate(on=None), ACQUIRED, "acquisition_basis", "rate", "incomplete"),
    (rate(), None, "acquisition_basis", "rate", "incomplete"),
    (rate(value=None), ACQUIRED, "acquisition_basis", "rate", "incomplete"),
    (rate(status="unknown"), ACQUIRED, "acquisition_basis", "rate", "incomplete"),
    (rate(), SOLD, "acquisition_basis", "rate", "input_error"),
    (rate(purpose="cash_settlement"), ACQUIRED, "disposal_fee", "rate", "input_error"),
    (rate(purpose="acquisition_fee"), ACQUIRED, "disposal_fee", "rate", "input_error"),
])
def test_missing_or_incompatible_rate_suppresses_amount(quote, on, purpose, key, expected):
    result = FxRates((quote,)).convert(Decimal("100"), on=on, purpose=purpose, rate_id=key)
    assert result.status == expected
    assert result.amount_gbp is result.display_gbp is None
    assert result.warnings


def test_actual_rate_replaces_explicit_same_date_forecast_without_losing_original():
    forecast = rate(status="forecast")
    actual = rate("actual", value="0.75", replaces="rate")
    catalog = FxRates((forecast, actual))
    result = catalog.convert(Decimal("100"), on=ACQUIRED, purpose=actual.purpose, rate_id="rate")
    assert catalog.rates == (forecast, actual)
    assert result.requested_rate_id == "rate"
    assert result.rate == actual and result.status == "confirmed"
    assert result.amount_gbp == 75


@pytest.mark.parametrize("rates", [
    (rate(), rate()),
    (rate("actual", replaces="not-present"),),
    (rate(), rate("actual", replaces="rate")),
    (rate(status="forecast"), rate("actual", on=SOLD, replaces="rate")),
    (rate(status="forecast"), rate("actual", purpose="disposal_proceeds", replaces="rate")),
    (rate(status="forecast"), rate("actual", replaces="rate"), rate("second", replaces="rate")),
])
def test_catalog_rejects_duplicate_or_incompatible_replacements(rates):
    with pytest.raises(InputError):
        FxRates(rates)


@pytest.mark.parametrize(("quote_status", "event_status", "expected"), [
    ("forecast", "actual", "estimated"),
    ("actual", "forecast", "estimated"),
    ("actual", "unknown", "incomplete"),
])
def test_forecast_and_unknown_propagate(quote_status, event_status, expected):
    result = FxRates((rate(status=quote_status),)).convert(Decimal("0"), on=ACQUIRED,
             purpose="acquisition_basis", rate_id="rate", source_status=event_status)
    assert result.status == expected
    assert result.amount_gbp == (0 if expected == "estimated" else None)


def test_missing_amount_is_unknown_and_existing_money_input_precision_is_unchanged():
    result = FxRates((rate(),)).convert(None, on=ACQUIRED, purpose="acquisition_basis", rate_id="rate")
    assert result.status == "incomplete" and result.amount_gbp is None
    with pytest.raises(InputError):
        DatedMoney("vest", ACQUIRED, Decimal("0.005"), "actual", "synthetic")
