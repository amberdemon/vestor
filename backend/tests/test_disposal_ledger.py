from dataclasses import replace
from datetime import date
from decimal import Decimal
from fractions import Fraction

from vestor_domain.disposal_ledger import calculate_disposal_ledger
from vestor_domain.fx import FxRate, FxRates
from vestor_domain.share_evidence import (
    Fee, Grant, OpeningHolding, Sale, Security, ShareSource, Vest, WithholdingLink,
)


def d(value):
    return Decimal(value)


def source(key, status="actual", replaces=None):
    return ShareSource(key, status, "synthetic brokerage evidence", replaces)


TRADE = date(2027, 4, 5)
SETTLEMENT = date(2027, 4, 7)
SHARES = Security("issuer", "A", "owner", "personal", True)
OPENING = OpeningHolding(source("opening"), SHARES, date(2027, 4, 4),
                         d("100"), d("800"), True, date(2027, 5, 6))
SALE = Sale(source("sale"), SHARES, TRADE, d("10"), d("120"), "USD", "voluntary",
            settlement_on=SETTLEMENT, rate_id="sale-rate", uk_resident=True)
RATES = FxRates((
    FxRate(source("sale-rate"), TRADE, "disposal_proceeds", d("0.75"), "GBP/USD"),
    FxRate(source("fee-rate"), TRADE, "disposal_fee", d("0.80"), "GBP/USD"),
))


def test_trade_year_and_exact_gross_and_mixed_currency_expenses():
    sale = replace(SALE, price_per_share=d("12"), fees_confirmed=True)
    expenses = (
        Fee(source("usd-fee"), "sale", TRADE, d("1.50"), "USD", "fee-rate", category="eligible_dealing"),
        Fee(source("gbp-fee"), "sale", TRADE, d("0.50"), "GBP", category="eligible_dealing"),
        Fee(source("wire-fee"), "sale", SETTLEMENT, d("6"), "GBP", category="cash_transfer"),
    )
    ledger = calculate_disposal_ledger((OPENING, sale, *expenses), RATES)
    trade, = ledger.disposals
    assert trade.status == "confirmed"
    assert trade.sale == sale
    assert trade.tax_year_start == 2026
    assert trade.gross_gbp == 90
    assert trade.eligible_fees_gbp == Fraction(17, 10)
    assert trade.net_tax_proceeds_gbp == Fraction(883, 10)


def test_unknown_fee_classification_leaves_known_gross_proceeds_available():
    sale = replace(SALE, price_per_share=d("12"), fees_confirmed=True)
    fee = Fee(source("unknown-fee"), "sale", TRADE, d("2"), "GBP")
    trade, = calculate_disposal_ledger((OPENING, sale, fee), RATES).disposals
    assert trade.status == "incomplete"
    assert trade.gross_gbp == 90
    assert trade.net_tax_proceeds_gbp is None
    assert any(warning.field == "unknown-fee" for warning in trade.warnings)


def test_price_quantity_conflict_does_not_produce_tax_proceeds():
    sale = replace(SALE, price_per_share=d("12.01"), fees_confirmed=True)
    trade, = calculate_disposal_ledger((OPENING, sale), RATES).disposals
    assert trade.status == "input_error"
    assert trade.net_tax_proceeds_gbp is None


def test_forecast_cancellation_preserves_sources_and_excludes_projected_fee():
    forecast = replace(SALE, source=source("forecast", "forecast"), price_per_share=d("12"),
                       fees_confirmed=True)
    projected_fee = Fee(source("projected-fee", "forecast"), "forecast", TRADE, d("2"), "GBP",
                        category="eligible_dealing")
    cancelled = replace(forecast, source=source("cancel", replaces="forecast"), cancelled=True,
                        trade_on=None, quantity=None, gross_amount=None, price_per_share=None,
                        rate_id=None, settlement_on=None)
    ledger = calculate_disposal_ledger((OPENING, forecast, projected_fee, cancelled), RATES)
    assert ledger.evidence.status == "confirmed"
    assert ledger.evidence.replacements == (("forecast", "cancel"),)
    assert ledger.evidence.records == (OPENING, forecast, projected_fee, cancelled)
    assert ledger.evidence.active == (OPENING,)
    assert ledger.disposals == ()


