import { CircleAlert, PackageCheck } from "lucide-react";
import type { AgentResponse } from "@/lib/types";
import { StatusBadge } from "./StatusBadge";

const names: Record<string, string> = { northstar: "Northstar Health Supply", kora: "Kora Medical Logistics", baobab: "Baobab Pharma Collective", lumina: "Lumina Essential Medicines", cedar: "Cedar Bridge Therapeutics" };
export function DecisionCards({ result }: { result: AgentResponse }) {
  const { request, quotes, decision } = result;
  return <div className="result-stack">
    <section className="data-card"><div className="card-title"><PackageCheck size={18} /><h3>Request brief</h3></div>
      <dl className="request-grid">
        <div><dt>Medicine</dt><dd>{request.medicine.medicine_name || "Pending"}</dd></div><div><dt>Strength</dt><dd>{request.medicine.strength || "Pending"}</dd></div>
        <div><dt>Form</dt><dd>{request.medicine.dosage_form || "Pending"}</dd></div><div><dt>Quantity</dt><dd>{request.medicine.quantity ? `${request.medicine.quantity.toLocaleString()} packs` : "Pending"}</dd></div>
        <div><dt>Pack size</dt><dd>{request.medicine.pack_size || "Pending"}</dd></div><div><dt>Destination</dt><dd>{request.destination || "Pending"}</dd></div>
        <div><dt>Delivery</dt><dd>{request.max_lead_time_days ? `Within ${request.max_lead_time_days} days` : "Pending"}</dd></div><div><dt>Currency</dt><dd>{request.currency || "Pending"}</dd></div>
      </dl>
    </section>
    {decision.human_review_required && <div className="review-banner" role="status"><CircleAlert size={20} /><div><strong>Human review required</strong><p>{decision.escalation_reasons[0] || "An unsafe condition requires staff review."}</p></div></div>}
    {quotes.length > 0 && <section className="data-card quote-card"><div className="card-title"><h3>Quotation comparison</h3><span>{quotes.length} reviewed</span></div>
      <div className="quote-table" role="table" aria-label="Supplier quotation comparison">
        {quotes.map((quote, index) => <div className="quote-row" role="row" key={quote.quote_id}>
          <div className="supplier-cell"><span className="rank">{String(index + 1).padStart(2, "0")}</span><div><strong>{names[quote.supplier_id] || quote.supplier_id}</strong><small>{quote.reliability * 100}% reliability · {quote.lead_time_days} days</small></div></div>
          <div className="price"><strong>{quote.currency} {quote.total_price.toLocaleString(undefined, { minimumFractionDigits: 2 })}</strong><small>{quote.score ? `Score ${quote.score}` : quote.reasons[0]}</small></div>
          <StatusBadge status={quote.eligible ? "eligible" : "ineligible"} />
        </div>)}
      </div>
    </section>}
    {decision.status === "recommended" && <div className="recommendation"><span>Recommended supplier</span><strong>{names[decision.recommendation_supplier_id || ""] || decision.recommendation_supplier_id}</strong><p>Best balance of eligibility, price, delivery, and reliability. Confirm approval before issuing an order.</p></div>}
  </div>;
}
