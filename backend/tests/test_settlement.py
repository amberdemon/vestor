from dataclasses import replace
from datetime import date
from decimal import Decimal
from fractions import Fraction

import pytest

from test_ani import inputs
from test_rsu import vest as manual_vest
from test_disposal_ledger import OPENING, RATES, SALE, SETTLEMENT, SHARES, TRADE, source
from vestor_domain.ani import calculate_ani
from vestor_domain.disposal_ledger import calculate_disposal_ledger
from vestor_domain.fx import FxRate, FxRates
from vestor_domain.settlement import BrokerTransfer, PayrollEntry, calculate_settlement
from vestor_domain.share_evidence import Grant, Vest, WithholdingLink


def d(value):
    return Decimal(value)


def cover_ledger():
    grant = Grant(source("grant"), SHARES, date(2025, 5, 1), "ordinary_rsu")
    vest = Vest(source("vest"), SHARES, "grant", TRADE, TRADE, TRADE, d(100), d(10), uk_resident=True)
    sale = replace(SALE, quantity=d(45), price_per_share=d(10), gross_amount=None, currency="GBP",
                   rate_id=None, fees_confirmed=True, purpose="sell_to_cover", vest_id="vest")
    return calculate_disposal_ledger((OPENING, grant, vest, sale,
                                     WithholdingLink(source("remit"), "vest", "sale", SETTLEMENT)), RATES)


def test_partial_settlements_keep_reported_owed_distinct_from_cover_cash():
    ledger = cover_ledger()
    entries = (
        PayrollEntry(source("liability"), "vest", TRADE, "GBP", "liability", d(550), "payroll"),
        PayrollEntry(source("withheld"), "vest", SETTLEMENT, "GBP", "withholding", d(450), "broker_cover",
                     liability_id="liability", withholding_link_id="remit", settled=True, transaction_ref="broker-01"),
        PayrollEntry(source("paid"), "vest", SETTLEMENT, "GBP", "repayment", d(25), "employer_repayment",
                     liability_id="liability", settled=True, transaction_ref="pay-01"),
        PayrollEntry(source("owed"), "vest", SETTLEMENT, "GBP", "reported_owed", d(75), "payroll",
                     liability_id="liability"),
    )
    result = calculate_settlement(ledger, entries, (), RATES, payroll_coverage=True, cash_coverage=True)
    payroll, = result.payroll
    assert result.payroll_status == "confirmed"
    assert payroll.withheld_gbp == 450 and payroll.repaid_gbp == 25
    assert payroll.reported_owed_gbp == 75 and payroll.reconciliation_difference_gbp == 0
    cover, = result.cover_cash
    assert cover.net_broker_proceeds_gbp == 450 and cover.after_linked_remittance_gbp == 0
    assert ledger.disposals[0].net_tax_proceeds_gbp == 450


def test_wire_reconciles_execution_fx_and_fixed_fees_without_changing_trade():
    transfer = BrokerTransfer(source("wire"), "wire-01", TRADE, SETTLEMENT, d(100), d(2), d(1),
                              d("77.4"), "execution", reference_rate_id="reference")
    rates = FxRates((
        FxRate(source("execution"), TRADE, "cash_settlement", d(".8"), "GBP/USD"),
        FxRate(source("reference"), TRADE, "cash_settlement", d(".81"), "GBP/USD"),
    ))
    ledger = cover_ledger()
    result = calculate_settlement(ledger, (), (transfer,), rates, payroll_coverage=False, cash_coverage=True)
    row, = result.transfers
    assert row.actual_received_gbp == Fraction(387, 5)
    assert row.expected_received_gbp == Fraction(387, 5)
    assert row.receipt_difference_gbp == 0
    assert row.fx_spread_gbp == Fraction(49, 50)
    assert ledger.disposals[0].net_tax_proceeds_gbp == 450
    assert result.payroll_status == result.cash_status == "incomplete"
    assert row.status == "confirmed"


@pytest.mark.parametrize(("paid", "difference"), [("400", 50), ("470", -20)])
def test_payment_mismatch_never_infers_the_reported_amount_owed(paid, difference):
    entries = (
        PayrollEntry(source("liability"), "vest", TRADE, "GBP", "liability", d(450), "payroll"),
        PayrollEntry(source("payment"), "vest", SETTLEMENT, "GBP", "withholding", d(paid), "payroll",
                     liability_id="liability", settled=True, transaction_ref="pay-1"),
        PayrollEntry(source("reported"), "vest", SETTLEMENT, "GBP", "reported_owed", d(0), "payroll",
                     liability_id="liability"),
    )
    result = calculate_settlement(cover_ledger(), entries, (), RATES,
                                  payroll_coverage=True, cash_coverage=False)
    group, = result.payroll
    assert group.reconciliation_difference_gbp == difference
    assert group.reported_owed_gbp == 0
    assert group.status == "incomplete"


def test_duplicate_payment_reference_rejects_the_affected_amount():
    liability = PayrollEntry(source("liability"), "vest", TRADE, "GBP", "liability", d(450), "payroll")
    payment = PayrollEntry(source("payment"), "vest", SETTLEMENT, "GBP", "withholding", d(225), "payroll",
                           liability_id="liability", settled=True, transaction_ref="same")
    result = calculate_settlement(cover_ledger(), (liability, payment, replace(payment, source=source("duplicate"))),
                                  (), RATES, payroll_coverage=True, cash_coverage=False)
    assert result.payroll_status == "input_error"
    assert result.payroll[0].withheld == 0
    assert not result.payroll[0].reconciliation_difference


def test_forecast_wire_replaced_once_and_duplicate_reference_is_explicit():
    rate = FxRate(source("execution"), TRADE, "cash_settlement", d(".8"), "GBP/USD")
    forecast = BrokerTransfer(source("forecast", "forecast"), "wire-1", TRADE, None, d(100), d(0), d(0),
                              None, "execution")
    actual = replace(forecast, source=source("actual", replaces="forecast"),
                     received_on=SETTLEMENT, received_gbp=d(80))
    ledger = calculate_disposal_ledger((), RATES)
    rates = FxRates((rate,))
    result = calculate_settlement(ledger, (), (forecast, actual), rates,
                                  payroll_coverage=True, cash_coverage=True)
    assert result.cash_status == "confirmed" and result.replacements == (("forecast", "actual"),)
    assert result.sources == (forecast, actual)
    assert result.transfers[0].actual_received_gbp == 80
    duplicate = replace(actual, source=source("duplicate"))
    invalid = calculate_settlement(ledger, (), (forecast, actual, duplicate), rates,
                                   payroll_coverage=True, cash_coverage=True)
    assert invalid.cash_status == "input_error"


def test_unknown_receipt_and_reported_balance_remain_distinct_from_ani():
    from vestor_domain.settlement import BrokerBalance

    ledger = cover_ledger()
    base = inputs(rsu_events=(manual_vest("vest", "1000", TRADE.isoformat()),))
    before = calculate_ani(base)
    transfer = BrokerTransfer(source("wire"), "wire-02", TRADE, None, d(100), d(0), d(0), None, None)
    balance = BrokerBalance(source("balance"), SETTLEMENT, "USD", d(50))
    result = calculate_settlement(ledger, (), (transfer, balance), RATES,
                                  payroll_coverage=False, cash_coverage=True)
    assert result.balances == (balance,)
    assert result.transfers[0].actual_received_gbp is None and result.cash_status == "incomplete"
    assert calculate_ani(base) == before
    assert before.rsu.taxable_gbp == 1000
