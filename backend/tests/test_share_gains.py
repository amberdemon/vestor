from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction

import pytest

from test_priority_matching import OPEN, SHARE, buy, sell, source
from vestor_domain.disposal_ledger import calculate_disposal_ledger
from vestor_domain.fx import FxRate, FxRates
from vestor_domain.priority_matching import AcquisitionBasis
from vestor_domain.share_evidence import Fee, Grant, Vest
from vestor_domain.share_gains import calculate_share_gains


def calculate(records, costs, rates=()):
    return calculate_share_gains(
        calculate_disposal_ledger(records, FxRates(rates)),
        {key: AcquisitionBasis(Fraction(cost), "confirmed") for key, cost in costs.items()},
    )


@pytest.mark.parametrize(("quantity", "buy_cost", "sale_rate", "commission", "expected"), [
    (100, 800, "0.75", 10, 90), (10, 70, "0.80", 0, 10),
])
def test_f4_and_f6(quantity, buy_cost, sale_rate, commission, expected):
    acquired = date(2026, 5, 10)
    sold = date(2026, 6, 20)
    price = Decimal("12") if quantity == 100 else Decimal("10")
    opening = replace(OPEN, quantity=Decimal(0), cost_gbp=Decimal(0))
    lot = buy("lot", acquired, quantity, buy_cost)
    sale = replace(sell("sale", sold, quantity), price_per_share=price,
                   currency="USD", rate_id="proceeds")
    rate = FxRate(source("proceeds"), sold, "disposal_proceeds", Decimal(sale_rate), "GBP/USD")
    fee = Fee(source("fee"), "sale", sold, Decimal(commission), "GBP", category="eligible_dealing")
    result = calculate((opening, lot, sale, fee), {"lot": buy_cost}, (rate,))
    gain, = result.gains
    assert result.status == "confirmed"
    assert gain.matched_basis_gbp == buy_cost and gain.gain_gbp == expected
    assert result.pool_movements[-1].after.quantity == 0
    assert result.pool_movements[-1].after.cost_gbp == 0


def test_f5_priority_reservations_never_enter_pool_twice():
    nov, dec = date(2026, 11, 20), date(2026, 12, 15)
    grant = Grant(source("grant"), SHARE, date(2025, 5, 1), "ordinary_rsu")
    vest = Vest(source("vest"), SHARE, "grant", dec, dec, dec, Decimal(40), Decimal(8), uk_resident=True)
    sale = sell("november", nov, 100)
    cover = replace(sell("cover", dec, 20, vest="vest"), price_per_share=Decimal(9))
    result = calculate((OPEN, sale, grant, vest, cover), {"vest": 320})
    first, second = result.gains
    assert (first.matched_basis_gbp, second.matched_basis_gbp) == (560, 160)
    assert (first.gain_gbp, second.gain_gbp) == (440, 20)
    assert result.pool_movements[-1].after.quantity == 20
    assert result.pool_movements[-1].after.cost_gbp == 100


def test_fractional_pool_debit_conserves_basis_and_keeps_a_signed_loss():
    on = date(2026, 9, 1)
    opening = replace(OPEN, quantity=Decimal(3), cost_gbp=Decimal(10))
    first = replace(sell("first", on, 1), price_per_share=Decimal(5))
    second = replace(sell("second", on + timedelta(days=1), 1), price_per_share=Decimal(1))
    result = calculate((opening, first, second), {})
    assert [row.gain_gbp for row in result.gains] == [Fraction(5, 3), Fraction(-7, 3)]
    assert result.pool_movements[-1].after.cost_gbp == Fraction(10, 3)
    assert sum(row.matched_basis_gbp for row in result.gains) + result.pool_movements[-1].after.cost_gbp == 10


def test_cross_year_match_preserves_prior_trade_year_and_next_day_cover():
    sold = date(2027, 4, 5)
    acquired = date(2027, 4, 6)
    opening = replace(OPEN, quantity=Decimal(15), cost_gbp=Decimal(45))
    grant = Grant(source("grant"), SHARE, date(2025, 5, 1), "ordinary_rsu")
    vest = Vest(source("vest"), SHARE, "grant", acquired, acquired, acquired,
                Decimal(6), Decimal(7), uk_resident=True)
    cover = replace(sell("cover", acquired, 2, vest="vest"), price_per_share=Decimal(8))
    sale = replace(sell("prior", sold, 10), settlement_on=acquired)
    result = calculate((opening, sale, grant, vest, cover), {"vest": 42})
    assert [(row.disposal.tax_year_start, row.gain_gbp) for row in result.gains] == [(2026, 54), (2027, 2)]
    assert result.pool_movements[-1].after.quantity == 9
    assert result.pool_movements[-1].after.cost_gbp == 27


def test_unknown_later_acquisition_cost_keeps_quantity_but_blocks_dependent_gain():
    on = date(2026, 9, 1)
    opening = replace(OPEN, quantity=Decimal(3), cost_gbp=Decimal(10))
    sale = sell("first", on, 1)
    later = buy("later", on + timedelta(days=4), 1, 10)
    result = calculate((opening, sale, later), {})
    gain, = result.gains
    assert result.status == "incomplete"
    assert gain.priority_segments[0].quantity == 1
    assert gain.matched_basis_gbp is gain.gain_gbp is None
    assert result.pool_movements[-1].after.cost_gbp == 10


@pytest.mark.parametrize(("opening", "status"), [
    (replace(OPEN, cost_gbp=None), "incomplete"),
    (replace(OPEN, history_confirmed=False), "incomplete"),
    (replace(OPEN, quantity=Decimal(1)), "unsupported"),
])
def test_unknown_and_impossible_opening_pool_blocks_qualified_gain(opening, status):
    result = calculate((opening, sell("sale", date(2026, 9, 1), 2)), {})
    assert result.status == status and result.warnings
    assert result.gains[0].gain_gbp is None
    assert not result.pool_movements


def test_missing_unrelated_basis_does_not_hide_forecast_allocation_dependency():
    nov, dec = date(2026, 11, 20), date(2026, 12, 15)
    prior = sell("prior", nov, 10)
    lot = buy("lot", dec, 10, 100)
    forecast = replace(sell("forecast", dec, 10), source=source("forecast", "forecast"))
    missing = buy("missing", date(2027, 2, 1), 1, 10)
    result = calculate((OPEN, prior, lot, forecast, missing), {"lot": 100})
    assert result.status == "incomplete"
    assert result.gains[0].gain_gbp == 50
    assert result.gains[0].status == "estimated"
