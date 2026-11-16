import { expect, test, type Page, type TestInfo } from "@playwright/test";

type Fields = Record<string, string | boolean>;
const identity = {
  "security.issuer_id": "synthetic-co",
  "security.share_class": "ordinary-A",
  "security.owner_id": "synthetic-owner",
  "security.ordinary_listed": "true",
};
const source = { "source.source_status": "actual", "source.source_note": "Synthetic source evidence" };

function field(page: Page, path: string) {
  return page.locator(`[id="inputs.${path}"]`);
}
async function edit(page: Page, prefix: string, values: Fields) {
  for (const [key, value] of Object.entries(values)) {
    const control = field(page, prefix ? `${prefix}.${key}` : key);
    if (typeof value === "boolean") await control.setChecked(value);
    else if (await control.evaluate((element) => element.tagName === "SELECT")) await control.selectOption(value);
    else await control.fill(value);
  }
}
const addLabels: Record<string, string> = {
  opening_holdings: "Add opening holding",
  grants: "Add grant",
  vests: "Add vest",
  sales: "Add sale",
  rates: "Add FX rate",
  fees: "Add fee",
  withholding_links: "Add remittance link",
  transfers: "Add transfer",
};
async function add(page: Page, kind: string, index: number, values: Fields) {
  const section = field(page, kind);
  if (await section.getAttribute("open") === null) await section.locator("summary").click();
  await page.getByRole("button", { name: addLabels[kind], exact: true }).click();
  await edit(page, `${kind}.${index}`, values);
  return field(page, `${kind}.${index}.${kind === "vests" ? "vest." : ""}source.event_id`).inputValue();
}
async function initial(page: Page, openQty: string, openCost: string) {
  await page.goto("/");
  await edit(page, "", { standard_treatment: "true" });
  for (const checkbox of await page.getByRole("checkbox", { name: /I confirm all/ }).all()) await checkbox.check();
  await page.getByLabel("Include share ledger and CGT").check();
  await page.getByRole("button", { name: "Add salary periods entry" }).click();
  await edit(page, "salary_periods.0", {
    annual_gbp: "80000", source_status: "forecast", source_note: "Synthetic salary",
  });
  await add(page, "opening_holdings", 0, {
    ...source, ...identity, as_of: "2026-04-05", quantity: openQty, cost_gbp: openCost,
    history_confirmed: true, coverage_through: "2027-05-15",
  });
}
async function addVest(page: Page, date: string, qty: string, price: string, gbp: string, basisFX?: string) {
  const grant = await add(page, "grants", 0, { ...source, ...identity, awarded_on: "2025-06-01", treatment: "ordinary_rsu" });
  const vestFields: Fields = {
    ...Object.fromEntries(Object.entries({ ...source, ...identity }).map(([key, value]) => [`vest.${key}`, value])),
    "vest.grant_id": grant, "vest.vested_on": date, "vest.acquired_on": date, "vest.charge_on": date,
    "vest.quantity": qty, "vest.fmv_usd_per_share": price, "vest.uk_resident": "true",
    confirmed_payroll_gbp: gbp, included_in_payroll: "false", basis_method: "market_value",
  };
  if (basisFX) {
    vestFields["vest.basis_rate_id"] = basisFX;
    vestFields.acquisition_fees_confirmed = true;
  } else {
    vestFields.confirmed_basis_gbp = gbp;
  }
  return add(page, "vests", 0, vestFields);
}
async function sale(page: Page, index: number, date: string, quantity: string, price: string, options: Fields = {}) {
  return add(page, "sales", index, {
    ...source, ...identity, trade_on: date, quantity, price_per_share: price, uk_resident: "true",
    fees_confirmed: true, ...options,
  });
}
async function rate(page: Page, index: number, date: string, value: string, purpose: string) {
  return add(page, "rates", index, { ...source, on: date, gbp_per_usd: value, purpose });
}
async function calculate(page: Page) {
  await page.getByRole("button", { name: "Calculate ANI and shares" }).click();
  await expect(page.getByRole("heading", { name: "Your calculation" })).toBeFocused();
}
async function screenshot(page: Page, info: TestInfo, name: string) {
  const section = page.getByRole("region", { name: "RSU and share ledger" });
  await section.screenshot({ path: info.outputPath(`${name}.png`) });
}

