import type { RecordValue } from "./inputs";
export type ExactGBP = {
  numerator: string;
  denominator: string;
  display_gbp: string;
};
export type FieldError = { field: string; message: string };
export type AniResult = {
  status: string;
  ani_gbp: ExactGBP | null;
  personal_allowance_gbp: ExactGBP | null;
  headroom_gbp: ExactGBP | null;
  net_income_gbp: ExactGBP | null;
  taxable_income_gbp: ExactGBP | null;
  rounding_discrepancy_gbp: ExactGBP | null;
  rules: Record<string, unknown> | null;
  rows: {
    key: string;
    amount_gbp: ExactGBP | null;
    status: string;
    explanation: string;
    evidence_path: string;
  }[];
  warnings: FieldError[];
  assumptions: string[];
  source_urls: string[];
  sources_verified_on: string;
  [key: string]: unknown;
};
export async function calculate(
  inputs: RecordValue,
): Promise<AniResult | { errors: FieldError[] }> {
  const response = await fetch("/api/calculate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(inputs),
  });
  if (response.status === 422)
    return response.json() as Promise<{ errors: FieldError[] }>;
  if (!response.ok) throw new Error("Calculation unavailable");
  return response.json() as Promise<AniResult>;
}
