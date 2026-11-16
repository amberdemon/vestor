import type { Field, RecordValue } from "./inputs";

const f = (key: string, label: string, type?: Field["type"]): Field => ({ key, label, type });
const option = (key: string, label: string, ...options: string[]): Field => ({ key, label, options });
const group = (key: string, label: string, fields: Field[]): Field => ({ key, label, fields });
const date = (key: string, label: string) => f(key, label, "date");
const decimal = (key: string, label: string) => f(key, label, "decimal");
const money = (key: string, label: string) => f(key, label, "money");
const confirm = (key: string, label: string) => f(key, label, "bool");
const yesNo = (key: string, label: string) => f(key, label, "tri");
const currency = option("currency", "Currency", "GBP", "USD");
const rate = f("rate_id", "FX rate ID for USD");
const quantity = decimal("quantity", "Number of shares");
const ukResident = yesNo("uk_resident", "UK tax resident on this date");
const source = group("source", "Source evidence", [
  f("event_id", "Source ID"),
  option("source_status", "Source status", "unknown", "actual", "forecast"),
  f("source_note", "Source or assumption note"),
  f("replaces_forecast_id", "Forecast source ID replaced"),
]);
const security = group("security", "Share identity", [
  f("issuer_id", "Issuer ID"), f("share_class", "Share class"), f("owner_id", "Beneficial owner ID"),
  option("capacity", "Holding capacity", "personal", "trust", "joint", "other"),
  yesNo("ordinary_listed", "Ordinary listed shares"),
]);

export function blankFields(fields: Field[]): RecordValue {
  return Object.fromEntries(fields.map((field) => [
    field.key,
    field.fields ? blankFields(field.fields)
      : field.type === "bool" ? false
      : field.type === "ids" ? []
      : field.options?.[0] || null,
  ]));
}

type LedgerSection = { key: string; title: string; add: string; fields: Field[] };