test("F4 separates gross vest income from a £90 share gain and incomplete annual CGT", async ({ page }, info) => {
  const requests: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  await initial(page, "0", "0");
  await addVest(page, "2026-05-10", "100", "10", "800");
  const quote = await rate(page, 0, "2026-06-20", "0.75", "disposal_proceeds");
  const saleId = await sale(page, 0, "2026-06-20", "100", "12", { currency: "USD", rate_id: quote });
  await add(page, "fees", 0, {
    ...source, transaction_id: saleId, on: "2026-06-20", amount: "10", category: "eligible_dealing",
  });

  const price = field(page, "sales.0.price_per_share");
  await price.fill("-1");
  await price.press("Enter");
  await expect(page.getByRole("alert")).toBeFocused();
  await page.getByRole("alert").getByRole("link", { name: /price_per_share/ }).click();
  await expect(price).toBeFocused();
  await expect(price).toHaveAttribute("aria-invalid", "true");
  await price.fill("12");
  await calculate(page);

  await expect(page.getByTestId("ani")).toHaveText("£80,800.00");
  await expect(page.getByTestId("disposal-gain")).toHaveText("£90.00");
  await expect(page.getByTestId("annual-cgt")).toHaveText("Unavailable");
  await page.locator(".disposal-result summary").first().press("Enter");
  await expect(page.getByTestId("matched-basis")).toHaveText("£800.00");
  await expect(page.getByText("Section 104 pool basis £800.00", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await screenshot(page, info, "f4-ledger");
  const annual = field(page, "annual");
  await annual.locator("summary").click();
  await page.getByLabel("Include other gains and losses").check();
  await page.getByLabel("Include tax band evidence").check();
  await edit(page, "annual", {
    ordinary_treatment: "true", eligible_for_aea: "true", share_coverage_confirmed: true,
    "capital.source.source_status": "actual", "capital.source.source_note": "Synthetic known absence",
    "capital.other_gains_gbp": "0", "capital.other_current_losses_gbp": "0",
    "capital.available_brought_forward_gbp": "0",
    "band.source.source_status": "actual", "band.source.source_note": "Synthetic confirmed unused band",
    "band.unused_basic_band_gbp": "0",
  });
  const execution = await rate(page, 1, "2026-07-01", "0.8", "cash_settlement");
  await add(page, "transfers", 0, {
    ...source, transaction_ref: "synthetic-wire", executed_on: "2026-07-01", received_on: "2026-07-02",
    sent_usd: "100", fee_usd: "2", fee_gbp: "1", received_gbp: "77.40", rate_id: execution,
  });
  await edit(page, "", { payroll_coverage: true, cash_coverage: true });
  await calculate(page);
  await expect(page.getByTestId("annual-cgt")).toHaveText("£0.00");
  await expect(page.getByTestId("disposal-gain")).toHaveText("£90.00");
  const settlement = page.getByRole("region", { name: "Payroll withholding and broker cash" });
  await settlement.locator("summary").first().click();
  await expect(settlement.getByText("Observed GBP received £77.40", { exact: true })).toBeVisible();

  expect(requests.every((url) => new URL(url).origin === new URL(page.url()).origin)).toBe(true);
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0]);
  await page.reload();
  await expect(page.getByLabel("Include share ledger and CGT")).not.toBeChecked();
  await expect(page.getByTestId("disposal-gain")).toHaveCount(0);
});

test("F6 preserves a gain caused only by the difference between dated FX rates", async ({ page }) => {
  await initial(page, "0", "0");
  const buyRate = await rate(page, 0, "2026-05-10", "0.70", "acquisition_basis");
  const sellRate = await rate(page, 1, "2026-06-20", "0.80", "disposal_proceeds");
  await addVest(page, "2026-05-10", "10", "10", "70", buyRate);
  await sale(page, 0, "2026-06-20", "10", "10", { currency: "USD", rate_id: sellRate });
  await calculate(page);
  await expect(page.getByTestId("disposal-gain")).toHaveText("£10.00");
});

for (const crossYear of [false, true]) {
  test(crossYear ? "A 5 April sale sees the 6 April cover and keeps its tax year" : "F5 reserves cover shares before matching the earlier sale",
    async ({ page }, info) => {
      const vestDate = crossYear ? "2027-04-06" : "2026-12-15";
      const saleDate = crossYear ? "2027-04-05" : "2026-11-20";
      await initial(page, "100", "500");
      const vest = await addVest(page, vestDate, "40", "8", "320");
      await sale(page, 0, saleDate, "100", "10");
      const cover = await sale(page, 1, vestDate, "20", "9", { purpose: "sell_to_cover", vest_id: vest });
      await add(page, "withholding_links", 0, { ...source, vest_id: vest, sale_id: cover, remitted_on: vestDate });
      await calculate(page);
      await expect(page.getByTestId("ani")).toHaveText(crossYear ? "£80,000.00" : "£80,320.00");
      await expect(page.getByTestId("disposal-gain")).toHaveText(["£440.00", "£20.00"]);
      await page.locator(".disposal-result > summary").nth(0).click();
      await page.locator(".disposal-result > summary").nth(1).click();
      await expect(page.getByText(/following 30 days · vests-/)).toBeVisible();
      await expect(page.getByText(/same day · vests-/)).toBeVisible();
      await expect(page.getByText(/disposal tax year 2026/).first()).toBeVisible();
      if (crossYear) {
        await expect(page.getByText(/disposal tax year 2027/)).toBeVisible();
        await screenshot(page, info, "cross-year-ledger");
      }
    });
}
