from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction

import pytest

from vestor_domain.disposal_ledger import calculate_disposal_ledger
from vestor_domain.fx import FxRates
from vestor_domain.priority_matching import AcquisitionBasis, identify_priority_matches
from vestor_domain.share_evidence import Grant, OpeningHolding, Purchase, Sale, Security, ShareSource, Vest


SHARE = Security("issuer", "A", "owner", "personal", True)
NOV = date(2026, 11, 20)
DEC = date(2026, 12, 15)
OPEN = OpeningHolding(ShareSource("opening", "actual", "synthetic"), SHARE, date(2026, 4, 5),
                      Decimal(100), Decimal(500), True, date(2027, 5, 31))


def source(key, status="actual"):
    return ShareSource(key, status, "synthetic matching evidence")


def sell(key, on, quantity, *, vest=None, security=SHARE):
    return Sale(source(key), security, on, Decimal(quantity), None, "GBP",
                "voluntary" if vest is None else "sell_to_cover", vest, uk_resident=True,
                price_per_share=Decimal(10), fees_confirmed=True)


def buy(key, on, quantity, cost, *, security=SHARE, resident=True):
    return Purchase(source(key), security, on, Decimal(quantity), Decimal(cost), "GBP", uk_resident=resident)


def match(records, costs):
    ledger = calculate_disposal_ledger(records, FxRates(()))
    return identify_priority_matches(ledger, {
        key: AcquisitionBasis(Fraction(amount), "confirmed") for key, amount in costs.items()
    })


def test_f5_reserves_same_day_cover_before_prior_sale():
    grant = Grant(source("grant"), SHARE, date(2025, 5, 1), "ordinary_rsu")
    vest = Vest(source("vest"), SHARE, "grant", DEC, DEC, DEC, Decimal(40), Decimal(8), uk_resident=True)
    result = match((OPEN, sell("nov", NOV, 100), grant, vest, sell("cover", DEC, 20, vest="vest")), {"vest": 320})
    assert result.status == "confirmed"
    assert [(s.disposal_id, s.acquisition_id, s.rule, s.quantity, s.basis_gbp) for s in result.segments] == [
        ("cover", "vest", "same_day", 20, 160),
        ("nov", "vest", "following_30_days", 20, 160),
    ]
    assert result.disposal_remainders == (("nov", Fraction(80)), ("cover", Fraction(0)))
    assert result.acquisition_remainders == (("vest", Fraction(0)),)


def test_same_day_aggregate_is_weighted_across_every_original_source():
    records = (OPEN, buy("a", NOV, 3, 15), buy("b", NOV, 3, 27),
               sell("small", NOV, 2), sell("large", NOV, 6))
    result = match(records, {"a": 15, "b": 27})
    assert result.status == "confirmed"
    assert sum(s.quantity for s in result.segments if s.disposal_id == "small") == Fraction(3, 2)
    assert sum(s.basis_gbp for s in result.segments if s.disposal_id == "small") == Fraction(21, 2)
    assert sum(s.quantity for s in result.segments) == 6
    assert sum(s.basis_gbp for s in result.segments) == 42
    assert result == match(tuple(reversed(records)), {"b": 27, "a": 15})


@pytest.mark.parametrize(("days", "matched"), [(-1, 0), (29, 4), (30, 4), (31, 0)])
def test_cross_year_calendar_boundaries(days, matched):
    sold_on = date(2027, 4, 5)
    acquired_on = sold_on + timedelta(days=days)
    result = match((OPEN, sell("sale", sold_on, 10), buy("buy", acquired_on, 4, 28)), {"buy": 28})
    assert sum(s.quantity for s in result.segments) == matched
    for segment in result.segments:
        assert segment.disposal_tax_year_start == 2026
        assert segment.acquired_on == acquired_on


def test_overlapping_windows_use_earliest_sale_and_earliest_acquisition():
    result = match((OPEN, sell("early", NOV, 10), sell("late", NOV + timedelta(days=4), 10),
                    buy("a", NOV + timedelta(days=9), 12, 120),
                    buy("b", NOV + timedelta(days=19), 3, 33)), {"a": 120, "b": 33})
    assert [(s.disposal_id, s.acquisition_id, s.quantity, s.basis_gbp) for s in result.segments] == [
        ("early", "a", 10, 100), ("late", "a", 2, 20), ("late", "b", 3, 33),
    ]
    assert result.disposal_remainders == (("early", Fraction(0)), ("late", Fraction(5)))


@pytest.mark.parametrize(("first", "second", "available"), [(1, 3, 2), (4, 6, 19), (2, 7, 8), (5, 5, 10)])
def test_quantities_and_attributed_cost_are_conserved(first, second, available):
    records = (OPEN, sell("prior", NOV, first), sell("later", DEC, second),
               buy("lot", DEC, available, 41))
    result = match(records, {"lot": 41})
    used = sum(s.quantity for s in result.segments)
    assert used + dict(result.acquisition_remainders)["lot"] == available
    assert sum(s.basis_gbp for s in result.segments) == Fraction(41) * used / available
    for key, expected in (("prior", first), ("later", second)):
        assert sum(s.quantity for s in result.segments if s.disposal_id == key) + dict(result.disposal_remainders)[key] == expected


def test_other_share_class_is_never_matched():
    other = replace(SHARE, share_class="B")
    result = match((OPEN, replace(OPEN, source=source("opening-b"), security=other),
                    sell("a-sale", NOV, 10), buy("b-buy", NOV, 10, 100, security=other)), {"b-buy": 100})
    assert result.status == "confirmed"
    assert result.segments == ()


@pytest.mark.parametrize(("resident", "expected"), [(None, "incomplete"), (False, "unsupported")])
def test_acquisition_residence_prevents_qualified_identification(resident, expected):
    result = match((OPEN, sell("sale", NOV, 10), buy("later", DEC, 10, 100, resident=resident)), {"later": 100})
    assert result.status == expected
    assert not result.segments and result.warnings


def test_missing_basis_preserves_share_identification_without_claiming_cost():
    result = match((OPEN, sell("sale", NOV, 10), buy("lot", DEC, 10, 100)), {})
    segment, = result.segments
    assert result.status == segment.status == "incomplete"
    assert segment.quantity == 10 and segment.basis_gbp is None


def test_duplicate_lots_and_unconfirmed_history_block_qualified_segments():
    lot = buy("lot", DEC, 10, 100)
    sale = sell("sale", NOV, 10)
    assert match((OPEN, sale, lot, lot), {"lot": 100}).status == "input_error"
    incomplete = match((replace(OPEN, coverage_through=NOV + timedelta(days=29)), sale, lot), {"lot": 100})
    assert incomplete.status == "incomplete" and not incomplete.segments


def test_forecast_same_day_competitor_makes_affected_actual_match_provisional():
    future_buy = buy("buy", DEC, 20, 100)
    competitor = replace(sell("forecast", DEC, 12), source=source("forecast", "forecast"))
    result = match((OPEN, sell("actual", NOV, 10), competitor, future_buy), {"buy": 100})
    assert result.status == "estimated"
    assert [(s.disposal_id, s.quantity, s.status) for s in result.segments] == [
        ("forecast", 12, "estimated"), ("actual", 8, "estimated"),
    ]
