// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "./App";

let root: Root | undefined;

afterEach(async () => {
  await act(async () => root?.unmount());
  document.body.replaceChildren();
  vi.unstubAllGlobals();
});

test.each([
  [{ status: "ok" }, "Local API connected."],
  [{ status: "unexpected" }, "Local API unavailable."],
])("renders the shell and handles health payload %j", async (payload, message) => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const fetchHealth = vi.fn().mockResolvedValue(Response.json(payload));
  vi.stubGlobal("fetch", fetchHealth);
  root = createRoot(document.body);

  await act(async () => root?.render(<App />));

  expect(document.querySelector("main h1")?.textContent).toBe("Vestor");
  expect(document.querySelector("main")?.textContent).toContain("Data is not saved.");
  expect(document.querySelector('[role="status"]')?.textContent).toBe(message);
  expect(fetchHealth).toHaveBeenCalledWith("/api/health");
});
