"use client";

import { ChangeEvent, DragEvent, FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Check, ChevronLeft, ChevronRight, Download, FileSpreadsheet, LoaderCircle, RefreshCw, Search, Send, Upload, X } from "lucide-react";
import { api } from "@/lib/api";
import type { IntakeLine, IntakeStatus, ProcurementIntake } from "@/lib/types";

const PAGE_SIZE = 25;
const editable: { key: keyof IntakeLine; label: string; type?: string }[] = [
  { key: "medicine_name", label: "Medicine" }, { key: "strength", label: "Strength" },
  { key: "dosage_form", label: "Dosage form" }, { key: "quantity", label: "Quantity", type: "number" },
  { key: "unit", label: "Unit" }, { key: "pack_size", label: "Pack size", type: "number" },
  { key: "destination", label: "Destination" }, { key: "max_lead_time_days", label: "Delivery days", type: "number" },
  { key: "currency", label: "Currency" },
];

const statusText: Record<IntakeStatus | IntakeLine["status"], string> = {
  draft: "Draft", processing: "Processing", needs_correction: "Needs correction",
  suggestion_available: "Suggestion available", ready: "Ready", submitted: "Submitted",
  critical_review_required: "Critical review required", failed_safe: "Retry available",
};

function count(intake: ProcurementIntake, status: IntakeLine["status"]) {
  return intake.lines.filter(line => line.status === status).length;
}

function IntakeStatusBadge({ status }: { status: IntakeStatus | IntakeLine["status"] }) {
  const blocked = ["needs_correction", "critical_review_required", "failed_safe"].includes(status);
  return <span className={`intake-status status-${status}`}><span aria-hidden>{status === "ready" || status === "submitted" ? "✓" : blocked ? "!" : "•"}</span>{statusText[status]}</span>;
}

