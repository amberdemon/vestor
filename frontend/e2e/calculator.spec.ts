import { test, expect, type Page } from "@playwright/test";

// All browser evidence is fictional. Use controls, never inject calculator state.
async function set(
  page: Page,
  path: string,
  value: string | boolean | string[],
) {
  const control = page.locator(`[id="inputs.${path}"]`);
  if (typeof value === "boolean") await control.setChecked(value);
  else if (await control.evaluate((el) => el.tagName === "SELECT"))
    await control.selectOption(String(value));
  else await control.fill(Array.isArray(value) ? value.join(", ") : value);
}
const titles: Record<string, string> = {
  salary_periods: "salary periods",
  salary_payments: "dated payroll payments",
  bonuses: "bonus events",
  payroll_reductions: "payroll pension reductions",
  adjustments: "personal pensions, gift aid & employer funding",
  benefits: "benefits & renewals",
  rsu_events: "rsu vest employment income",
  other_income: "interest, dividends & other income",
};
async function add(
  page: Page,
  key: string,
  index: number,
  values: Record<string, string | boolean | string[]>,
) {
  await page
    .getByRole("button", { name: `Add ${titles[key]} entry`, exact: true })
    .click();
  for (const [name, value] of Object.entries(values))
    await set(page, `${key}.${index}.${name}`, value);
}
async function base(page: Page, salary = "80000") {
  await page.goto("/");
  await page
    .getByLabel(
      "Full-year UK residence and standard Personal Allowance eligibility",
    )
    .selectOption("true");
  for (const checkbox of await page
    .getByRole("checkbox", { name: /I confirm all/ })
    .all())
    await checkbox.check();
  await add(page, "salary_periods", 0, {
    annual_gbp: salary,
    source_status: "forecast",
    source_note: "Synthetic annual salary",
  });
  return page.locator('[id="inputs.salary_periods.0.period_id"]').inputValue();
}
async function compute(page: Page, ani: string, allowance = "£12,570.00") {
  await page
    .getByRole("button", { name: "Calculate ANI", exact: true })
    .click();
  await expect(page.getByTestId("ani")).toHaveText(ani);
  await expect(page.getByTestId("allowance")).toHaveText(allowance);
}
const dated = (amount: string, date = "2027-04-05", status = "forecast") => ({
  "money.amount_gbp": amount,
  "money.on": date,
  "money.source_status": status,
  "money.source_note": "Synthetic dated evidence",
});

