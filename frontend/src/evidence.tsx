import type { ExactGBP } from "./api";

export const words = (value: string) => value.replaceAll("_", " ");
export const gbp = (amount: ExactGBP | null) =>
  amount === null
    ? "Unavailable"
    : `£${amount.display_gbp.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}`;
export function Evidence({ value }: { value: unknown }) {
  if (value === null || value === undefined)
    return <span>Unknown / not supplied</span>;
  if (typeof value !== "object") return <span>{String(value)}</span>;
  if ("display_gbp" in value)
    return (
      <span>
        {gbp(value as ExactGBP)}{" "}
        <small>
          (exact {String((value as ExactGBP).numerator)}/
          {String((value as ExactGBP).denominator)})
        </small>
      </span>
    );
  if (Array.isArray(value))
    return value.length ? (
      <ol>
        {value.map((item, i) => (
          <li key={i}>
            <Evidence value={item} />
          </li>
        ))}
      </ol>
    ) : (
      <span>None</span>
    );
  return (
    <dl className="evidence">
      {Object.entries(value).map(([key, child]) => (
        <div key={key}>
          <dt>{words(key)}</dt>
          <dd>
            <Evidence value={child} />
          </dd>
        </div>
      ))}
    </dl>
  );
}
