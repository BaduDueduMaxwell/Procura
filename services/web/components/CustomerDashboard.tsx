"use client";

import { useEffect, useState } from "react";
import { ArrowRight, FileSearch, PackageCheck, Plus } from "lucide-react";
import { api } from "@/lib/api";
import type { CustomerDashboard as CustomerDashboardData, IntakeDashboardSummary, IntakeStatus, ProcurementIntake, ProcurementLifecycle } from "@/lib/types";
import { StatusBadge } from "./StatusBadge";

function medicineLabel(name?: string, strength?: string, fallback = "Incomplete requirement") {
  if (!name) return fallback;
  const normalizedName = `${name.charAt(0).toUpperCase()}${name.slice(1)}`;
  return strength ? `${normalizedName} ${strength}` : normalizedName;
}

const intakeLabels: Record<IntakeStatus, string> = {
  draft: "Draft",
  processing: "Processing",
  needs_correction: "Needs correction",
  suggestion_available: "Suggestion available",
  ready: "Ready to submit",
  submitted: "Submitted",
  critical_review_required: "Critical review",
  failed_safe: "Retry available",
};

function intakeTitle(intake: ProcurementIntake) {
  return intake.filename ?? medicineLabel(intake.lines[0]?.medicine_name, intake.lines[0]?.strength, "Procurement requirement");
}

export function CustomerDashboard({
  onStart,
  onOpenDecision,
  onOpenIntake,
}: {
  onStart: () => void;
  onOpenDecision: (traceId: string) => void;
  onOpenIntake: (intakeId: string) => void;
}) {
  const [data, setData] = useState<CustomerDashboardData>();
  const [intakes, setIntakes] = useState<IntakeDashboardSummary>();
  const [requests, setRequests] = useState<ProcurementLifecycle[]>([]);
  const [expanded, setExpanded] = useState<string>();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    Promise.all([api.customerDashboard(), api.intakeSummary(), api.procurementRequests().catch(() => [] as ProcurementLifecycle[])])
      .then(([summary, intakeSummary, lifecycles]) => {
        setData(summary);
        setIntakes(intakeSummary);
        setRequests(lifecycles);
      })
      .catch(() => setFailed(true));
  }, []);

  if (failed) return <main className="page-shell"><div className="error-state" role="alert">Dashboard data is unavailable.</div></main>;
  if (!data || !intakes) return <main className="page-shell"><div className="progress-line" role="status"><span className="pulse-dot" />Loading your dashboard…</div></main>;

  return <main className="page-shell">
    <header className="page-head"><div><p className="eyebrow">Buyer overview</p><h1>Procurement dashboard</h1><p>Track requirements from intake through supplier comparison and review.</p></div><button className="primary-page-action" onClick={onStart}><Plus size={16}/>Start a requirement</button></header>
    <div className="metric-grid customer-metrics" data-tour="dashboard">
      <div className="metric"><span>Requirements</span><strong>{intakes.total}</strong></div>
      <div className="metric"><span>Needs attention</span><strong>{intakes.needs_correction}</strong></div>
      <div className="metric"><span>Ready to submit</span><strong>{intakes.ready}</strong></div>
      <div className="metric"><span>Submitted</span><strong>{intakes.submitted}</strong></div>
    </div>
    <section className="dashboard-grid">
      <article className="data-card"><div className="card-title"><FileSearch size={17}/><h2>Recent requirements</h2></div>
        {intakes.recent.length ? <div className="requirement-list">{intakes.recent.map((item, index) => <button type="button" key={item.id} onClick={() => onOpenIntake(item.id)} aria-label={`Open ${intakeTitle(item)}`}>
          <span className="decision-index">{String(index + 1).padStart(2, "0")}</span><span><strong>{intakeTitle(item)}</strong><small>{item.lines.length} row{item.lines.length === 1 ? "" : "s"} · Updated {new Date(item.updated_at).toLocaleDateString()}</small></span><span className={`intake-status status-${item.status}`}><span aria-hidden>{["ready", "submitted"].includes(item.status) ? "✓" : "•"}</span>{intakeLabels[item.status]}</span><ArrowRight className="row-arrow" size={15}/>
        </button>)}</div> : <div className="dashboard-empty"><FileSearch size={24}/><strong>No requirements yet</strong><p>Start with a single request or upload a procurement list.</p></div>}
      </article>
      <article className="data-card next-step"><span>Primary workflow</span><h2>Prepare a complete requirement</h2><p>Upload a list or describe a request. Procura flags missing details and suggests catalogue corrections before supplier comparison.</p><button onClick={onStart}>Open buyer intake<ArrowRight size={15}/></button></article>
    </section>
    <section className="data-card comparison-panel">
      <div className="card-title"><PackageCheck size={17}/><h2>Supplier comparison decisions</h2><span>{data.execution_count} evaluated</span></div>
      <div className="comparison-summary" aria-label="Supplier comparison totals"><span><strong>{data.recommendation_count}</strong> recommendation{data.recommendation_count === 1 ? "" : "s"}</span><span><strong>{data.review_count}</strong> review handoff{data.review_count === 1 ? "" : "s"}</span></div>
      {data.recent_decisions.length ? <div className="decision-list">{data.recent_decisions.map((item, index) => {
        const requestLabel = medicineLabel(item.medicine_name, item.strength);
        const decisionLabel = item.decision.replaceAll("_", " ");
        const detail = [item.dosage_form, decisionLabel].filter(Boolean).join(" · ");
        return <button type="button" key={item.trace_id} onClick={() => onOpenDecision(item.trace_id)} aria-label={`Open ${requestLabel} decision ${index + 1}: ${decisionLabel}`}><span className="decision-index">{String(index + 1).padStart(2, "0")}</span><span><strong>{requestLabel}</strong><small>{detail}</small></span><StatusBadge status={item.decision === "clarification" ? "clarification" : item.review_required ? "review" : "eligible"}/><ArrowRight className="row-arrow" size={15}/></button>;
      })}</div> : <div className="dashboard-empty compact"><PackageCheck size={24}/><strong>No supplier comparisons yet</strong><p>Submitted requirements can move into the comparison workspace.</p></div>}
    </section>
    {requests.length > 0 && <section className="data-card lifecycle-list"><div className="card-title"><h2>Supplier response timeline</h2><span>{requests.length} open or completed</span></div>{requests.map(item => <article key={item.id}><button type="button" onClick={() => setExpanded(expanded === item.id ? undefined : item.id)} aria-expanded={expanded === item.id}><span><strong>{medicineLabel(item.request.medicine.medicine_name, item.request.medicine.strength)}</strong><small>{item.invited_supplier_count} invited · {item.responses.length} response{item.responses.length === 1 ? "" : "s"}</small></span><span className={`state-label ${item.status}`}>{item.status.replaceAll("_", " ")}</span><ArrowRight size={14}/></button>{expanded === item.id && <ol className="timeline">{item.events.map(event => <li key={event.id}><span/><div><strong>{event.message}</strong><small>{event.actor_role} · {new Date(event.created_at).toLocaleString()}</small></div></li>)}</ol>}</article>)}</section>}
  </main>;
}