test("F1 salary sacrifice, keyboard navigation, privacy and unsaved refresh", async ({
  page,
}, info) => {
  const external: string[] = [];
  page.on("request", (request) => {
    if (
      new URL(request.url()).origin !==
      new URL(process.env.VESTOR_URL ?? "http://127.0.0.1:8000").origin
    )
      external.push(request.url());
  });
  const id = await base(page);
  await add(page, "payroll_reductions", 0, {
    pay_id: id,
    source_status: "forecast",
    source_note: "Synthetic valid election",
    qualifies: "true",
    percent: "2",
    base: "full_pay",
    elected_on: "2026-04-01",
    effective_on: "2026-04-06",
    through: "2027-04-05",
  });
  await page
    .getByRole("button", { name: "Calculate ANI", exact: true })
    .focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("ani")).toHaveText("£78,400.00");
  await expect(page.getByTestId("headroom")).toHaveText("£21,600.00");
  await page
    .locator("summary")
    .filter({ hasText: "taxable salary" })
    .first()
    .click();
  await expect(
    page.getByText(
      "Salary isolated from payroll components, after payroll reductions.",
    ),
  ).toBeVisible();
  await page
    .getByText("Rules, dates, assumptions & rounding", { exact: true })
    .click();
  await expect(
    page.getByText("uk-eng-ni-2026-27-v1", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("heading", { name: "Your calculation", exact: true })
    .scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("f1-result.png") });
  expect(external).toEqual([]);
  await page.reload();
  await expect(page.getByTestId("ani")).toHaveCount(0);
  await expect(
    page.getByText("Not saved — data lost on refresh.", { exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(() => ({
      local: localStorage.length,
      session: sessionStorage.length,
    })),
  ).toEqual({ local: 0, session: 0 });
});

test("F2 bonus and valid prospective sacrifice recompute from backend", async ({
  page,
}) => {
  await base(page, "95000");
  await add(page, "bonuses", 0, {
    ...dated("10000", "2026-12-01"),
    timing: "confirmed_receipt",
    basis: "before_reductions",
  });
  await compute(page, "£105,000.00", "£10,070.00");
  const bonus = await page
    .locator('[id="inputs.bonuses.0.money.event_id"]')
    .inputValue();
  await add(page, "payroll_reductions", 0, {
    pay_id: bonus,
    source_status: "forecast",
    source_note: "Synthetic bonus election",
    qualifies: "true",
    fixed_gbp: "5500",
    base: "full_pay",
    elected_on: "2026-11-01",
    effective_on: "2026-11-02",
  });
  await expect(page.getByTestId("ani")).toHaveCount(0);
  await compute(page, "£99,500.00");
});

test("mixed payroll, net pay, benefit renewals, RSU replacement, other income, RAS and Gift Aid", async ({
  page,
}, info) => {
  const salary = await base(page);
  await add(page, "salary_payments", 0, {
    "pay.money.amount_gbp": "80000",
    "pay.money.source_status": "actual",
    "pay.money.source_note": "Synthetic payroll total",
    "pay.money.on": "2027-04-05",
    "pay.timing": "confirmed_receipt",
    "pay.basis": "before_reductions",
    replaces_period_ids: [salary],
  });
  await page
    .getByRole("button", { name: "Confirm no included components" })
    .click();
  const payroll = await page
    .locator('[id="inputs.salary_payments.0.pay.money.event_id"]')
    .inputValue();
  await add(page, "payroll_reductions", 0, {
    pay_id: payroll,
    method: "net_pay",
    fixed_gbp: "1000",
    base: "full_pay",
    deducted_on: "2027-04-05",
    source_status: "actual",
    source_note: "Synthetic deduction",
    qualifies: "true",
  });
  await add(page, "benefits", 0, {
    benefit_id: "medical",
    category: "Medical",
    "dates.end": "2026-10-31",
    taxability: "yes",
    source_status: "forecast",
    source_note: "Synthetic taxable forecast",
    basis: "annual_taxable",
    taxable_gbp: "2400",
    daily_apportionment_confirmed: true,
    included_in_payroll: "false",
  });
  await add(page, "benefits", 1, {
    benefit_id: "medical",
    category: "Medical",
    "dates.start": "2026-11-01",
    taxability: "yes",
    source_status: "forecast",
    source_note: "Synthetic renewal",
    basis: "annual_taxable",
    taxable_gbp: "3000",
    daily_apportionment_confirmed: true,
    included_in_payroll: "false",
  });
  await add(page, "rsu_events", 0, {
    ...dated("3500"),
    charge_date_confirmed: true,
    supported_award: "true",
    included_in_payroll: "false",
  });
  const forecast = await page
    .locator('[id="inputs.rsu_events.0.money.event_id"]')
    .inputValue();
  await add(page, "rsu_events", 1, {
    ...dated("4000", "2027-04-05", "actual"),
    "money.replaces_forecast_id": forecast,
    charge_date_confirmed: true,
    supported_award: "true",
    included_in_payroll: "false",
  });
  for (const [index, category, amount] of [
    [0, "interest", "1000"],
    [1, "dividends", "500"],
  ] as const)
    await add(page, "other_income", index, {
      ...dated(amount),
      category,
      coverage_ids: [category],
      treatment: "taxable",
      treatment_confirmed: "true",
      allocation_confirmed: true,
    });
  for (const [index, kind] of [
    [0, "relief_at_source"],
    [1, "gift_aid"],
  ] as const)
    await add(page, "adjustments", index, {
      ...dated("800"),
      kind,
      qualifies: "true",
      effective_date_known: true,
    });
  await compute(page, "£85,156.44");
  await page.locator("summary").filter({ hasText: "benefits" }).first().click();
  await page
    .getByRole("heading", { name: "Your calculation", exact: true })
    .scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("mixed-result.png") });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("unsupported scope and unknown benefits never display confident totals", async ({
  page,
}) => {
  await base(page);
  await set(page, "jurisdiction", "scotland");
  await compute(page, "Unavailable", "Unavailable");
  await expect(
    page.getByText(
      "jurisdiction: Only England and Northern Ireland rules are supported.",
    ),
  ).toBeVisible();
  await set(page, "jurisdiction", "england");
  await add(page, "benefits", 0, {
    category: "Medical",
    source_status: "forecast",
    source_note: "Synthetic premium only",
    annual_premium_gbp: "1200",
  });
  await compute(page, "Unavailable", "Unavailable");
  await expect(
    page.getByRole("heading", {
      name: "Warnings — resolve before relying on totals",
    }),
  ).toBeVisible();
});

test("out-of-range year and source-ID semantic errors have accessible working targets", async ({
  page,
}) => {
  const salary = await base(page);
  await set(page, "start_year", "10000");
  await page
    .getByRole("button", { name: "Calculate ANI", exact: true })
    .click();
  const year = page.getByLabel("Tax year starting year");
  await expect(year).toHaveAttribute("aria-invalid", "true");
  await page.locator('[role=alert] a[href="#inputs.start_year"]').click();
  await expect(year).toBeFocused();
  await set(page, "start_year", "2026");
  await add(page, "payroll_reductions", 0, {
    pay_id: salary,
    source_status: "forecast",
    source_note: "Synthetic excess election",
    qualifies: "true",
    fixed_gbp: "90000",
    base: "full_pay",
    elected_on: "2026-04-01",
    effective_on: "2026-04-06",
    through: "2027-04-05",
  });
  await page
    .getByRole("button", { name: "Calculate ANI", exact: true })
    .click();
  const source = page.getByLabel("Reduction ID", { exact: true });
  await expect(source).toHaveAttribute("aria-invalid", "true");
  await page
    .locator('[role=alert] a[href="#inputs.payroll_reductions.0.reduction_id"]')
    .click();
  await expect(source).toBeFocused();
  await expect(page.getByTestId("ani")).toHaveCount(0);
});
