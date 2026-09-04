import { CircleAlert, PackageCheck } from "lucide-react";
import type { AgentResponse } from "@/lib/types";
import { StatusBadge } from "./StatusBadge";

const names: Record<string, string> = { northstar: "Northstar Health Supply", kora: "Kora Medical Logistics", baobab: "Baobab Pharma Collective", lumina: "Lumina Essential Medicines", cedar: "Cedar Bridge Therapeutics" };
export function formatReviewReason(reason: string): string {
  const legacy: Record<string, string> = {
    "Safe failure: ValueError": "The verification sequence was incomplete, so Procura stopped before evaluating suppliers.",
    "Safe failure: ToolTimeoutError": "Supplier verification timed out before all eligibility checks completed.",
    "Safe failure: ProviderUnavailableError": "The request could not be interpreted because the language provider was unavailable.",
    "Safe failure: InvalidModelOutputError": "The request interpreter returned an invalid structured request after one retry.",
  };
  const prefix = reason.startsWith("Escalation: ") ? "Escalation: " : "";
  const raw = prefix ? reason.slice(prefix.length) : reason;
  const readable = legacy[raw] ?? raw.replaceAll("_", " ").replace(/^./, letter => letter.toUpperCase());
  return `${prefix}${readable}`;
}

function humanJoin(values: string[]): string {
  if (values.length === 1) return values[0];
  if (values.length === 2) return `${values[0]} and ${values[1]}`;
  return `${values.slice(0, -1).join(", ")}, and ${values.at(-1)}`;
}

export function summarizeReviewReasons(reasons: string[], requiredLeadTime?: number, quoteCount?: number): string[] {
  const raw = reasons.map(reason => reason.replace(/^Escalation: /, "").trim());
  const consumed = new Set<number>();
  const summaries: string[] = [];
  const leadTimes: number[] = [];

  raw.forEach((reason, index) => {
    const match = reason.match(/^(\d+) day lead time misses requirement$/i);
    if (match) { leadTimes.push(Number(match[1])); consumed.add(index); }
  });
  if (leadTimes.length) {
    const all = quoteCount && leadTimes.length === quoteCount ? "all " : "";
    const requirement = requiredLeadTime ? `the ${requiredLeadTime}-day requirement` : "the required lead time";
    const subject = `${leadTimes.length} quotation${leadTimes.length === 1 ? "" : "s"}`;
    const verb = leadTimes.length === 1 ? "exceeds" : "exceed";
    summaries.push(`Delivery: ${all}${subject} ${verb} ${requirement} (${humanJoin(leadTimes.sort((a, b) => a - b).map(String))} day${leadTimes.length === 1 ? "" : "s"}).`);
  }

  const expired = raw.flatMap((reason, index) => reason.toLowerCase() === "authorization expired" ? [index] : []);
  expired.forEach(index => consumed.add(index));
  if (expired.length) summaries.push(`Authorization: ${expired.length === 1 ? "one supplier has" : `${expired.length} suppliers have`} expired authorization.`);

  raw.forEach((reason, index) => {
    const match = reason.match(/^Currency ([A-Z]{3}) cannot be compared with ([A-Z]{3}) without a verified rate$/i);
    if (!match) return;
    consumed.add(index);
    summaries.push(`Currency: the ${match[1].toUpperCase()} quote cannot be compared with the requested ${match[2].toUpperCase()} without a verified rate.`);
  });

  const noEligibleReasons = new Set(["no eligible quotation", "no eligible quotation is available after deterministic supplier checks"]);
  const noEligible = raw.flatMap((reason, index) => noEligibleReasons.has(reason.toLowerCase()) ? [index] : []);
  noEligible.forEach(index => consumed.add(index));
  raw.forEach((reason, index) => { if (!consumed.has(index)) summaries.push(formatReviewReason(reason)); });
  if (noEligible.length) summaries.push("Outcome: no eligible quotation remains after deterministic supplier checks.");
  return [...new Set(summaries)];
}
export function DecisionCards({ result }: { result: AgentResponse }) {
  const { request, quotes, decision } = result;
  const recommendedQuote = quotes.find(quote => quote.supplier_id === decision.recommendation_supplier_id);
  const reviewReasons = summarizeReviewReasons(decision.escalation_reasons, request.max_lead_time_days, quotes.length);
  return <div className="result-stack">
    <section className="data-card"><div className="card-title"><PackageCheck size={18} /><h3>Request brief</h3></div>
      <dl className="request-grid">
        <div><dt>Medicine</dt><dd>{request.medicine.medicine_name || "Pending"}</dd></div><div><dt>Strength</dt><dd>{request.medicine.strength || "Pending"}</dd></div>
        <div><dt>Form</dt><dd>{request.medicine.dosage_form || "Pending"}</dd></div><div><dt>Quantity</dt><dd>{request.medicine.quantity ? `${request.medicine.quantity.toLocaleString()} packs` : "Pending"}</dd></div>
        <div><dt>Pack size</dt><dd>{request.medicine.pack_size || "Pending"}</dd></div><div><dt>Destination</dt><dd>{request.destination || "Pending"}</dd></div>
        <div><dt>Delivery</dt><dd>{request.max_lead_time_days ? `Within ${request.max_lead_time_days} days` : "Pending"}</dd></div><div><dt>Currency</dt><dd>{request.currency || "Pending"}</dd></div>
      </dl>
    </section>
    {decision.human_review_required && <div className="review-banner" role="status"><CircleAlert size={20} /><div><strong>Human review required</strong><p>Supplier evidence needs a reviewer before this requirement can proceed.</p>{reviewReasons.length ? <ul>{reviewReasons.map(reason => <li key={reason}>{reason}</li>)}</ul> : <p>An unsafe condition requires staff review.</p>}</div></div>}
    {quotes.length > 0 && <section className="data-card quote-card"><div className="card-title"><h3>Quotation comparison</h3><span>{quotes.length} reviewed</span></div>
      <div className="quote-table" role="table" aria-label="Supplier quotation comparison">
        {quotes.map((quote, index) => <div className="quote-row" role="row" key={quote.quote_id}>
          <div className="supplier-cell"><span className="rank">{String(index + 1).padStart(2, "0")}</span><div><strong>{quote.supplier_display_name || names[quote.supplier_id] || quote.supplier_id}</strong><small>{quote.reliability * 100}% reliability · {quote.lead_time_days} days</small></div></div>
          <div className="price"><strong>{quote.currency} {quote.total_price.toLocaleString(undefined, { minimumFractionDigits: 2 })}</strong><small>Total for {quote.requested_quantity_packs.toLocaleString()} requested packs</small></div>
          <StatusBadge status={quote.eligible ? "eligible" : "ineligible"} />
          <div className="quote-basis">{quote.available_quantity_packs.toLocaleString()} available · pack {quote.offered_pack_size} · {quote.currency} {quote.unit_price.toFixed(2)} per pack</div>
          <ul className={`quote-reasons ${quote.eligible ? "quote-passed" : ""}`}>{quote.eligible ? <li>All eligibility checks passed</li> : quote.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>
        </div>)}
      </div>
    </section>}
    {decision.status === "recommended" && <div className="recommendation"><span>Recommended supplier</span><strong>{recommendedQuote?.supplier_display_name || names[decision.recommendation_supplier_id || ""] || decision.recommendation_supplier_id}</strong><p>Best balance of eligibility, price, delivery, and reliability. Confirm approval before issuing an order.</p></div>}
  </div>;
}
