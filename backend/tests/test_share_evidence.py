from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime
from decimal import Decimal

import pytest

from vestor_domain.primitives import InputError
from vestor_domain.share_evidence import (
    Fee, Grant, OpeningHolding, Purchase, Sale, Security, ShareSource, Vest,
    WithholdingLink, validate_share_evidence,
)


def day(value):
    return date.fromisoformat(value)


def source(event_id, status="actual", replaces=None):
    return ShareSource(event_id, status, "synthetic evidence", replaces)


SHARE = Security("fictional-issuer", "ordinary-A", "owner", "personal", True)
OPENING = OpeningHolding(source("opening"), SHARE, day("2026-04-05"), Decimal("0"), Decimal("0"),
                         True, day("2027-05-05"))
GRANT = Grant(source("grant"), SHARE, day("2025-01-01"), "ordinary_rsu")
VEST = Vest(source("vest"), SHARE, "grant", day("2026-04-06"), day("2026-04-06"),
            day("2026-04-06"), Decimal("10.123456789"), Decimal("1.23456789"), "income-rate", "basis-rate", uk_resident=True)
SALE = Sale(source("sale"), SHARE, day("2026-04-06"), Decimal("4"), Decimal("5"), "USD",
            "sell_to_cover", "vest", day("2026-04-08"), "sale-rate", uk_resident=True)


def test_complete_cover_and_voluntary_sales_keep_distinct_dates_and_evidence():
    fee = Fee(source("fee"), "sale", day("2026-04-06"), Decimal("0.025"), "USD", "fee-rate")
    withheld = WithholdingLink(source("withheld"), "vest", "sale", day("2026-04-09"))
    later_sale = replace(SALE, source=source("later"), trade_on=day("2026-05-08"),
                         settlement_on=None, quantity=Decimal("6.123456789"), purpose="voluntary", vest_id=None)
    records = (GRANT, VEST, SALE, OPENING, fee, withheld, later_sale)
    result = validate_share_evidence(records)
    assert result.status == "confirmed"
    assert result.records == result.active == records
    assert VEST.quantity == Decimal("10.123456789")
    with pytest.raises(FrozenInstanceError):
        VEST.quantity = Decimal("1")


@pytest.mark.parametrize(("change", "field"), [
    ({"quantity": 0.1}, "quantity"),
    ({"quantity": Decimal("NaN")}, "quantity"),
    ({"quantity": Decimal("-1")}, "quantity"),
    ({"quantity": Decimal("0")}, "quantity"),
    ({"fmv_usd_per_share": Decimal("Infinity")}, "fmv_usd_per_share"),
    ({"acquired_on": datetime(2026, 4, 6)}, "acquired_on"),
    ({"basis_rate_id": ""}, "basis_rate_id"),
])
def test_invalid_vest_fields(change, field):
    with pytest.raises(InputError) as exc:
        replace(VEST, **change)
    assert exc.value.field == field


@pytest.mark.parametrize(("factory", "field"), [
    (lambda: source(" "), "event_id"),
    (lambda: source("vest", "confirmed"), "source_status"),
    (lambda: source("vest", "forecast", "prior"), "replaces_forecast_id"),
    (lambda: replace(SALE, settlement_on=day("2026-04-05")), "settlement_on"),
    (lambda: replace(OPENING, cost_gbp=Decimal("1")), "cost_gbp"),
    (lambda: replace(OPENING, coverage_through=day("2026-04-04")), "coverage_through"),
    (lambda: Fee(source("fee"), "sale", SALE.trade_on, Decimal("1"), "EUR"), "currency"),
])
def test_invalid_metadata(factory, field):
    with pytest.raises(InputError) as exc:
        factory()
    assert exc.value.field == field


def test_actual_replaces_forecast_with_different_date_and_keeps_original():
    forecast = replace(VEST, source=source("forecast", "forecast"), charge_on=day("2026-04-05"))
    actual = replace(VEST, source=source("vest", replaces="forecast"))
    records = (OPENING, GRANT, forecast, actual, SALE)
    result = validate_share_evidence(records)
    assert result.status == "confirmed"
    assert result.records == records
    assert result.active == (OPENING, GRANT, actual, SALE)
    assert result.replacements == (("forecast", "vest"),)