export function BuyerIntake({ onNotice }: { onNotice?: (title: string, detail: string, tone?: "progress" | "success" | "attention" | "error") => void }) {
  const [current, setCurrent] = useState<ProcurementIntake>();
  const [recent, setRecent] = useState<ProcurementIntake[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [sheet, setSheet] = useState("all");
  const [page, setPage] = useState(1);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const loadRecent = () => api.intakes().then(setRecent).catch(() => undefined);
  useEffect(() => {
    const syncRoute = async () => {
      const routeId = window.location.pathname.match(/^\/intake\/([^/]+)$/)?.[1];
      try {
        const items = await api.intakes();
        setRecent(items);
        if (!routeId) { setCurrent(undefined); return; }
        const id = decodeURIComponent(routeId);
        setCurrent(items.find(item => item.id === id) ?? await api.intake(id));
      } catch { setError("This saved intake could not be loaded."); }
    };
    syncRoute();
    window.addEventListener("popstate", syncRoute);
    return () => window.removeEventListener("popstate", syncRoute);
  }, []);

  function showIntake(intake: ProcurementIntake) {
    setCurrent(intake);
    const path = `/intake/${encodeURIComponent(intake.id)}`;
    if (window.location.pathname !== path) window.history.pushState({}, "", path);
  }

  async function run(action: () => Promise<ProcurementIntake>, progress: string) {
    setBusy(true); setError(""); onNotice?.(progress, "Procura is checking catalogue identity and required fields.");
    try {
      const result = await action(); showIntake(result); await loadRecent();
      const detail = result.status === "ready" ? "Every row is ready for confirmation." : result.status === "submitted" ? "The validated requirement is now submitted." : "Review the highlighted rows and continue from the same draft.";
      onNotice?.(result.status === "ready" ? "Validation complete" : result.status === "submitted" ? "Submission recorded" : "Feedback ready", detail, result.status === "ready" || result.status === "submitted" ? "success" : "attention");
      return result;
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "The intake could not be processed.";
      setError(message); onNotice?.("Intake interrupted", message, "error");
    } finally { setBusy(false); }
  }

  async function submitText(event: FormEvent) {
    event.preventDefault(); const value = text.trim(); if (!value || busy) return;
    const result = await run(() => api.createTextIntake(value), "Reading request");
    if (result) setText("");
  }

  async function upload(file?: File) {
    if (!file || busy) return;
    if (!/\.(csv|xlsx)$/i.test(file.name)) { setError("Upload an .xlsx or .csv procurement list."); return; }
    if (file.size > 5 * 1024 * 1024) { setError("The file exceeds the 5 MB upload limit."); return; }
    await run(() => api.uploadIntake(file), "Validating procurement list");
    if (inputRef.current) inputRef.current.value = "";
  }

  function drop(event: DragEvent) { event.preventDefault(); setDragging(false); upload(event.dataTransfer.files[0]); }
  const sheets = useMemo(() => [...new Set(current?.lines.map(line => line.sheet_name).filter(Boolean) as string[] ?? [])], [current]);
  const rows = useMemo(() => (current?.lines ?? []).filter(line => {
    const term = `${line.medicine_name ?? ""} ${line.strength ?? ""} ${line.dosage_form ?? ""}`.toLowerCase();
    return term.includes(search.toLowerCase()) && (filter === "all" || line.status === filter) && (sheet === "all" || line.sheet_name === sheet);
  }), [current, search, filter, sheet]);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const visible = rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  if (!current) return <main className="page-shell buyer-intake-shell">
    <header className="page-head"><div><p className="eyebrow">Buyer intake</p><h1>Prepare a complete requirement</h1><p>Enter one request or upload a procurement list. Procura returns corrections before the requirement reaches operations.</p></div></header>
    <section className="intake-start-grid">
      <article className={`intake-option upload-option ${dragging ? "is-dragging" : ""}`} onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={drop}>
        <div className="intake-option-icon"><Upload size={20}/></div><span>Spreadsheet intake</span><h2>Upload procurement list</h2><p>Use CSV or XLSX up to 5 MB and 2,000 rows. Procura checks every row together.</p>
        <input ref={inputRef} id="intake-file" type="file" accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(event: ChangeEvent<HTMLInputElement>) => upload(event.target.files?.[0])}/>
        <button type="button" onClick={() => inputRef.current?.click()} disabled={busy}><FileSpreadsheet size={16}/>{busy ? "Processing…" : "Choose a file"}</button>
        <a href={api.intakeTemplateUrl()}><Download size={14}/>Download template</a>
      </article>
      <article className="intake-option text-option"><div className="intake-option-icon"><Send size={20}/></div><span>Single requirement</span><h2>Describe a request</h2><p>Include medicine, strength, form, quantity, pack size, destination, delivery need, and currency.</p>
        <form onSubmit={submitText}><label htmlFor="intake-text">Procurement requirement</label><textarea id="intake-text" value={text} onChange={event => setText(event.target.value)} maxLength={4000} placeholder="We need 600 packs of omeprazole 20 mg capsules, pack size 28, delivered to Accra within 18 days, priced in USD."/><button disabled={busy || !text.trim()}>{busy ? <LoaderCircle className="spin" size={16}/> : <Send size={16}/>}Check requirement</button></form>
      </article>
    </section>
    {error && <div className="intake-error" role="alert"><AlertTriangle size={18}/><div><strong>Could not process this intake</strong><p>{error}</p></div></div>}
    <section className="recent-intakes"><div><p className="eyebrow">Saved progress</p><h2>Recent intake drafts</h2></div>{recent.length ? <div>{recent.slice(0, 5).map(item => <button key={item.id} onClick={() => showIntake(item)}><span><strong>{item.filename ?? item.lines[0]?.medicine_name ?? "Procurement intake"}</strong><small>{item.lines.length} row{item.lines.length === 1 ? "" : "s"} · {new Date(item.updated_at).toLocaleString()}</small></span><IntakeStatusBadge status={item.status}/></button>)}</div> : <p>No saved intake drafts yet.</p>}</section>
  </main>;

  return <main className="page-shell buyer-intake-shell validation-workspace">
    <header className="page-head"><div><button className="back-link" onClick={() => { setCurrent(undefined); window.history.pushState({}, "", "/intake"); }}><ChevronLeft size={15}/>All intakes</button><p className="eyebrow">Validation workspace</p><h1>{current.filename ?? current.lines[0]?.medicine_name ?? "Procurement requirement"}</h1><p>Correct highlighted fields, confirm catalogue suggestions, then submit the validated requirement.</p></div><IntakeStatusBadge status={current.status}/></header>
    {current.status === "failed_safe" && <section className="intake-error intake-retry" role="alert"><AlertTriangle size={18}/><div><strong>The request interpreter is temporarily unavailable</strong><p>Your draft is saved. Retry without re-entering the request. No review case has been created.</p></div><button disabled={busy} onClick={() => run(() => api.revalidateIntake(current.id, current.version), "Retrying saved request")}><RefreshCw size={15}/>{busy ? "Retrying…" : "Retry processing"}</button></section>}
    <div className="intake-metrics" aria-live="polite"><div><span>Total rows</span><strong>{current.lines.length}</strong></div><div><span>Ready</span><strong>{count(current, "ready")}</strong></div><div><span>Need information</span><strong>{count(current, "needs_correction")}</strong></div><div><span>Suggestions</span><strong>{count(current, "suggestion_available")}</strong></div><div><span>Critical</span><strong>{count(current, "critical_review_required")}</strong></div></div>
    <section className="validation-card">
      <div className="validation-toolbar"><label><Search size={15}/><span className="sr-only">Search rows</span><input value={search} onChange={event => { setSearch(event.target.value); setPage(1); }} placeholder="Search medicine, strength, or form"/></label><select aria-label="Filter by status" value={filter} onChange={event => { setFilter(event.target.value); setPage(1); }}><option value="all">All statuses</option><option value="needs_correction">Needs correction</option><option value="suggestion_available">Suggestions</option><option value="ready">Ready</option><option value="critical_review_required">Critical review</option></select>{sheets.length > 1 && <select aria-label="Filter by worksheet" value={sheet} onChange={event => setSheet(event.target.value)}><option value="all">All worksheets</option>{sheets.map(name => <option key={name}>{name}</option>)}</select>}</div>
      <div className="intake-table-wrap"><table className="intake-table"><thead><tr><th>Row</th><th>Medicine requirement</th><th>Quantity</th><th>Destination</th><th>Status</th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>{visible.map(line => <IntakeRow key={line.id} line={line} intake={current} busy={busy} run={run}/>)}</tbody></table></div>
      {!visible.length && <p className="table-empty">No rows match these filters.</p>}
      {pages > 1 && <div className="table-pagination"><button onClick={() => setPage(value => Math.max(1, value - 1))} disabled={page === 1}><ChevronLeft size={14}/>Previous</button><span>Page {page} of {pages}</span><button onClick={() => setPage(value => Math.min(pages, value + 1))} disabled={page === pages}>Next<ChevronRight size={14}/></button></div>}
    </section>
    {error && <div className="intake-error" role="alert"><AlertTriangle size={18}/><div><strong>Action could not be completed</strong><p>{error}</p></div></div>}
    <section className="submission-summary"><div><p className="eyebrow">Final confirmation</p><h2>{current.status === "submitted" ? "Requirement submitted" : "Submission summary"}</h2><dl><div><dt>Original rows</dt><dd>{current.lines.length}</dd></div><div><dt>Ready rows</dt><dd>{count(current, "ready")}</dd></div><div><dt>Automatically normalized</dt><dd>{current.lines.filter(line => (line.normalized_fields?.length ?? 0) > 0).length}</dd></div><div><dt>Buyer-corrected rows</dt><dd>{current.lines.filter(line => (line.buyer_corrected_fields?.length ?? 0) > 0).length}</dd></div><div><dt>Accepted suggestions</dt><dd>{current.lines.filter(line => line.suggestion?.status === "accepted").length}</dd></div><div><dt>Rejected suggestions</dt><dd>{current.lines.filter(line => line.suggestion?.status === "rejected").length}</dd></div><div><dt>Remaining blockers</dt><dd>{current.lines.reduce((total, line) => total + line.findings.filter(item => item.severity === "blocker" || item.severity === "critical").length + (line.suggestion?.status === "pending" ? 1 : 0), 0)}</dd></div></dl><p>No purchase order has been placed and no supplier has been contacted.</p><small>Validated {new Date(current.updated_at).toLocaleString()} · {current.policy_version} · Trace {current.trace_id}</small></div><button disabled={busy || current.status !== "ready"} onClick={() => run(() => api.submitIntake(current.id, current.version), "Recording submission")}><Check size={16}/>{current.status === "submitted" ? "Submitted" : "Confirm submission"}</button></section>
  </main>;
}

