// Wire values preserve decimal strings and date-only strings; no financial arithmetic here.
export type Value = string | number | boolean | null | RecordValue | Value[];
export type RecordValue = { [key: string]: Value };
export type Field = {
  key: string;
  label: string;
  type?: "money" | "percent" | "date" | "bool" | "tri" | "integer" | "ids";
  options?: string[];
  fields?: Field[];
  repeat?: boolean;
  initial?: RecordValue;
};
const f = (key: string, label: string, type?: Field["type"]): Field => ({
  key,
  label,
  type,
});
const select = (key: string, label: string, options: string[]): Field => ({
  key,
  label,
  options,
});
const status = select("source_status", "Source status", [
  "unknown",
  "forecast",
  "actual",
]);
const note = f("source_note", "Source / assumption note");
const dates = {
  key: "dates",
  label: "Inclusive effective dates",
  fields: [f("start", "Start date", "date"), f("end", "End date", "date")],
};
const money: Field = {
  key: "money",
  label: "Dated GBP evidence",
  fields: [
    f("event_id", "Source event ID"),
    f("on", "Taxable / effective date", "date"),
    f("amount_gbp", "GBP amount (blank = unknown)", "money"),
    status,
    note,
    f(
      "replaces_forecast_id",
      "Forecast event ID explicitly replaced (actual only)",
    ),
  ],
};
const payFields = [
  money,
  select("timing", "Receipt timing", [
    "unknown_date",
    "payment_date",
    "confirmed_receipt",
    "unconfirmed_entitlement",
  ]),
  select("basis", "Pay pension basis", [
    "unknown",
    "before_reductions",
    "after_reductions",
  ]),
  f(
    "entitlement_on",
    "Earlier entitlement date (payment date basis only)",
    "date",
  ),
  f(
    "reflected_methods",
    "Methods already reflected (comma separated: salary_sacrifice, net_pay; blank = both when after reductions)",
    "ids",
  ),
];
const periodDates = { start: "2026-04-06", end: "2027-04-05" };
const source = { source_status: "unknown", source_note: "" };
const dated = {
  event_id: "",
  on: "2026-04-06",
  amount_gbp: null,
  ...source,
  replaces_forecast_id: null,
};
const pay = {
  money: dated,
  timing: "unknown_date",
  basis: "unknown",
  entitlement_on: null,
  reflected_methods: null,
};
export const sections: {
  key: string;
  title: string;
  help: string;
  initial: RecordValue;
  fields: Field[];
  coverage?: string;
}[] = [
  {
    key: "salary_periods",
    title: "Salary periods",
    help: "Annual rates are calendar-day forecasts, even when the rate is confirmed. Cover the full tax year; enter zero for unpaid or out-of-employment periods. Split at every rate change.",
    initial: {
      period_id: "",
      dates: periodDates,
      annual_gbp: null,
      ...source,
      pay_frequency: null,
    },
    fields: [
      f("period_id", "Salary period ID"),
      dates,
      f("annual_gbp", "Annual salary GBP (blank = unknown)", "money"),
      status,
      note,
      f("pay_frequency", "Pay frequency (optional evidence)"),
    ],
  },
  {
    key: "salary_payments",
    title: "Dated payroll payments",
    help: "Optional actual or forecast payroll overrides. Link the salary period IDs and exact covered service days. Components identify bonuses, benefits and RSUs already in the payroll total. An empty component list confirms salary-only payroll.",
    initial: {
      pay,
      covered: periodDates,
      replaces_period_ids: [],
      components: null,
    },
    fields: [
      { key: "pay", label: "Payroll receipt and basis", fields: payFields },
      { ...dates, key: "covered", label: "Covered service dates" },
      f(
        "replaces_period_ids",
        "Salary period IDs replaced (comma separated)",
        "ids",
      ),
      {
        key: "components",
        label: "Included payroll components",
        repeat: true,
        initial: { component_id: "", kind: "rsu", amount_gbp: null },
        fields: [
          f("component_id", "Linked component source ID"),
          select("kind", "Component type", ["rsu", "benefit", "bonus"]),
          f("amount_gbp", "Included GBP", "money"),
        ],
      },
    ],
  },
  {
    key: "bonuses",
    title: "Bonus events",
    coverage: "bonus_coverage_confirmed",
    help: "Use taxable receipt, including any earlier entitlement. A change of source status keeps its ID. To retain replaced forecast evidence, add an actual with a new ID and explicit replacement link.",
    initial: pay,
    fields: payFields,
  },
  {
    key: "payroll_reductions",
    title: "Payroll pension reductions",
    help: "Salary sacrifice is a valid prospective contractual change. Net pay is a payroll deduction, after sacrifice. Relief at source belongs below. Link the pay or salary-period ID. Annual salary periods support salary sacrifice only; model net pay with dated payroll. Qualification confirms scheme eligibility and minimum wage compliance; allowance eligibility is not calculated.",
    initial: {
      reduction_id: "",
      pay_id: "",
      method: "salary_sacrifice",
      treatment: "apply",
      ...source,
      qualifies: null,
      fixed_gbp: null,
      percent: null,
      base: null,
      eligible_gbp: null,
      elected_on: null,
      effective_on: null,
      through: null,
      deducted_on: null,
    },
    fields: [
      f("reduction_id", "Reduction ID"),
      f("pay_id", "Linked salary period / payroll / bonus ID"),
      select("method", "Pension method", ["salary_sacrifice", "net_pay"]),
      select("treatment", "Apply or already reflected", ["apply", "reflected"]),
      status,
      note,
      f("qualifies", "Valid qualifying arrangement confirmed", "tri"),
      f("fixed_gbp", "Fixed GBP (annual for salary period)", "money"),
      f("percent", "Or percentage (up to 4 decimal places)", "percent"),
      select("base", "Percentage pay base", ["", "full_pay", "stated_amount"]),
      f("eligible_gbp", "Stated eligible GBP base", "money"),
      f("elected_on", "Election date (before affected pay)", "date"),
      f("effective_on", "Effective from", "date"),
      f("through", "Effective through (inclusive)", "date"),
      f("deducted_on", "Payroll deduction date", "date"),
    ],
  },
  {
    key: "adjustments",
    title: "Personal pensions, Gift Aid & employer funding",
    coverage: "pension_coverage_confirmed",
    help: "Confirm coverage of all payroll reductions and personal contributions here. Relief at source takes net cash paid or confirmed provider gross. Gift Aid takes qualifying net donations, not Payroll Giving or carry-back. Gross pension means eligible payment with no prior relief. Employer funding is evidence only.",
    initial: {
      money: dated,
      kind: "relief_at_source",
      qualifies: null,
      effective_date_known: false,
      provider_gross_gbp: null,
      recorded_on: null,
    },
    fields: [
      money,
      select("kind", "Contribution method", [
        "relief_at_source",
        "gross_pension",
        "gift_aid",
        "employer",
      ]),
      f(
        "qualifies",
        "Eligibility confirmed (Gift Aid includes sufficient tax)",
        "tri",
      ),
      f(
        "effective_date_known",
        "Effective contribution date confirmed",
        "bool",
      ),
      f(
        "provider_gross_gbp",
        "Provider-confirmed gross RAS GBP (optional)",
        "money",
      ),
      f("recorded_on", "Provider / evidence record date (optional)", "date"),
    ],
  },
  {
    key: "benefits",
    title: "Benefits & renewals",
    coverage: "benefit_coverage_confirmed",
    help: "Enter annual taxable value, not insurance premium. Add a period for each renewal with the same benefit ID. Daily apportionment needs confirmation. Actual payrolled/P11D amounts cover the stated period in full; link payroll if included. Premium and employee payment are evidence, not automatic deductions.",
    initial: {
      period_id: "",
      benefit_id: "",
      category: "",
      dates: periodDates,
      taxability: "unknown",
      ...source,
      basis: null,
      taxable_gbp: null,
      annual_premium_gbp: null,
      payer: null,
      employee_contribution_gbp: null,
      daily_apportionment_confirmed: false,
      included_in_payroll: null,
      payroll_ids: [],
      replaces_forecast_ids: [],
    },
    fields: [
      f("period_id", "Benefit period ID"),
      f("benefit_id", "Stable benefit ID (same across renewals)"),
      f("category", "Benefit description"),
      dates,
      select("taxability", "Taxability", ["unknown", "yes", "no"]),
      status,
      note,
      select("basis", "Taxable value basis", [
        "",
        "annual_taxable",
        "payrolled",
        "p11d",
      ]),
      f(
        "taxable_gbp",
        "Taxable GBP (annual for annual taxable basis)",
        "money",
      ),
      f("annual_premium_gbp", "Annual premium GBP (evidence only)", "money"),
      f("payer", "Premium payer (optional)"),
      f(
        "employee_contribution_gbp",
        "Employee payment GBP (evidence only)",
        "money",
      ),
      f(
        "daily_apportionment_confirmed",
        "Daily apportionment appropriate",
        "bool",
      ),
      f("included_in_payroll", "Included in taxable payroll", "tri"),
      f("payroll_ids", "Linked payroll IDs (comma separated)", "ids"),
      f(
        "replaces_forecast_ids",
        "Forecast benefit period IDs replaced (comma separated)",
        "ids",
      ),
    ],
  },
  {
    key: "rsu_events",
    title: "RSU vest employment income",
    coverage: "rsu_coverage_confirmed",
    help: "Gross taxable GBP at vest, before withholding or sell-to-cover. This is employment income, not stock-sale gain. No USD, FX, share sales or CGT calculation in M1.",
    initial: {
      money: dated,
      charge_date_confirmed: false,
      supported_award: null,
      included_in_payroll: null,
      payroll_ids: [],
      label: null,
      sold_to_cover_percent: null,
    },
    fields: [
      money,
      f("charge_date_confirmed", "Taxable charge date confirmed", "bool"),
      f("supported_award", "Ordinary supported RSU award confirmed", "tri"),
      f("included_in_payroll", "Included in taxable payroll", "tri"),
      f("payroll_ids", "Linked payroll IDs (comma separated)", "ids"),
      f("label", "Award label (optional)"),
      f("sold_to_cover_percent", "Sold-to-cover % (evidence only)", "percent"),
    ],
  },
  {
    key: "other_income",
    title: "Interest, dividends & other income",
    coverage: "other_income_coverage_confirmed",
    help: "Gross taxable interest/dividends before nil-rate allowances. UK trading/property require externally determined nonnegative taxable profit and assessment year. Exempt income requires a reason (e.g. ISA); savings/dividend allowances are not exemptions. Stream IDs identify every underlying stream, including consolidated totals, to detect duplicates. Foreign, trust and generic other income are unsupported.",
    initial: {
      money: dated,
      category: "interest",
      basis: "dated",
      coverage_ids: [],
      treatment: "unknown",
      treatment_confirmed: null,
      allocation_confirmed: false,
      assessment_year: null,
      exemption_reason: null,
    },
    fields: [
      money,
      select("category", "Income category", [
        "interest",
        "dividends",
        "uk_trading",
        "uk_property",
        "other",
      ]),
      select("basis", "Allocation basis", ["dated", "tax_year"]),
      f("coverage_ids", "Covered income stream IDs (comma separated)", "ids"),
      select("treatment", "Tax treatment", ["unknown", "taxable", "exempt"]),
      f("treatment_confirmed", "Supported treatment confirmed", "tri"),
      f(
        "allocation_confirmed",
        "Taxable date / assessment allocation confirmed",
        "bool",
      ),
      f(
        "assessment_year",
        "Assessment tax year start (profit / year totals)",
        "integer",
      ),
      f("exemption_reason", "Exemption reason (if exempt)"),
    ],
  },
];
export const configuration: Field[] = [
  f("start_year", "Tax year starting year", "integer"),
  select("jurisdiction", "Income tax jurisdiction", [
    "england",
    "northern_ireland",
    "scotland",
    "wales",
  ]),
  f(
    "standard_treatment",
    "Full-year UK residence and standard Personal Allowance eligibility",
    "tri",
  ),
  f("target_gbp", "ANI target GBP (blank = no target)", "money"),
];
export const initialInputs: RecordValue = {
  start_year: 2026,
  jurisdiction: "england",
  standard_treatment: null,
  target_gbp: "100000",
  ...Object.fromEntries(sections.map((s) => [s.key, []])),
  ...Object.fromEntries(
    sections.filter((s) => s.coverage).map((s) => [s.coverage!, false]),
  ),
};