export const ledgerSections: LedgerSection[] = [
  { key: "grants", title: "Grants", add: "Add grant", fields: [
    source, security, date("awarded_on", "Award date"),
    option("treatment", "Award treatment", "", "ordinary_rsu", "unsupported"),
  ] },
  { key: "vests", title: "Vests and acquisition basis", add: "Add vest", fields: [
    group("vest", "Vest event", [
      source, security, f("grant_id", "Grant source ID"), date("vested_on", "Vest date"),
      date("acquired_on", "Acquisition date"), date("charge_on", "Employment charge date"),
      quantity, decimal("fmv_usd_per_share", "USD fair market value per share"),
      f("income_rate_id", "Vest income FX rate ID"), f("basis_rate_id", "Acquisition FX rate ID"), ukResident,
    ]),
    money("gross_usd", "Reported gross value in USD"),
    money("confirmed_payroll_gbp", "Confirmed gross taxable payroll GBP"),
    yesNo("included_in_payroll", "Already included in an ANI payroll entry"),
    f("payroll_ids", "ANI payroll source IDs, comma separated", "ids"),
    f("manual_vest_id", "Canonical manual ANI vest source ID"),
    f("replaces_manual_forecast_id", "Manual forecast ANI vest source ID replaced"),
    option("basis_method", "CGT acquisition basis method", "", "market_value", "nil_price_chapter_5"),
    money("confirmed_basis_gbp", "Confirmed total allowable acquisition basis in GBP"),
    confirm("acquisition_fees_confirmed", "Acquisition expenses covered, or none"),
  ] },
  { key: "opening_holdings", title: "Opening holdings", add: "Add opening holding", fields: [
    source, security, date("as_of", "Opening snapshot date"), quantity,
    decimal("cost_gbp", "Opening allowable cost in GBP"),
    confirm("history_confirmed", "Opening history reconciled"),
    date("coverage_through", "History covered through this date"),
  ] },
  { key: "purchases", title: "Other acquisitions", add: "Add purchase", fields: [
    source, security, date("acquired_on", "Purchase date"), quantity,
    decimal("gross_amount", "Purchase cost before fees"), currency, rate, ukResident,
    confirm("fees_confirmed", "Purchase fees covered, or none"),
  ] },
  { key: "sales", title: "Sales and sell-to-cover", add: "Add sale", fields: [
    source, security, option("purpose", "Sale purpose", "voluntary", "sell_to_cover"),
    f("vest_id", "Linked vest source ID for sell-to-cover"),
    date("trade_on", "Trade date"), date("settlement_on", "Broker settlement date"),
    quantity, decimal("price_per_share", "Trade price per share"),
    decimal("gross_amount", "Reported gross sale amount"), currency, rate, ukResident,
    confirm("fees_confirmed", "Sale fees covered, or none"),
    confirm("cancelled", "Cancel the linked forecast sale"),
  ] },
  { key: "fees", title: "Broker fees", add: "Add fee", fields: [
    source, f("transaction_id", "Sale or acquisition source ID"), date("on", "Fee date"),
    decimal("amount", "Fee amount"), currency, rate,
    option("category", "Fee category", "", "eligible_dealing", "other_broker", "cash_transfer"),
  ] },
  { key: "rates", title: "Dated FX rates", add: "Add FX rate", fields: [
    source, date("on", "Rate date"), decimal("gbp_per_usd", "GBP per one USD"),
    option("purpose", "Rate purpose", "vest_income", "acquisition_basis", "disposal_proceeds",
      "acquisition_fee", "disposal_fee", "cash_settlement"),
  ] },
  { key: "withholding_links", title: "Cover remittance links", add: "Add remittance link", fields: [
    source, f("vest_id", "Vest source ID"), f("sale_id", "Cover sale source ID"), date("remitted_on", "Remittance date"),
  ] },
  { key: "payroll_entries", title: "Payroll settlements", add: "Add payroll settlement", fields: [
    source, f("vest_id", "Vest source ID"), date("on", "Payroll evidence date"),
    option("kind", "Payroll entry kind", "liability", "withholding", "repayment", "reported_owed"),
    option("component", "Liability tax component", "", "combined", "income_tax", "national_insurance"),
    option("method", "Method", "payroll", "broker_cover", "employer_repayment"),
    decimal("amount", "Payroll evidence amount"), currency, f("liability_id", "Liability source ID"),
    f("withholding_link_id", "Cover remittance source ID"), f("transaction_ref", "Payment reference"),
    yesNo("settled", "Payment settled"),
  ] },
  { key: "transfers", title: "Broker transfers", add: "Add transfer", fields: [
    source, f("transaction_ref", "Transfer reference"), date("executed_on", "Execution date"),
    date("received_on", "Receipt date"), decimal("sent_usd", "USD sent"),
    decimal("fee_usd", "Fixed fee in USD"), decimal("fee_gbp", "Fixed fee in GBP"),
    decimal("received_gbp", "GBP received"), f("rate_id", "Execution FX rate ID"),
    f("reference_rate_id", "Reference FX rate ID for spread comparison"),
  ] },
  { key: "broker_balances", title: "Broker balances", add: "Add broker balance", fields: [
    source, date("on", "Balance date"), decimal("amount", "Observed balance"), currency,
  ] },
];

export const annualFields: Field[] = [
  yesNo("ordinary_treatment", "Ordinary supported CGT treatment"),
  yesNo("eligible_for_aea", "Eligible for the full annual exemption"),
  confirm("share_coverage_confirmed", "All share sales for this tax year covered, or none"),
];

export const capitalFields: Field[] = [
  source, money("other_gains_gbp", "Other ordinary gains in GBP"),
  money("other_current_losses_gbp", "Other allowable losses this year in GBP"),
  money("available_brought_forward_gbp", "Available brought-forward losses in GBP"),
];

export const bandFields: Field[] = [
  source, money("unused_basic_band_gbp", "Externally confirmed unused basic band in GBP"),
  money("taxable_income_gbp", "Externally confirmed taxable income in GBP"),
  money("basic_band_extension_gbp", "Confirmed basic band extension in GBP"),
];

export const settlementCoverage = [
  confirm("payroll_coverage", "Payroll settlements covered, or none"),
  confirm("cash_coverage", "Broker cash evidence covered, or none"),
];

export const initialLedger: RecordValue = {
  ...Object.fromEntries(ledgerSections.map(({ key }) => [key, []])),
  annual: { ...blankFields(annualFields), capital: null, band: null },
  ...blankFields(settlementCoverage),
};
