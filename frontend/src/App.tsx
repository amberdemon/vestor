import { useEffect, useRef, useState } from "react";
import {
  calculate,
  calculateM2,
  type AniResult,
  type FieldError,
  type M2Result,
} from "./api";
import {
  configuration,
  initialInputs,
  optionLabels,
  sections,
  type Field,
  type Value,
  type RecordValue,
} from "./inputs";
import { Evidence, gbp, words } from "./evidence";
import {
  annualFields, bandFields, blankFields, capitalFields, initialLedger,
  ledgerSections, settlementCoverage,
} from "./ledgerInputs";
import { LedgerResults } from "./LedgerResults";
function Editor({
  fields,
  value,
  path,
  change,
  errors,
}: {
  fields: Field[];
  value: RecordValue;
  path: string;
  change: (next: RecordValue) => void;
  errors: FieldError[];
}) {
  return (
    <>
      {fields.map((field) => {
        const id = `${path}.${field.key}`,
          current = value[field.key];
        const set = (next: Value) => change({ ...value, [field.key]: next });
        if (field.repeat) {
          const items = (current ?? []) as RecordValue[];
          return (
            <fieldset key={id} id={id} tabIndex={-1}>
              <legend>{field.label}</legend>
              {current === null && (
                <p>
                  Composition unknown. Add components or confirm there are none.
                </p>
              )}
              {items.map((item, i) => (
                <fieldset key={i}>
                  <legend>Component {i + 1}</legend>
                  <Editor
                    fields={field.fields!}
                    value={item}
                    path={`${id}.${i}`}
                    errors={errors}
                    change={(next) =>
                      set(items.map((v, n) => (n === i ? next : v)))
                    }
                  />
                  <button
                    type="button"
                    onClick={() => set(items.filter((_, n) => n !== i))}
                  >
                    Remove component {i + 1}
                  </button>
                </fieldset>
              ))}
              <button
                type="button"
                onClick={() => set([...items, structuredClone(field.initial!)])}
              >
                Add component
              </button>
              {current === null && (
                <button type="button" onClick={() => set([])}>
                  Confirm no included components
                </button>
              )}
            </fieldset>
          );
        }
        if (field.fields)
          return (
            <fieldset key={id} id={id} tabIndex={-1}>
              <legend>{field.label}</legend>
              <Editor
                fields={field.fields}
                value={current as RecordValue}
                path={id}
                errors={errors}
                change={set}
              />
            </fieldset>
          );
        const error = errors.find((e) => e.field === id);
        const props = {
          id,
          "aria-invalid": !!error,
          "aria-describedby": error ? `${id}-error` : undefined,
        };
        let control;
        if (field.type === "bool")
          control = (
            <input
              {...props}
              type="checkbox"
              checked={current === true}
              onChange={(e) => set(e.target.checked)}
            />
          );
        else if (field.type === "tri")
          control = (
            <select
              {...props}
              value={current === null ? "" : String(current)}
              onChange={(e) =>
                set(e.target.value === "" ? null : e.target.value === "true")
              }
            >
              <option value="">Unknown / not confirmed</option>
              <option value="true">Yes</option>
              <option value="false">No</option>
            </select>
          );
        else if (field.options)
          control = (
            <select
              {...props}
              value={String(current ?? "")}
              onChange={(e) => set(e.target.value || null)}
            >
              {field.options.map((v) => (
                <option key={v} value={v}>
                  {v ? (optionLabels[v] ?? words(v)) : "Unknown / not supplied"}
                </option>
              ))}
            </select>
          );
        else
          control = (
            <input
              {...props}
              type={field.type === "date" ? "date" : "text"}
              inputMode={
                field.type === "money" || field.type === "percent" || field.type === "decimal"
                  ? "decimal"
                  : field.type === "integer"
                    ? "numeric"
                    : undefined
              }
              value={
                Array.isArray(current)
                  ? current.join(", ")
                  : String(current ?? "")
              }
              onChange={(e) => {
                const text = e.target.value;
                set(
                  field.type === "ids"
                    ? text.trim()
                      ? text.split(",").map((s) => s.trim())
                      : field.key === "reflected_methods"
                        ? null
                        : []
                    : field.type === "integer"
                      ? text === ""
                        ? null
                        : /^\d+$/.test(text)
                          ? Number(text)
                          : text
                      : text || null,
                );
              }}
            />
          );
        return (
          <div
            className={`field ${field.type === "bool" ? "check" : ""}`}
            key={id}
          >
            <label htmlFor={id}>{field.label}</label>
            {control}
            {error && (
              <p id={`${id}-error`} className="error">
                {error.message}
              </p>
            )}
          </div>
        );
      })}
    </>
  );
}
function inputTargets(
  fields: Field[],
  value: RecordValue,
  path: string,
): string[] {
  return fields.flatMap((field) => {
    const id = `${path}.${field.key}`,
      current = value[field.key];
    return [
      id,
      ...(field.repeat
        ? ((current ?? []) as RecordValue[]).flatMap((row, index) =>
            inputTargets(field.fields!, row, `${id}.${index}`),
          )
        : field.fields
          ? inputTargets(field.fields, current as RecordValue, id)
          : []),
    ];
  });
}
export function validate(
  fields: Field[],
  value: RecordValue,
  path: string,
): FieldError[] {
  return fields.flatMap((field) => {
    const item = value[field.key],
      key = `${path}.${field.key}`;
    if (field.repeat)
      return ((item ?? []) as RecordValue[]).flatMap((row, i) =>
        validate(field.fields!, row, `${key}.${i}`),
      );
    if (field.fields) return validate(field.fields, item as RecordValue, key);
    if (item === undefined || item === null || item === "") return [];
    const pattern =
      field.type === "money"
        ? /^\d+(\.\d{1,2})?$/
        : field.type === "percent"
          ? /^\d+(\.\d{1,4})?$/
          : field.type === "decimal"
            ? /^\d+(\.\d+)?$/
            : null;
    if (field.type === "decimal" && typeof item === "string" && item.replace(".", "").length > 64)
      return [{ field: key, message: "Use at most 64 digits." }];
    if (pattern && (typeof item !== "string" || !pattern.test(item)))
      return [
        {
          field: key,
          message:
            field.type === "decimal" ? "Enter a plain nonnegative decimal."
              : "Enter a plain nonnegative decimal with up to two places for GBP or four for percentages.",
        },
      ];
    if (
      field.type === "percent" &&
      typeof item === "string" &&
      !/^(?:0*\d{1,2}(?:\.\d{1,4})?|0*100(?:\.0{1,4})?)$/.test(item)
    )
      return [{ field: key, message: "Enter a percentage from 0 to 100." }];
    if (
      field.type === "integer" &&
      (typeof item !== "number" || !Number.isSafeInteger(item))
    )
      return [{ field: key, message: "Enter a whole year." }];
    return [];
  });
}
export function App() {
  const [inputs, setInputs] = useState<RecordValue>(
    structuredClone(initialInputs),
  );
  const [result, setResult] = useState<AniResult | null>(null),
    [errors, setErrors] = useState<FieldError[]>([]);
  const [busy, setBusy] = useState(false),
    [message, setMessage] = useState("Enter inputs, then calculate.");
  const [includeLedger, setIncludeLedger] = useState(false);
  const [ledger, setLedger] = useState<RecordValue>(() => structuredClone(initialLedger));
  const [m2Result, setM2Result] = useState<M2Result | null>(null);
  const annual = ledger.annual as RecordValue;
  const activeAnnualFields = [
    ...annualFields,
    ...(annual.capital ? [{ key: "capital", label: "Other gains and losses", fields: capitalFields }] : []),
    ...(annual.band ? [{ key: "band", label: "Tax band evidence", fields: bandFields }] : []),
  ];
  const ledgerFields: Field[] = [
    ...ledgerSections.map((section) => ({ key: section.key, label: section.title, repeat: true, fields: section.fields })),
    { key: "annual", label: "Annual CGT inputs", fields: activeAnnualFields },
    ...settlementCoverage,
  ];
  const sourceNumber = useRef(0);
  function newRecord(section: (typeof sections)[number]): RecordValue {
    const row = structuredClone(section.initial);
    const id = `${section.key.replaceAll("_", "-")}-${++sourceNumber.current}`;
    if ("money" in row) (row.money as RecordValue).event_id = id;
    else if ("pay" in row)
      ((row.pay as RecordValue).money as RecordValue).event_id = id;
    else if ("reduction_id" in row) row.reduction_id = id;
    else row.period_id = id;
    if ("benefit_id" in row) row.benefit_id = id;
    return row;
  }
  const sequence = useRef(0),
    summary = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (errors.length) summary.current?.focus();
  }, [errors]);
  useEffect(() => {
    if (result) document.getElementById("results-heading")?.focus();
  }, [result]);
  function invalidate() {
    sequence.current++;
    setResult(null);
    setM2Result(null);
    setMessage("Inputs changed. Calculate to update results.");
  }
  function edit(next: RecordValue) {
    setInputs(next);
    invalidate();
  }
  function editLedger(next: RecordValue) {
    setLedger(next);
    invalidate();
  }
  function newLedgerRecord(section: (typeof ledgerSections)[number]) {
    const row = blankFields(section.fields);
    const record = (row.vest ?? row) as RecordValue;
    (record.source as RecordValue).event_id = `${section.key.replaceAll("_", "-")}-${++sourceNumber.current}`;
    if (section.key === "rates") row.pair = "GBP/USD";
    return row;
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const invalid = [
      ...validate(configuration, inputs, "inputs"),
      ...sections.flatMap((s) =>
        ((inputs[s.key] ?? []) as RecordValue[]).flatMap((row, i) =>
          validate(s.fields, row, `inputs.${s.key}.${i}`),
        ),
      ),
    ];
    if (includeLedger) invalid.push(...validate(ledgerFields, ledger, "inputs"));
    setErrors(invalid);
    setResult(null);
    setM2Result(null);
    if (invalid.length) {
      setMessage("Check the highlighted fields.");
      return;
    }
    const request = sequence.current;
    setBusy(true);
    setMessage("Calculating locally…");
    try {
      const response = includeLedger ? await calculateM2({ ...ledger, ani: inputs }) : await calculate(inputs);
      if (request !== sequence.current) return;
      if ("errors" in response) {
        setErrors((response.errors as FieldError[]).map(({ field, message }) => ({
          field: field.replace(/^inputs\.ani(?=\.|$)/, "inputs"), message,
        })));
        setMessage("Check the highlighted fields.");
        } else {
        const combined = includeLedger ? response as M2Result : null;
        const ani = combined?.ani ?? response as AniResult;
        setResult(ani);
        setM2Result(combined);
        setMessage(combined ? `Calculation returned. ANI ${ani.status}. CGT ${combined.annual_cgt.status}.`
          : `Calculation ${ani.status}.`);
      }
    } catch {
      if (request === sequence.current) {
        setErrors([
          {
            field: "inputs",
            message:
              "Local calculation unavailable. Your entries remain here; retry when the local service is available.",
          },
        ]);
        setMessage("Calculation unavailable.");
      }
    } finally {
      setBusy(false);
    }
  }
  const targets = new Set([
    ...inputTargets(configuration, inputs, "inputs"),
    ...(includeLedger ? inputTargets(ledgerFields, ledger, "inputs") : []),
    ...sections.flatMap((section) => [
      `inputs.${section.key}`,
      ...(inputs[section.key] as RecordValue[]).flatMap((row, index) =>
        inputTargets(section.fields, row, `inputs.${section.key}.${index}`),
      ),
    ]),
  ]);
  return (
    <main>
      <header>
        <p className="eyebrow">VESTOR · LOCAL COMPENSATION PLANNER</p>
        <h1>Your adjusted net income</h1>
        <p>Plan a UK tax year with a calculation you can inspect.</p>
      </header>
      <aside className="notice">
        <strong>Not saved — data lost on refresh.</strong> Inputs stay in this
        page only. Enable the share ledger below to include RSUs, disposal gains and qualified CGT.
      </aside>
      <form onSubmit={submit} noValidate>
        {errors.length > 0 && (
          <div
            ref={summary}
            tabIndex={-1}
            className="error-summary"
            role="alert"
          >
            <h2>Check your inputs</h2>
            <ul>
              {errors.map((e, i) => (
                <li key={i}>
                  {targets.has(e.field) ? (
                    <a
                      href={`#${e.field}`}
                      onClick={() => document.getElementById(e.field)?.focus()}
                    >
                      {e.field.replace("inputs.", "")}: {e.message}
                    </a>
                  ) : (
                    <span>{e.message}</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
        <section>
          <h2>1. Tax year & target</h2>
          <p>
            Verified scope: 6 April 2026–5 April 2027, England / Northern
            Ireland, full-year UK residence and standard allowance eligibility.
            Other selections return explicit warnings.
          </p>
          <Editor
            fields={configuration}
            value={inputs}
            path="inputs"
            errors={errors}
            change={edit}
          />
        </section>
        {sections.map((section, index) => {
          const rows = inputs[section.key] as RecordValue[];
          return (
            <section
              key={section.key}
              id={`inputs.${section.key}`}
              tabIndex={-1}
            >
              <h2>
                {index + 2}. {section.title}
              </h2>
              <p>{section.help}</p>
              {rows.map((row, i) => (
                <fieldset className="record" key={i}>
                  <legend>
                    {section.title} · entry {i + 1}
                  </legend>
                  <Editor
                    fields={section.fields}
                    value={row}
                    path={`inputs.${section.key}.${i}`}
                    errors={errors}
                    change={(next) =>
                      edit({
                        ...inputs,
                        [section.key]: rows.map((v, n) => (n === i ? next : v)),
                      })
                    }
                  />
                  <button
                    type="button"
                    className="remove"
                    onClick={() =>
                      edit({
                        ...inputs,
                        [section.key]: rows.filter((_, n) => n !== i),
                      })
                    }
                  >
                    Remove entry {i + 1} from {section.title}
                  </button>
                </fieldset>
              ))}
              <button
                type="button"
                onClick={() =>
                  edit({
                    ...inputs,
                    [section.key]: [...rows, newRecord(section)],
                  })
                }
              >
                Add {section.title.toLowerCase()} entry
              </button>
              {section.coverage && (
                <label className="coverage">
                  <input
                    type="checkbox"
                    checked={inputs[section.coverage] === true}
                    onChange={(e) =>
                      edit({ ...inputs, [section.coverage!]: e.target.checked })
                    }
                  />{" "}
                  I confirm all {section.title.toLowerCase()} are represented,
                  or there are none.
                </label>
              )}
            </section>
          );
        })}
        <section aria-labelledby="ledger-form-heading">
          <h2 id="ledger-form-heading">Share ledger and Capital Gains Tax</h2>
          <label className="coverage" htmlFor="include-m2">
            <input id="include-m2" type="checkbox" checked={includeLedger} onChange={(event) => {
              setIncludeLedger(event.target.checked);
              setErrors([]);
              invalidate();
            }} />
            Include share ledger and CGT
          </label>
          {includeLedger && <>
            <p>Use matching share identities and source IDs to link grants, vests, sales, expenses and payroll.</p>
            {ledgerSections.map((section) => {
              const rows = ledger[section.key] as RecordValue[];
              const path = `inputs.${section.key}`;
              return <details key={section.key} id={path} tabIndex={-1} open={errors.some((error) =>
                error.field === path || error.field.startsWith(`${path}.`)) || undefined}>
                <summary>{section.title} ({rows.length})</summary>
                {rows.map((row, index) => (
                  <fieldset key={index}>
                    <legend>{section.title} · entry {index + 1}</legend>
                    <Editor fields={section.fields} value={row} path={`${path}.${index}`} errors={errors}
                      change={(next) => editLedger({ ...ledger, [section.key]: rows.map((item, i) => i === index ? next : item) })} />
                    <button type="button" className="remove" onClick={() =>
                      editLedger({ ...ledger, [section.key]: rows.filter((_, i) => i !== index) })}>
                      Remove entry {index + 1} from {section.title}
                    </button>
                  </fieldset>
                ))}
                <button type="button" onClick={() => editLedger({ ...ledger, [section.key]: [...rows, newLedgerRecord(section)] })}>
                  {section.add}
                </button>
              </details>;
            })}
            <details id="inputs.annual" tabIndex={-1} open={errors.some(({ field }) => field.startsWith("inputs.annual")) || undefined}>
              <summary>Annual CGT evidence</summary>
              <p>Enter other gains and losses, including explicit zero amounts. For the rate band, enter an externally
                confirmed unused band or taxable income and the confirmed band extension.</p>
              {([["capital", "Other gains and losses", capitalFields], ["band", "Tax band evidence", bandFields]] as const)
                .map(([key, label, fields]) => <label className="coverage" key={key}>
                  <input type="checkbox" checked={annual[key] !== null} onChange={(event) => {
                    const record = blankFields(fields);
                    (record.source as RecordValue).event_id = `annual-${key}`;
                    editLedger({ ...ledger, annual: { ...annual, [key]: event.target.checked ? record : null } });
                  }} />
                  Include {label.toLowerCase()}
                </label>)}
              <Editor fields={activeAnnualFields} value={annual} path="inputs.annual" errors={errors}
                change={(next) => editLedger({ ...ledger, annual: next })} />
            </details>
            <Editor fields={settlementCoverage} value={ledger} path="inputs" errors={errors} change={editLedger} />
          </>}
        </section>
        <div className="calculate">
          <button className="primary" disabled={busy} type="submit">
            {busy ? "Calculating…" : includeLedger ? "Calculate ANI and shares" : "Calculate ANI"}
          </button>
          <p role="status" aria-live="polite">
            {message}
          </p>
        </div>
      </form>
      {result && (
        <section aria-labelledby="results-heading" className="results">
          <p className="eyebrow">
            {result.status.toUpperCase()} · LOCAL CALCULATION
          </p>
          <h2 id="results-heading" tabIndex={-1}>
            Your calculation
          </h2>
          <p>
            Selected tax year starting {String(inputs.start_year ?? "unknown")}{" "}
            · Verified rule period:{" "}
            {result.rules
              ? "6 April 2026–5 April 2027"
              : "Unavailable for selection"}{" "}
            · Rule version:{" "}
            {String(result.rules?.version ?? "No supported rules selected")}
          </p>
          {result.warnings.length > 0 && (
            <div className="notice">
              <h3>Warnings — resolve before relying on totals</h3>
              <ul>
                {result.warnings.map((warning, i) => (
                  <li key={i}>
                    {warning.field}: {warning.message}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="totals">
            <div>
              <h3>Projected ANI</h3>
              <p data-testid="ani">{gbp(result.ani_gbp)}</p>
            </div>
            <div>
              <h3>Standard Personal Allowance</h3>
              <p data-testid="allowance">
                {gbp(result.personal_allowance_gbp)}
              </p>
            </div>
            <div>
              <h3>Signed target headroom</h3>
              <p data-testid="headroom">{gbp(result.headroom_gbp)}</p>
            </div>
          </div>
          <p>
            Headroom is target minus ANI: a negative value means above your
            chosen target. The statutory taper threshold is £100,000,
            independent of that target. The standard allowance reduces by £1 for
            every £2 above the threshold, with the remaining allowance rounded
            up to a whole pound.
          </p>
          <p>
            HMRC net income: {gbp(result.net_income_gbp)} · Taxable income
            before personal deductions: {gbp(result.taxable_income_gbp)}
          </p>
          <h3>Calculation waterfall</h3>
          {result.rows.map((row) => (
            <details key={row.key}>
              <summary>
                {words(row.key)} <strong>{gbp(row.amount_gbp)}</strong>{" "}
                <span className="badge">{row.status}</span>
              </summary>
              <p>{row.explanation}</p>
              <p>Source records, dates and decisions</p>
              <Evidence
                value={row.evidence_path
                  .split(".")
                  .reduce<unknown>(
                    (v, key) =>
                      v && typeof v === "object"
                        ? (v as Record<string, unknown>)[key]
                        : null,
                    result,
                  )}
              />
            </details>
          ))}
          <details>
            <summary>Rules, dates, assumptions & rounding</summary>
            <p>
              Sources verified {result.sources_verified_on}. Displayed GBP
              rounds half-up to pennies once; calculations use exact unrounded
              values. Independently rounded rows may differ from ANI. Display
              rounding difference: {gbp(result.rounding_discrepancy_gbp)}.
            </p>
            <ul>
              {result.assumptions.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
            <Evidence value={result.rules} />
            <ul>
              {result.source_urls.map((url) => (
                <li key={url}>
                  <a href={url}>
                    {url.includes("legislation")
                      ? "Income Tax Act 2007, section 35"
                      : "HMRC adjusted net income guidance"}
                  </a>
                </li>
              ))}
            </ul>
          </details>
          <details>
            <summary>All entered source evidence & dates</summary>
            <Evidence value={result.inputs} />
          </details>
        </section>
      )}
      {m2Result && <LedgerResults result={m2Result} />}
      <footer>
        Local-first · Synthetic examples only in tests · Persistence planned for
        M4
      </footer>
    </main>
  );
}