export const optionLabels: Record<string, string> = {
  england: "England",
  northern_ireland: "Northern Ireland",
  scotland: "Scotland (unsupported)",
  wales: "Wales (unsupported)",
  actual: "Actual — confirmed evidence",
  forecast: "Forecast — assumption",
  unknown: "Unknown",
  unknown_date: "Reference date only — taxable date unknown",
  payment_date: "Payment date (including payment on account)",
  confirmed_receipt: "Confirmed taxable receipt date",
  unconfirmed_entitlement: "Entitlement timing not confirmed",
  before_reductions: "Before payroll pension reductions",
  after_reductions: "After payroll pension reductions",
  salary_sacrifice: "Salary sacrifice",
  net_pay: "Net pay",
  relief_at_source: "Relief at source",
  gross_pension: "Gross pension without prior relief",
  gift_aid: "Gift Aid donation",
  employer: "Ordinary employer pension funding (evidence only)",
  annual_taxable: "Annual taxable value (calendar-day forecast)",
  payrolled: "Actual taxable payroll amount",
  p11d: "Actual P11D taxable amount",
  full_pay: "Full remaining eligible pay",
  stated_amount: "Stated eligible GBP amount",
  apply: "Apply this reduction once",
  reflected: "Already reflected in taxable payroll",
  dated: "Dated taxable receipt",
  tax_year: "Total allocated to assessment tax year",
  uk_trading: "UK trading taxable profit",
  uk_property: "UK property taxable profit",
  other: "Other (unsupported)",
};