def test_replacement_uses_actual_trade_date_price_and_currency():
    forecast = replace(SALE, source=source("forecast", "forecast"), price_per_share=d("12"),
                       fees_confirmed=True)
    actual = replace(forecast, source=source("actual", replaces="forecast"),
                     trade_on=date(2027, 4, 6), currency="GBP", rate_id=None,
                     gross_amount=None, price_per_share=d("8.435"))
    ledger = calculate_disposal_ledger((OPENING, forecast, actual), RATES)
    trade, = ledger.disposals
    assert trade.tax_year_start == 2027
    assert trade.gross_gbp == trade.net_tax_proceeds_gbp == Fraction(1687, 20)
    assert ledger.evidence.replacements == (("forecast", "actual"),)


def test_missing_other_broker_fee_details_block_only_broker_net():
    sale = replace(SALE, price_per_share=d("12"), fees_confirmed=True)
    fee = Fee(source("other"), "sale", TRADE, None, "GBP", category="other_broker")
    trade, = calculate_disposal_ledger((OPENING, sale, fee), RATES).disposals
    assert trade.status == "confirmed" and trade.net_tax_proceeds_gbp == 90
    assert trade.net_broker_proceeds_gbp is None and trade.broker_warnings


def test_duplicate_trade_ids_block_resolution():
    sale = replace(SALE, price_per_share=d("12"), fees_confirmed=True)
    ledger = calculate_disposal_ledger((OPENING, sale, sale), RATES)
    assert ledger.evidence.status == "input_error"
    assert ledger.disposals == ()


def test_cover_disposals_preserve_gross_shares_and_separate_withholding_links():
    grant = Grant(source("grant"), SHARES, date(2026, 5, 1), "ordinary_rsu")
    vest = Vest(source("vest"), SHARES, "grant", TRADE, TRADE, TRADE, d("100"), d("12"), uk_resident=True)
    opening = replace(OPENING, quantity=d("0"), cost_gbp=d("0"))
    cover = replace(SALE, source=source("first"), quantity=d("20"), gross_amount=None,
                    price_per_share=d("12"), fees_confirmed=True, purpose="sell_to_cover", vest_id="vest")
    second = replace(cover, source=source("second"), quantity=d("25"))
    withholding = WithholdingLink(source("remit"), "vest", "first", SETTLEMENT)
    ledger = calculate_disposal_ledger((opening, grant, vest, cover, second, withholding), RATES)
    first, second = ledger.disposals
    assert ledger.evidence.status == "confirmed"
    assert vest.quantity - first.sale.quantity - second.sale.quantity == 55
    assert (first.net_tax_proceeds_gbp, second.net_tax_proceeds_gbp) == (180, 225)
    assert first.withholding_ids == ("remit",) and not first.withholding_warnings
    assert second.withholding_warnings


def test_missing_proceeds_fx_leaves_raw_proceeds_and_eligible_fees_available():
    sale = replace(SALE, price_per_share=d("12"), fees_confirmed=True, rate_id=None)
    fee = Fee(source("gbp-fee"), "sale", TRADE, d("2"), "GBP", category="eligible_dealing")
    trade, = calculate_disposal_ledger((OPENING, sale, fee), RATES).disposals
    assert trade.status == "incomplete"
    assert trade.gross_native == 120 and trade.eligible_fees_gbp == 2
    assert trade.gross_gbp is trade.net_tax_proceeds_gbp is None


def test_forecast_nonallowable_broker_fee_marks_only_broker_net_estimated():
    sale = replace(SALE, price_per_share=d("12"), fees_confirmed=True)
    fee = Fee(source("broker", "forecast"), "sale", TRADE, d("2"), "GBP", category="other_broker")
    trade, = calculate_disposal_ledger((OPENING, sale, fee), RATES).disposals
    assert trade.status == "confirmed" and trade.net_tax_proceeds_gbp == 90
    assert trade.broker_status == "estimated" and trade.net_broker_proceeds_gbp == 88
