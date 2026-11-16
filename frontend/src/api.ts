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
async function calculateAt<T>(
  path: string,
  inputs: RecordValue,
): Promise<T | { errors: FieldError[] }> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(inputs),
  });
  if (response.status === 422)
    return response.json() as Promise<{ errors: FieldError[] }>;
  if (!response.ok) throw new Error("Calculation unavailable");
  return response.json() as Promise<T>;
}
export const calculate = (inputs: RecordValue) => calculateAt<AniResult>("/api/calculate", inputs);


export type M2Result = {
  version: string;
  ani: AniResult;
  rates: LedgerRate[];
  vests: VestResult[];
  ledger: {
    evidence: { status: string; warnings: FieldError[]; records: unknown[]; replacements: string[][] };
    disposals: DisposalResult[];
  };
  acquisitions: unknown[];
  share_gains: {
    status: string; warnings: FieldError[]; gains: GainResult[];
    pool_movements: PoolMovement[]; priority: { rule_version: string };
  };
  annual_cgt: {
    status: string; warnings: FieldError[]; rules: { version: string } | null;
    known_share_gains_gbp: ExactGBP; known_share_losses_gbp: ExactGBP;
    estimate: { tax_gbp: ExactGBP; taxable_gains_gbp: ExactGBP } | null;
  };
  settlement: {
    payroll_status: string; cash_status: string; payroll_warnings: FieldError[]; cash_warnings: FieldError[];
    payroll: unknown[]; transfers: TransferResult[]; balances: unknown[]; cover_cash: unknown[];
  };
};

type LedgerSource = { event_id: string; source_status: string; source_note: string };
export type LedgerRate = { source: LedgerSource; on: string | null; purpose: string; gbp_per_usd: string | null };
type VestResult = {
  source: { vest: { source: LedgerSource; charge_on: string | null }; included_in_payroll: boolean | null };
  employment_gbp: ExactGBP | null; employment_status: string; basis_gbp: ExactGBP | null; basis_status: string;
  payroll_difference_gbp: ExactGBP | null;
};
type DisposalResult = {
  sale: { source: LedgerSource; trade_on: string | null; purpose: string; vest_id: string | null; quantity: string | null };
  tax_year_start: number | null; gross_gbp: ExactGBP | null; eligible_fees_gbp: ExactGBP | null;
  net_tax_proceeds_gbp: ExactGBP | null; net_broker_proceeds_gbp: ExactGBP | null;
  withholding_ids: string[]; status: string; warnings: FieldError[];
};
type GainResult = {
  disposal: DisposalResult; status: string; gain_gbp: ExactGBP | null; matched_basis_gbp: ExactGBP | null;
  priority_segments: { acquisition_id: string; acquired_on: string; rule: string; basis_gbp: ExactGBP | null }[];
  pool_movement: PoolMovement | null; warnings: FieldError[];
};
type PoolMovement = {
  source_id: string; on: string; kind: string; status: string;
  basis_gbp: ExactGBP | null;
  after: { quantity: { numerator: string; denominator: string }; cost_gbp: ExactGBP | null };
};
type TransferResult = {
  source: { source: LedgerSource; received_on: string | null };
  actual_received_gbp: ExactGBP | null; status: string;
};
export const calculateM2 = (inputs: RecordValue) => calculateAt<M2Result>("/api/v2/calculate", inputs);
