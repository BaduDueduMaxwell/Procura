import { FileCheck2, ShieldCheck, Timer } from "lucide-react";
import type { AgentResponse } from "@/lib/types";

export function EvidencePanel({ result, close, tourId }: { result?: AgentResponse; close?: () => void; tourId?: string }) {
  return <aside className="evidence" data-tour={tourId} aria-label="Decision evidence">
    <div className="panel-heading"><div><p className="eyebrow">Decision evidence</p><h2>Audit trail</h2></div>{close && <button className="icon-button mobile-only" onClick={close} aria-label="Close decision evidence">×</button>}</div>
    {!result ? <div className="evidence-empty"><FileCheck2 size={26} /><p>Evidence will appear here once a request is evaluated.</p></div> : <>
      <div className="evidence-item"><ShieldCheck size={18} /><div><strong>Policy applied</strong><span>{result.decision.policy_version}</span></div></div>
      <div className="evidence-item"><Timer size={18} /><div><strong>Workflow state</strong><span>{result.decision.status.replaceAll("_", " ")}</span></div></div>
      <div className="divider" />
      <p className="label">Trace ID</p><code className="trace-code">{result.decision.trace_id}</code>
      <details><summary>Tool progress</summary><ol className="tool-list">{result.progress_events.map(event => <li key={event}>{event}</li>)}</ol></details>
      <div className="boundary"><strong>Autonomy boundary</strong><p>No order was placed and no external supplier message was sent.</p></div>
    </>}
  </aside>;
}
