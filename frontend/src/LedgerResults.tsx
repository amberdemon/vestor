import type { FieldError, M2Result } from "./api";
import { Evidence, gbp, words } from "./evidence";

function Warnings({ warnings }: { warnings: FieldError[] }) {
  if (!warnings.length) return null;
  return <ul className="ledger-warnings">
    {warnings.map((warning, index) => <li key={index}>
      <strong>{words(warning.field)}</strong> · {warning.message}
    </li>)}
  </ul>;
}

function SourceEvidence({ label, value }: { label: string; value: unknown }) {
  return <details><summary>{label}</summary><Evidence value={value} /></details>;
}

export function LedgerResults({ result }: { result: M2Result }) {
  const { ledger, share_gains: shares, annual_cgt: annual, settlement } = result;
  return <>
    <section aria-labelledby="ledger-results-heading" className="results">
      <h2 id="ledger-results-heading">RSU and share ledger</h2>
      <p>Ledger {words(ledger.evidence.status)} · share matching {words(shares.status)} · rules {shares.priority.rule_version}</p>
      <Warnings warnings={ledger.evidence.warnings} />
      <Warnings warnings={shares.warnings} />
      <h3>Gross RSU employment income</h3>
      {result.vests.length ? result.vests.map((row) => {
        const { source, charge_on: chargeDate } = row.source.vest;
        return <details key={source.event_id}>
          <summary>{source.event_id} · {chargeDate ?? "Unknown charge date"} · {source.source_status}</summary>
          <p>Gross taxable income {gbp(row.employment_gbp)} ({words(row.employment_status)})</p>
          <p>Estimated or confirmed acquisition basis {gbp(row.basis_gbp)} ({words(row.basis_status)})</p>
          {row.payroll_difference_gbp && <p>Payroll GBP less the FX model {gbp(row.payroll_difference_gbp)}</p>}
          <p>Included in payroll {row.source.included_in_payroll === null ? "Unknown" : row.source.included_in_payroll ? "Yes" : "No"}</p>
          <Evidence value={row} />
        </details>;
      }) : <p>No share vests supplied.</p>}
      <h3>Disposals and matching</h3>
      {shares.gains.length ? shares.gains.map((row) => {
        const { sale, tax_year_start: year } = row.disposal;
        return <details key={sale.source.event_id} className="disposal-result">
          <summary>{sale.source.event_id} · {sale.trade_on ?? "Unknown trade date"} · {words(sale.purpose)}
            <strong data-testid="disposal-gain">{gbp(row.gain_gbp)}</strong>
            <span className="badge">{words(row.status)}</span>
          </summary>
          <p>{sale.source.source_status} · {sale.quantity ?? "Unknown"} shares · disposal tax year {year ?? "unknown"}</p>
          {sale.vest_id && <p>Linked vest {sale.vest_id}</p>}
          {row.disposal.withholding_ids.length > 0 && <p>Remittance evidence {row.disposal.withholding_ids.join(", ")}</p>}
          <dl className="evidence">
            <div><dt>Gross proceeds</dt><dd>{gbp(row.disposal.gross_gbp)}</dd></div>
            <div><dt>Eligible selling expenses</dt><dd>{gbp(row.disposal.eligible_fees_gbp)}</dd></div>
            <div><dt>Net tax proceeds</dt><dd>{gbp(row.disposal.net_tax_proceeds_gbp)}</dd></div>
            <div><dt>Total matched basis</dt><dd data-testid="matched-basis">{gbp(row.matched_basis_gbp)}</dd></div>
          </dl>
          <Warnings warnings={row.warnings} />
          {row.priority_segments.map((segment, index) => <p key={index}>
            {words(segment.rule)} · {segment.acquisition_id} · {segment.acquired_on} · {gbp(segment.basis_gbp)}
          </p>)}
          {row.pool_movement && <p>Section 104 pool basis {gbp(row.pool_movement.basis_gbp)}</p>}
          <SourceEvidence label="Exact matching and disposal evidence" value={row} />
        </details>;
      }) : <p>No disposal gains available. See the source ledger for the submitted records.</p>}
      <h3>Section 104 pool movements</h3>
      {shares.pool_movements.map((movement) => <details key={movement.source_id}>
        <summary>{movement.on} · {words(movement.kind)} · {movement.source_id}</summary>
        <p>Remaining shares {movement.after.quantity.numerator}/{movement.after.quantity.denominator} ·
          allowable cost {gbp(movement.after.cost_gbp)} · {words(movement.status)}</p>
        <Evidence value={movement} />
      </details>)}
      <h3>Dated exchange rates</h3>
      {result.rates.map((row) => <details key={row.source.event_id}>
        <summary>{row.source.event_id} · {row.on ?? "Unknown date"} · {words(row.purpose)}</summary>
        <p>{row.gbp_per_usd ?? "Unknown"} GBP per USD · {row.source.source_status} · {row.source.source_note}</p>
        <Evidence value={row} />
      </details>)}
      <SourceEvidence label="Acquisition valuations" value={result.acquisitions} />
      <SourceEvidence label="Original ledger records and replacements" value={{
        records: ledger.evidence.records, replacements: ledger.evidence.replacements,
      }} />
    </section>
    <section aria-labelledby="annual-cgt-heading" className="results">
      <h2 id="annual-cgt-heading">Qualified annual CGT estimate</h2>
      <p>{words(annual.status)}{annual.rules ? ` · rules ${annual.rules.version}` : ""}</p>
      <p>Known share gains {gbp(annual.known_share_gains_gbp)} · known share losses {gbp(annual.known_share_losses_gbp)}</p>
      <p className="ledger-total" data-testid="annual-cgt">{gbp(annual.estimate?.tax_gbp ?? null)}</p>
      <Warnings warnings={annual.warnings} />
      {annual.estimate && <SourceEvidence label="Exemption, losses and rate bands" value={annual.estimate} />}
    </section>
    <section aria-labelledby="settlement-heading" className="results">
      <h2 id="settlement-heading">Payroll withholding and broker cash</h2>
      <p>Payroll evidence {words(settlement.payroll_status)} · broker cash evidence {words(settlement.cash_status)}</p>
      <Warnings warnings={settlement.payroll_warnings} />
      <Warnings warnings={settlement.cash_warnings} />
      {settlement.transfers.map((row) => <details key={row.source.source.event_id}>
        <summary>{row.source.source.event_id} · {row.source.received_on ?? "Unknown receipt date"} · {words(row.status)}</summary>
        <p>Observed GBP received {gbp(row.actual_received_gbp)}</p>
        <Evidence value={row} />
      </details>)}
      <SourceEvidence label="Payroll liabilities, payments and reported balances" value={settlement.payroll} />
      <SourceEvidence label="Broker balances and cover remittances" value={{
        balances: settlement.balances, cover_cash: settlement.cover_cash,
      }} />
    </section>
  </>;
}