function IntakeRow({ line, intake, busy, run }: { line: IntakeLine; intake: ProcurementIntake; busy: boolean; run: (action: () => Promise<ProcurementIntake>, progress: string) => Promise<ProcurementIntake | undefined> }) {
  const [open, setOpen] = useState(line.status !== "ready");
  const [values, setValues] = useState<Record<string, string>>({});
  function value(key: keyof IntakeLine) { return values[String(key)] ?? String(line[key] ?? ""); }
  function keydown(event: KeyboardEvent<HTMLTableRowElement>) { if (event.key === "Enter" && event.target === event.currentTarget) setOpen(value => !value); }
  return <>
    <tr tabIndex={0} onKeyDown={keydown} className="intake-row"><td>{line.sheet_name ? `${line.sheet_name} · ` : ""}{line.source_row}</td><td><strong>{line.medicine_name || "Medicine needed"}</strong><small>{[line.strength, line.dosage_form, line.pack_size ? `pack ${line.pack_size}` : undefined].filter(Boolean).join(" · ") || "Details incomplete"}</small></td><td>{line.quantity ? `${line.quantity.toLocaleString()} ${line.unit ?? ""}` : "Missing"}</td><td>{line.destination || "Missing"}</td><td><IntakeStatusBadge status={line.status}/></td><td><button aria-expanded={open} onClick={() => setOpen(value => !value)}>{open ? "Hide" : "Review"}</button></td></tr>
    {open && <tr className="intake-row-detail"><td colSpan={6}><div>
      {line.suggestion?.status === "pending" && <section className="catalogue-suggestion"><div><strong>{line.suggestion.brand_name ? "Confirm brand mapping" : "Catalogue suggestion"}</strong><p>“{line.suggestion.original_value}” may be <b>{line.suggestion.suggested_value}</b>. {line.suggestion.match_reason}.</p>{line.suggestion.brand_name && <p className="suggestion-evidence"><span>Registered brand: <b>{line.suggestion.brand_name}</b></span><span>Active ingredient: <b>{line.suggestion.registered_active_ingredient}</b></span><span>Manufacturer: <b>{line.suggestion.manufacturer}</b></span><span>Registered variant: <b>{line.suggestion.registered_strength} {line.suggestion.registered_dosage_form}</b></span>{line.suggestion.source_url && <a href={line.suggestion.source_url} target="_blank" rel="noreferrer">View Ghana FDA source record</a>}</p>}{!line.suggestion.brand_name && <small>Source: {line.suggestion.source_record_id}</small>}<small>The original value is preserved. Accepting records your confirmation; it does not place an order.</small></div><div><button disabled={busy} onClick={() => run(() => api.decideIntakeSuggestion(intake.id, line.id, intake.version, "reject"), "Rejecting suggestion")}><X size={14}/>Reject</button><button disabled={busy} onClick={() => run(() => api.decideIntakeSuggestion(intake.id, line.id, intake.version, "accept"), "Applying confirmed suggestion")}><Check size={14}/>Accept mapping</button></div></section>}
      {line.findings.length > 0 && <ul className="finding-list">{line.findings.map(item => <li key={item.code} className={`finding-${item.severity}`}><AlertTriangle size={14}/><span><strong>{item.message}</strong><small>{item.suggested_action} · Evidence: {item.evidence_source}</small></span></li>)}</ul>}
      <form className="row-editor" onSubmit={event => { event.preventDefault(); const changed = Object.fromEntries(Object.entries(values).map(([key, item]) => [key, ["quantity", "pack_size", "max_lead_time_days"].includes(key) ? Number(item) : item])); run(() => api.patchIntakeLine(intake.id, line.id, intake.version, changed), "Revalidating changed row").then(result => result && setValues({})); }}>
        {editable.map(field => <label key={String(field.key)}><span>{field.label}</span><input type={field.type ?? "text"} value={value(field.key)} onChange={event => setValues(current => ({ ...current, [String(field.key)]: event.target.value }))}/></label>)}
        <button disabled={busy || !Object.keys(values).length}><RefreshCw size={14}/>Save and revalidate row</button>
      </form>
      <details><summary>Original values</summary><pre>{JSON.stringify(line.original_values, null, 2)}</pre></details>
    </div></td></tr>}
  </>;
}
