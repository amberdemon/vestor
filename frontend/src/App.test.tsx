// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, test, vi } from "vitest";
import { App, validate } from "./App";
import { configuration, sections } from "./inputs";
let root: Root | undefined;
afterEach(async () => {
  await act(async () => root?.unmount());
  document.body.replaceChildren();
  vi.unstubAllGlobals();
});
async function mount() {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  root = createRoot(document.body);
  await act(async () => root?.render(<App />));
}
async function click(text: string) {
  const button = [...document.querySelectorAll("button")].find(
    (b) => b.textContent === text,
  )!;
  await act(async () => button.click());
}
function input(id: string) {
  return document.getElementById(id) as HTMLInputElement;
}
async function fill(id: string, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input(id), value);
    input(id).dispatchEvent(new Event("input", { bubbles: true }));
  });
}

test("every input is labelled; add/remove buttons are keyboard focusable and no network on load", async () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  await mount();
  await click("Add salary periods entry");
  for (const control of document.querySelectorAll("input,select"))
    expect((control as HTMLInputElement).labels?.length).toBeGreaterThan(0);
  expect(input("inputs.salary_periods.0.period_id").value).toBe(
    "salary-periods-1",
  );
  input("inputs.salary_periods.0.annual_gbp").focus();
  expect(document.activeElement?.id).toBe("inputs.salary_periods.0.annual_gbp");
  await click("Remove entry 1 from Salary periods");
  expect(
    document.getElementById("inputs.salary_periods.0.annual_gbp"),
  ).toBeNull();
  expect(document.body.textContent).toContain(
    "Not saved — data lost on refresh.",
  );
  expect(fetch).not.toHaveBeenCalled();
});

test.each(["1e3", "-1", "12.345", "NaN", "1,000"])(
  "rejects invalid decimal %s before request with linked errors",
  async (value) => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    await mount();
    await fill("inputs.target_gbp", value);
    await click("Calculate ANI");
    expect(fetch).not.toHaveBeenCalled();
    expect(input("inputs.target_gbp").getAttribute("aria-invalid")).toBe(
      "true",
    );
    expect(document.querySelector("[role=alert] a")?.getAttribute("href")).toBe(
      "#inputs.target_gbp",
    );
  },
);

test("server failure preserves unsaved inputs and does not echo response data", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValue(new Error("PRIVATE RESPONSE")),
  );
  await mount();
  await fill("inputs.target_gbp", "99999.99");
  await click("Calculate ANI");
  expect(input("inputs.target_gbp").value).toBe("99999.99");
  expect(document.body.textContent).toContain("Your entries remain here");
  expect(document.body.textContent).not.toContain("PRIVATE RESPONSE");
});

test("status changes preserve stable source identity in submitted wire data", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue(
      Response.json(
        { errors: [{ field: "inputs", message: "Resolve inputs." }] },
        { status: 422 },
      ),
    );
  vi.stubGlobal("fetch", fetch);
  await mount();
  await click("Add rsu vest employment income entry");
  const id = "inputs.rsu_events.0.money.event_id";
  const original = input(id).value;
  const select = document.getElementById(
    "inputs.rsu_events.0.money.source_status",
  ) as HTMLSelectElement;
  await act(async () => {
    select.value = "actual";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await click("Calculate ANI");
  const payload = JSON.parse(fetch.mock.calls[0][1].body);
  expect(payload.rsu_events[0].money.event_id).toBe(original);
  expect(payload.rsu_events[0].money.source_status).toBe("actual");
});

test("validation keeps exact large decimal strings and four-place percentages", () => {
  expect(
    validate(
      configuration,
      { target_gbp: "99999999999999999999.99" },
      "inputs",
    ),
  ).toEqual([]);
  expect(
    validate(
      sections.find((s) => s.key === "payroll_reductions")!.fields,
      { percent: "2.1234" },
      "inputs",
    ),
  ).toEqual([]);
});

test("uses exact backend amounts and clears stale results on edit", async () => {
  const amount = {
    numerator: "9999999999999999999999",
    denominator: "100",
    display_gbp: "99999999999999999999.99",
  };
  const payload = {
    status: "estimated",
    ani_gbp: amount,
    personal_allowance_gbp: null,
    headroom_gbp: null,
    net_income_gbp: amount,
    taxable_income_gbp: amount,
    rounding_discrepancy_gbp: {
      numerator: "0",
      denominator: "1",
      display_gbp: "0.00",
    },
    warnings: [],
    rows: [],
    rules: { version: "test-rules" },
    assumptions: [],
    source_urls: [],
    sources_verified_on: "2026-11-08",
    inputs: {},
  };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(payload)));
  await mount();
  await click("Calculate ANI");
  expect(document.querySelector("[data-testid=ani]")?.textContent).toBe(
    "£99,999,999,999,999,999,999.99",
  );
  await fill("inputs.target_gbp", "1");
  expect(document.querySelector("[data-testid=ani]")).toBeNull();
});