@pytest.mark.parametrize(("records", "field"), [
    ((GRANT, VEST, VEST), "event_id"),
    ((replace(VEST, source=source("vest", replaces="missing")),), "replaces_forecast_id"),
    ((GRANT, replace(VEST, source=source("forecast", "forecast")),
      replace(SALE, source=source("sale", replaces="forecast"))), "replaces_forecast_id"),
    ((GRANT, replace(VEST, source=source("forecast", "forecast")),
      replace(VEST, source=source("one", replaces="forecast")),
      replace(VEST, source=source("two", replaces="forecast"))), "replaces_forecast_id"),
    ((GRANT, replace(VEST, source=source("forecast", "forecast")),
      replace(VEST, source=source("vest", replaces="forecast")),
      replace(SALE, vest_id="forecast")), "vest_id"),
    ((OPENING, GRANT, replace(VEST, grant_id="missing")), "grant_id"),
    ((OPENING, GRANT, VEST, replace(SALE, security=replace(SHARE, share_class="B"))), "vest_id"),
    ((OPENING, GRANT, VEST, replace(SALE, security=replace(SHARE, owner_id="different"))), "vest_id"),
    ((OPENING, GRANT, VEST, replace(SALE, trade_on=day("2026-04-07"))), "vest_id"),
    ((OPENING, GRANT, VEST, SALE, WithholdingLink(source("withheld"), "vest", "grant", None)), "sale_id"),
    ((OPENING, Fee(source("fee"), "missing", None, Decimal("0"), "GBP")), "transaction_id"),
])
def test_incompatible_record_links(records, field):
    result = validate_share_evidence(records)
    assert result.status == "input_error"
    assert result.records == records
    assert field in {problem.field for problem in result.warnings}


@pytest.mark.parametrize(("records", "expected"), [
    ((GRANT, VEST, SALE), "incomplete"),
    ((replace(OPENING, history_confirmed=False), GRANT, VEST, SALE), "incomplete"),
    ((replace(OPENING, coverage_through=day("2026-05-05")), GRANT, VEST, SALE), "incomplete"),
    ((OPENING, GRANT, replace(VEST, quantity=None), SALE), "incomplete"),
    ((OPENING, GRANT, replace(VEST, fmv_usd_per_share=None), SALE), "confirmed"),
    ((OPENING, GRANT, replace(VEST, uk_resident=None), SALE), "incomplete"),
    ((OPENING, GRANT, replace(VEST, charge_on=None), SALE), "incomplete"),
    ((OPENING, GRANT, replace(VEST, charge_on=day("2026-04-05")), SALE), "unsupported"),
    ((OPENING, GRANT, replace(VEST, security=replace(SHARE, ordinary_listed=None)), SALE), "incomplete"),
    ((OPENING, GRANT, replace(VEST, uk_resident=False), SALE), "unsupported"),
    ((OPENING, replace(GRANT, treatment="unsupported"), VEST, SALE), "unsupported"),
    ((OPENING, GRANT, VEST, replace(SALE, quantity=Decimal("11"), purpose="voluntary", vest_id=None)), "unsupported"),
    ((OPENING, GRANT, replace(VEST, source=source("vest", "forecast")), SALE), "estimated"),
    ((OPENING, GRANT, VEST, replace(SALE, gross_amount=None)), "incomplete"),
    ((OPENING, GRANT, VEST, replace(SALE, security=replace(SHARE, capacity="trust"), purpose="voluntary",
                                    vest_id=None)), "unsupported"),
])
def test_history_inventory_and_scope_status(records, expected):
    result = validate_share_evidence(records)
    assert result.status == expected
    assert result.records == records


def test_30_day_history_boundary_and_future_purchase_cannot_fund_oversale():
    opening = replace(OPENING, coverage_through=day("2026-05-06"))
    assert validate_share_evidence((opening, GRANT, VEST, SALE)).status == "confirmed"
    buy = Purchase(source("purchase"), SHARE, day("2026-04-10"), Decimal("10"), Decimal("70"), "GBP", uk_resident=True)
    sale = replace(SALE, purpose="voluntary", vest_id=None)
    assert validate_share_evidence((opening, sale, buy)).status == "unsupported"


def test_multiple_cover_sales_cannot_claim_more_shares_than_the_linked_vest():
    opening = replace(OPENING, quantity=Decimal("20"), cost_gbp=Decimal("20"))
    second_cover = replace(SALE, source=source("second"), quantity=Decimal("7"))
    result = validate_share_evidence((opening, GRANT, VEST, SALE, second_cover))
    assert result.status == "input_error"
    assert result.warnings[0].field == "quantity"
