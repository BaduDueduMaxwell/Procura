"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Activity, ArrowRight, ArrowUp, Building2, Check, ChevronLeft, CircleHelp, ClipboardCheck, FileSearch, LayoutDashboard, LogOut, MessageSquareText, PackageCheck, PanelRight, Plus, RefreshCw, Send, Shield, TriangleAlert, WifiOff, X } from "lucide-react";
import { api } from "@/lib/api";
import type { AgentResponse, AuthUser, CustomerDashboard as CustomerDashboardData, Operations, ReviewCase, SupplierDashboard as SupplierDashboardData, SupplierSubmission } from "@/lib/types";
import { DecisionCards } from "@/components/DecisionCards";
import { EvidencePanel } from "@/components/EvidencePanel";
import { StatusBadge } from "@/components/StatusBadge";

type Screen = "dashboard" | "chat" | "supplier" | "reviews" | "supplierReviews" | "operations";
type TourStep = { title: string; description: string; screen: Screen; target?: string };
type Notice = { id: number; title: string; detail: string; tone: "progress" | "success" | "attention" | "error" };
const examples = [
  "1,500 packs of paracetamol 500 mg tablets, pack size 20, delivered to Accra within 18 days in USD.",
  "300 packs of insulin 100 units/ml vials, pack size 10, cold chain, delivered to Ghana within 21 days in USD.",
  "We need ceftriaxone delivered to Nairobi."
];
const screenRoutes: Record<Screen, string> = { dashboard: "/dashboard", chat: "/workspace", reviews: "/reviews", supplierReviews: "/reviews/suppliers", operations: "/operations", supplier: "/supplier" };
const routeScreens = Object.fromEntries(Object.entries(screenRoutes).map(([screen, route]) => [route, screen])) as Record<string, Screen>;

function allowedScreen(user: AuthUser, requested?: Screen): Screen {
  if (user.role === "supplier") return "supplier";
  if (!requested || requested === "supplier") return "dashboard";
  if (user.role === "buyer" && (requested === "reviews" || requested === "supplierReviews" || requested === "operations")) return "dashboard";
  return requested;
}

export default function Home() {
  const [user, setUser] = useState<AuthUser>();
  const [authReady, setAuthReady] = useState(false);
  const [screen, setScreen] = useState<Screen>("dashboard");
  const [conversationId, setConversationId] = useState<string>();
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<{ role: "user" | "assistant"; content: string; result?: AgentResponse }[]>([]);
  const [latest, setLatest] = useState<AgentResponse>();
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState<string>();
  const [error, setError] = useState<string>();
  const [drawer, setDrawer] = useState(false);
  const [tourStep, setTourStep] = useState<number | null>(null);
  const [notices, setNotices] = useState<Notice[]>([]);
  const endRef = useRef<HTMLDivElement>(null);
  const noticeId = useRef(0);

  const navigate = useCallback((next: Screen, replace = false) => {
    setScreen(next);
    const route = screenRoutes[next];
    if (window.location.pathname !== route) window.history[replace ? "replaceState" : "pushState"]({}, "", route);
  }, []);

  const notify = useCallback((title: string, detail: string, tone: Notice["tone"] = "progress") => {
    const id = ++noticeId.current;
    setNotices(current => [...current, { id, title, detail, tone }]);
    window.setTimeout(() => setNotices(current => current.filter(item => item.id !== id)), 4500);
  }, []);

  const startNew = async () => {
    setError(undefined); setMessages([]); setLatest(undefined);
    try { setConversationId((await api.createConversation()).id); notify("New request ready", "Describe the medicine and delivery requirement to begin."); }
    catch { setError("The Procura API is offline. Start the backend, then retry."); notify("Request could not be created", "Check the connection and try again.", "error"); }
  };
  useEffect(() => {
    api.me().then(account => {
      setUser(account);
      navigate(allowedScreen(account, routeScreens[window.location.pathname]), true);
    }).catch(() => {
      if (window.location.pathname !== "/") window.history.replaceState({}, "", "/");
    }).finally(() => setAuthReady(true));
  }, [navigate]);
  useEffect(() => {
    if (!user) return;
    const syncRoute = () => navigate(allowedScreen(user, routeScreens[window.location.pathname]), true);
    window.addEventListener("popstate", syncRoute);
    return () => window.removeEventListener("popstate", syncRoute);
  }, [navigate, user]);
  useEffect(() => { if (user && user.role !== "supplier") api.createConversation().then(conversation => setConversationId(conversation.id)).catch(() => setError("The Procura API is offline. Start the backend, then retry.")); }, [user]);
  useEffect(() => { endRef.current?.scrollIntoView?.({ behavior: "smooth" }); }, [messages, progress]);
  useEffect(() => {
    if (!user) return;
    const key = `procura-guide:${user.id}`;
    if (!window.localStorage.getItem(key)) {
      const timer = window.setTimeout(() => setTourStep(0), 450);
      return () => window.clearTimeout(timer);
    }
  }, [user]);
  const closeTour = useCallback(() => {
    if (user) window.localStorage.setItem(`procura-guide:${user.id}`, "seen");
    setTourStep(null);
  }, [user]);

  async function submit(event?: FormEvent, supplied?: string) {
    event?.preventDefault(); const content = (supplied || input).trim();
    if (!content || loading) return;
    setInput(""); setError(undefined); setLoading(true); setMessages(current => [...current, { role: "user", content }]);
    notify("Request submitted", "Procura is checking requirements and supplier quotations.");
    let id = conversationId;
    try {
      if (!id) { id = (await api.createConversation()).id; setConversationId(id); }
      for (const step of ["Request understood", "Checking supplier eligibility", "Comparing quotations", "Applying review policy"]) { setProgress(step); await new Promise(resolve => setTimeout(resolve, 180)); }
      const result = await api.sendMessage(id, content);
      setProgress("Recommendation ready"); setLatest(result);
      setMessages(current => [...current, { role: "assistant", content: result.message.content, result }]);
      if (result.decision.status === "recommended") notify("Review complete", "An eligible supplier recommendation is ready.", "success");
      else if (result.decision.status === "clarification") notify("More information needed", "Answer the clarification to continue the review.", "attention");
      else notify("Review complete", "The request has been routed for staff attention.", "attention");
    } catch { setError("The request could not be completed. Your text was not lost. Retry when the API is available."); notify("Review interrupted", "Your request is preserved and can be retried.", "error"); }
    finally { setTimeout(() => setProgress(undefined), 300); setLoading(false); }
  }

  if (!authReady) return <main className="auth-loading" role="status"><span className="pulse-dot" />Loading Procura…</main>;
  if (!user) return <Landing onAuthenticated={account => { setUser(account); navigate(allowedScreen(account), true); }} />;
  return <div className="app-shell">
    <Nav screen={screen} setScreen={navigate} onNew={() => { navigate("chat"); startNew(); }} onGuide={() => setTourStep(0)} user={user} onLogout={() => api.logout().finally(() => { setUser(undefined); setConversationId(undefined); window.history.replaceState({}, "", "/"); })} />
    {screen === "dashboard" && user.role !== "supplier" && <CustomerDashboard onStart={() => { navigate("chat"); startNew(); }} />}
    {screen === "supplier" && user.role === "supplier" && <SupplierDashboard />}
    {screen === "chat" && <main className="workspace">
      <header className="mobile-header"><Brand /><button className="icon-button" onClick={() => setDrawer(true)} aria-label="Open decision evidence"><PanelRight size={20} /></button></header>
      <section className="conversation" aria-label="Procurement conversation">
        <div className="conversation-head"><div><p className="eyebrow">Procurement review</p><h1>Describe what you need</h1></div><div className="head-actions"><button className="quiet-button tablet-evidence" onClick={() => setDrawer(true)} aria-label="Open decision evidence"><PanelRight size={16} />Evidence</button><button className="quiet-button desktop-only" onClick={startNew}><Plus size={16} />New request</button></div></div>
        <div className="messages" aria-live="polite">
          {messages.length === 0 && <EmptyState onExample={example => submit(undefined, example)} />}
          {messages.map((message, index) => <article className={`message ${message.role}`} key={index}>
            <div className="message-label">{message.role === "user" ? "You" : "Procura"}</div>
            <div className="message-body"><p>{message.content}</p>{message.result && <DecisionCards result={message.result} />}</div>
          </article>)}
          {progress && <div className="progress-line" role="status"><span className="pulse-dot" />{progress}</div>}
          {error && <div className="error-state" role="alert"><WifiOff size={20} /><div><strong>Connection interrupted</strong><p>{error}</p></div><button onClick={() => submit(undefined, messages.filter(m => m.role === "user").at(-1)?.content)}><RefreshCw size={15} />Retry</button></div>}
          <div ref={endRef} />
        </div>
        <form className="composer" data-tour="composer" onSubmit={submit}>
          <label htmlFor="request-input" className="sr-only">Procurement request</label>
          <textarea id="request-input" value={input} onChange={event => setInput(event.target.value)} maxLength={4000} rows={2} placeholder="Describe a medicine, quantity, destination, and delivery need…" onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(); } }} />
          <button className="send-button" type="submit" disabled={!input.trim() || loading} aria-label="Send procurement request"><ArrowUp size={19} /></button>
          <p>Recommendations require your organization&apos;s approval.</p>
        </form>
      </section>
      <EvidencePanel result={latest} tourId="evidence" />
      {drawer && <div className="drawer-backdrop" onClick={() => setDrawer(false)}><div className="drawer" onClick={event => event.stopPropagation()}><EvidencePanel result={latest} close={() => setDrawer(false)} /></div></div>}
    </main>}
    {screen === "reviews" && <Reviews />}
    {screen === "supplierReviews" && <SupplierSubmissionReviews />}
    {screen === "operations" && <OperationsScreen />}
    <div className="toast-region" aria-live="polite" aria-label="Request notifications">{notices.map(notice => <div className={`toast toast-${notice.tone}`} key={notice.id} role="status"><span className="toast-indicator"/><div><strong>{notice.title}</strong><p>{notice.detail}</p></div><button onClick={() => setNotices(current => current.filter(item => item.id !== notice.id))} aria-label={`Dismiss ${notice.title}`}><X size={15}/></button></div>)}</div>
    {tourStep !== null && <ProductTour user={user} stepIndex={tourStep} onStep={setTourStep} onNavigate={navigate} onClose={closeTour} />}
  </div>;
}

function Brand() { return <div className="brand"><div className="brand-mark">P</div><div><strong>Procura</strong><span>Procurement operations</span></div></div>; }
function Nav({ screen, setScreen, onNew, onGuide, user, onLogout }: { screen: Screen; setScreen: (s: Screen) => void; onNew: () => void; onGuide: () => void; user: AuthUser; onLogout: () => void }) {
  const items: [Screen, string, typeof MessageSquareText][] = [["dashboard", "Dashboard", LayoutDashboard], ["chat", "Workspace", MessageSquareText], ["reviews", "Request reviews", ClipboardCheck], ["supplierReviews", "Supplier approvals", Building2], ["operations", "Operations", Activity]];
  const visible = user.role === "supplier" ? [["supplier", "Supplier portal", Building2]] as [Screen, string, typeof MessageSquareText][] : user.role === "buyer" ? items.filter(([id]) => !["reviews", "supplierReviews", "operations"].includes(id)) : items;
  return <nav className={`side-nav nav-${user.role}`} aria-label="Primary navigation"><Brand />{user.role !== "supplier" && <button className="new-button" data-tour="new-request" onClick={onNew}><Plus size={17} />New request</button>}<div className="nav-items">{visible.map(([id, label, Icon]) => <button key={id} data-tour={`nav-${id}`} aria-current={screen === id ? "page" : undefined} onClick={() => setScreen(id)}><Icon size={18} /><span>{label}</span></button>)}</div><button className="guide-button" onClick={onGuide} aria-label="Product guide"><CircleHelp size={17} /><span>Product guide</span></button><div className="account-card"><span>{user.display_name}</span><small>{user.role}</small><button onClick={onLogout} aria-label="Sign out"><LogOut size={15} /></button></div><div className="nav-footer"><Shield size={16} /><span>Policy<br/><strong>procura-policy-v1</strong></span></div></nav>;
}
function EmptyState({ onExample }: { onExample: (s: string) => void }) { return <div className="empty-state"><div className="empty-icon"><FileSearch size={25} /></div><h2>Start with a procurement need</h2><p>Procura structures the requirement, compares supplier quotations, and sends exceptions to the right reviewer.</p><div className="examples"><span>Try an example</span>{examples.map((example, i) => <button key={example} onClick={() => onExample(example)}><span>0{i + 1}</span>{i === 0 ? "Paracetamol comparison" : i === 1 ? "Cold-chain insulin" : "Ceftriaxone clarification"}<Send size={14} /></button>)}</div></div>; }

function tourSteps(role: AuthUser["role"]): TourStep[] {
  if (role === "supplier") return [
    { title: "Welcome to your supplier workspace", description: "Keep your market coverage, authorization evidence, capabilities, and quotations visible to procurement teams.", screen: "supplier" },
    { title: "Your account at a glance", description: "Start here to see active quotations, supported destinations, reliability, and cold-chain capability.", screen: "supplier", target: "supplier-overview" },
    { title: "Keep evidence current", description: "Review the authorization and market evidence used when Procura evaluates your quotations.", screen: "supplier", target: "supplier-compliance" },
    { title: "Review submitted quotations", description: "Confirm the medicine, pack format, delivery lead time, and price currently available to buyers.", screen: "supplier", target: "supplier-quotes" }
  ];
  const steps: TourStep[] = [
    { title: `Welcome to Procura`, description: "Here is the quickest path from a medicine requirement to a clear, reviewable supplier decision.", screen: "dashboard" },
    { title: "Start from the dashboard", description: "See request volume, recommendations, review handoffs, and your most recent decisions in one place.", screen: "dashboard", target: "dashboard" },
    { title: "Open the procurement workspace", description: "Select Workspace whenever you want to describe a new need or continue a procurement review.", screen: "dashboard", target: "nav-chat" },
    { title: "Describe the complete requirement", description: "Enter the medicine, strength, form, quantity, pack size, destination, deadline, and currency in ordinary language.", screen: "chat", target: "composer" },
    { title: "Follow the decision evidence", description: "Supplier checks, exclusions, policy details, and the decision record remain visible beside the conversation.", screen: "chat", target: "evidence" }
  ];
  if (role === "reviewer" || role === "admin") steps.push(
    { title: "Resolve exceptions", description: "Staff review collects every blocked or uncertain case with the evidence needed to approve, reject, or request clarification.", screen: "reviews", target: "reviews" },
    { title: "Monitor the workflow", description: "Operations shows actual request outcomes, review volume, latency, evaluations, and recent workflow activity.", screen: "operations", target: "operations" }
  );
  return steps;
}

function ProductTour({ user, stepIndex, onStep, onNavigate, onClose }: { user: AuthUser; stepIndex: number; onStep: (step: number) => void; onNavigate: (screen: Screen) => void; onClose: () => void }) {
  const steps = tourSteps(user.role);
  const step = steps[Math.min(stepIndex, steps.length - 1)];
  const cardRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    onNavigate(step.screen);
    let highlighted: HTMLElement | null = null;
    const timer = window.setTimeout(() => {
      highlighted = step.target ? document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`) : null;
      highlighted?.classList.add("tour-focus");
      highlighted?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      cardRef.current?.focus();
    }, 120);
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", escape);
    return () => { window.clearTimeout(timer); highlighted?.classList.remove("tour-focus"); window.removeEventListener("keydown", escape); };
  }, [step.screen, step.target, onNavigate, onClose]);
  const last = stepIndex === steps.length - 1;
  return <div className={`tour-layer ${stepIndex === 0 ? "tour-welcome" : ""}`}>
    <div className="tour-card" role="dialog" aria-labelledby="tour-title" aria-describedby="tour-description" aria-modal={stepIndex === 0 ? "true" : "false"} tabIndex={-1} ref={cardRef}>
      <div className="tour-top"><span>Product guide</span><button onClick={onClose} aria-label="Close product guide"><X size={17} /></button></div>
      <div className="tour-progress" aria-label={`Step ${stepIndex + 1} of ${steps.length}`}>{steps.map((_, index) => <span key={index} className={index <= stepIndex ? "active" : ""} />)}</div>
      <p className="tour-count">{String(stepIndex + 1).padStart(2, "0")} / {String(steps.length).padStart(2, "0")}</p>
      <h2 id="tour-title">{step.title}</h2>
      <p id="tour-description">{step.description}</p>
      <div className="tour-actions">{stepIndex > 0 ? <button className="tour-back" onClick={() => onStep(stepIndex - 1)}><ChevronLeft size={15} />Back</button> : <button className="tour-skip" onClick={onClose}>Maybe later</button>}<button className="tour-next" onClick={() => last ? onClose() : onStep(stepIndex + 1)}>{last ? "Finish" : stepIndex === 0 ? "Show me around" : "Next"}<ArrowRight size={15} /></button></div>
    </div>
  </div>;
}

function Reviews() {
  const [cases, setCases] = useState<ReviewCase[]>([]); const [selected, setSelected] = useState<ReviewCase>(); const [error, setError] = useState(false);
  const load = () => api.reviews().then(items => { setCases(items); setSelected(current => items.find(x => x.id === current?.id) || items[0]); }).catch(() => setError(true));
  useEffect(() => { load(); }, []);
  async function decide(action: "approve" | "reject" | "request_clarification") { if (!selected) return; const updated = await api.decideReview(selected.id, action, `Reviewed in Procura: ${action}`); setSelected(updated); load(); }
  return <main className="page-shell" data-tour="reviews"><header className="page-head"><div><p className="eyebrow">Human in the loop</p><h1>Staff review</h1><p>Resolve escalations without triggering orders or supplier communication.</p></div><StatusBadge status="review" /></header>
    {error ? <div className="error-state"><TriangleAlert /><p>Review data is unavailable.</p></div> : cases.length === 0 ? <div className="blank-panel"><ClipboardCheck size={28} /><h2>No open review cases</h2><p>Unsafe procurement workflows will appear here.</p></div> : <div className="review-layout"><aside className="case-list" aria-label="Review cases">{cases.map(item => <button key={item.id} className={selected?.id === item.id ? "selected" : ""} onClick={() => setSelected(item)}><span className={`case-status ${item.status}`} /> <div><strong>{item.request.medicine.medicine_name || "Incomplete request"}</strong><small>{item.reasons[0]}</small></div><time>{new Date(item.created_at).toLocaleDateString()}</time></button>)}</aside>{selected && <section className="case-detail"><div className="case-title"><div><span>Case {selected.id.slice(0, 8)}</span><h2>{selected.request.medicine.medicine_name || "Incomplete procurement request"}</h2></div><span className={`state-label ${selected.status}`}>{selected.status.replaceAll("_", " ")}</span></div><div className="review-callout"><TriangleAlert size={19} /><div><strong>Why review is required</strong><ul>{selected.reasons.map(r => <li key={r}>{r}</li>)}</ul></div></div><div className="review-columns"><div><h3>Request evidence</h3><dl><dt>Strength</dt><dd>{selected.request.medicine.strength || "Missing"}</dd><dt>Destination</dt><dd>{selected.request.destination || "Missing"}</dd><dt>Policy</dt><dd>{selected.policy_version}</dd><dt>Trace</dt><dd><code>{selected.trace_id.slice(0, 12)}…</code></dd></dl></div><div><h3>Supplier evidence</h3>{selected.quotes.slice(0, 3).map(q => <div className="mini-quote" key={q.quote_id}><strong>{q.supplier_id}</strong><span>{q.currency} {q.total_price.toLocaleString()}</span><StatusBadge status={q.eligible ? "eligible" : "ineligible"} /></div>)}</div></div>{selected.status === "open" ? <div className="review-actions"><button className="primary-action" onClick={() => decide("approve")}><Check size={16} />Approve recommendation</button><button onClick={() => decide("request_clarification")}>Request clarification</button><button className="danger-action" onClick={() => decide("reject")}>Reject</button></div> : <div className="audit-record"><Check size={18} /><div><strong>Action recorded</strong><p>{selected.status.replaceAll("_", " ")} · {selected.reviewer_note}</p></div></div>}<p className="fine-print">Staff actions are auditable and do not create a transaction.</p></section>}</div>}
  </main>;
}

function SupplierSubmissionReviews() {
  const [items, setItems] = useState<SupplierSubmission[]>([]); const [selected, setSelected] = useState<SupplierSubmission>(); const [failed, setFailed] = useState(false); const [busy, setBusy] = useState(false);
  const load = useCallback(() => api.supplierSubmissions().then(results => { setItems(results); setSelected(current => results.find(item => item.id === current?.id) || results[0]); setFailed(false); }).catch(() => setFailed(true)), []);
  useEffect(() => { load(); }, [load]);
  async function decide(action: "approve" | "reject") { if (!selected) return; setBusy(true); try { const updated = await api.decideSupplierSubmission(selected.id, action, action === "approve" ? "Supplier evidence verified" : "Supplier evidence rejected"); setSelected(updated); await load(); } finally { setBusy(false); } }
  return <main className="page-shell"><header className="page-head"><div><p className="eyebrow">Supplier governance</p><h1>Supplier approvals</h1><p>Verify profile, authorization, capability, and quotation changes before they enter procurement comparisons.</p></div><StatusBadge status="review" /></header>
    {failed ? <div className="error-state" role="alert">Supplier submissions are unavailable.</div> : items.length === 0 ? <div className="blank-panel"><Building2 size={28}/><h2>No supplier submissions</h2><p>Supplier profile and quotation changes will appear here.</p></div> : <div className="review-layout"><aside className="case-list" aria-label="Supplier submissions">{items.map(item => <button key={item.id} className={selected?.id === item.id ? "selected" : ""} onClick={() => setSelected(item)}><span className={`case-status ${item.status}`}/><div><strong>{item.kind} change</strong><small>{item.status}</small></div><time>{new Date(item.created_at).toLocaleDateString()}</time></button>)}</aside>{selected && <section className="case-detail"><div className="case-title"><div><span>Submission {selected.id.slice(0, 8)}</span><h2>{selected.kind === "profile" ? "Supplier profile update" : "Quotation update"}</h2></div><span className={`state-label ${selected.status}`}>{selected.status}</span></div><div className="submission-evidence"><h3>Submitted evidence</h3><dl>{Object.entries(selected.payload).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{Array.isArray(value) ? value.join(", ") : String(value ?? "Not supplied")}</dd></div>)}</dl></div>{selected.status === "pending" ? <div className="review-actions"><button className="primary-action" onClick={() => decide("approve")} disabled={busy}><Check size={16}/>Approve and publish</button><button className="danger-action" onClick={() => decide("reject")} disabled={busy}>Reject change</button></div> : <div className="audit-record"><Check size={18}/><div><strong>Decision recorded</strong><p>{selected.status} · {selected.reviewer_note}</p></div></div>}<p className="fine-print">Only approved evidence becomes available to buyer comparisons. This action does not place an order.</p></section>}</div>}
  </main>;
}

function OperationsScreen() {
  const [data, setData] = useState<Operations>(); const [error, setError] = useState(false);
  useEffect(() => { api.operations().then(setData).catch(() => setError(true)); }, []);
  if (error) return <main className="page-shell"><div className="error-state">Operations data is unavailable.</div></main>;
  if (!data) return <main className="page-shell"><div className="progress-line"><span className="pulse-dot" />Loading measured operations…</div></main>;
  const metrics = [["Requests", data.request_count], ["Autonomous", data.autonomous_recommendation_count], ["Human review", data.human_review_count], ["Errors", data.error_count], ["p50 latency", data.p50_latency_ms ? `${data.p50_latency_ms} ms` : "Not enough data"], ["p95 latency", data.p95_latency_ms ? `${data.p95_latency_ms} ms` : "Not enough data"], ["Token usage", data.token_usage ?? "Not available"], ["Eval pass rate", data.evaluation_pass_rate != null ? `${Math.round(data.evaluation_pass_rate * 100)}%` : "Not run"]];
  return <main className="page-shell" data-tour="operations"><header className="page-head"><div><p className="eyebrow">System performance</p><h1>Operations</h1><p>Monitor procurement activity, decision outcomes, review volume, and workflow performance.</p></div></header><div className="metric-grid">{metrics.map(([label, value]) => <div className="metric" key={label}><span>{label}</span><strong>{value}</strong></div>)}</div><div className="ops-grid"><section className="data-card"><div className="card-title"><h2>Recent workflow activity</h2><span>{data.recent_traces.length} records</span></div>{data.recent_traces.length ? <div className="trace-list">{data.recent_traces.map(t => <div key={t.trace_id}><code>{t.trace_id.slice(0, 8)}</code><span>{t.decision.replaceAll("_", " ")}</span><strong>{t.latency_ms} ms</strong></div>)}</div> : <p className="muted-block">No workflow activity yet. Complete a request to create the first record.</p>}</section><section className="data-card"><div className="card-title"><h2>System status</h2></div><div className="integration"><span className={data.langfuse_status === "Configured" ? "good-dot" : "neutral-dot"} /><div><strong>Trace export</strong><p>{data.langfuse_status === "Configured" ? "Connected" : "Using local records"}</p></div></div><div className="integration"><span className={data.sentry_status === "Configured" ? "good-dot" : "neutral-dot"} /><div><strong>Error monitoring</strong><p>{data.sentry_status === "Configured" ? "Connected" : "Using local logs"}</p></div></div><p className="fine-print">Procura preserves local workflow records when external monitoring is not connected.</p></section></div></main>;
}

function Landing({ onAuthenticated }: { onAuthenticated: (user: AuthUser) => void }) {
  const [mode, setMode] = useState<"login" | "signup">("signup");
  const [accountType, setAccountType] = useState<"buyer" | "supplier">("buyer");
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const elements = Array.from(document.querySelectorAll<HTMLElement>("[data-reveal]"));
    if (!("IntersectionObserver" in window) || window.matchMedia("(prefers-reduced-motion: reduce)").matches) { elements.forEach(element => element.classList.add("is-visible")); return; }
    const observer = new IntersectionObserver(entries => entries.forEach(entry => { if (entry.isIntersecting) { entry.target.classList.add("is-visible"); observer.unobserve(entry.target); } }), { threshold: .14 });
    elements.forEach(element => observer.observe(element));
    return () => observer.disconnect();
  }, []);
  async function authenticate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setFailure(""); setBusy(true);
    const form = new FormData(event.currentTarget);
    try {
      const email = String(form.get("email") || ""); const password = String(form.get("password") || "");
      const account = mode === "login" ? await api.login(email, password) : await api.signup({ email, password, display_name: String(form.get("name") || ""), organization: String(form.get("organization") || ""), account_type: accountType });
      onAuthenticated(account);
    } catch (error) { setFailure(error instanceof Error ? error.message : "Authentication failed"); }
    finally { setBusy(false); }
  }
  return <main className="landing">
    <nav className="landing-nav"><Brand /><div><a href="#about">How it works</a><a href="#workflow">Workflow</a><button onClick={() => setMode("login")}>Sign in</button></div></nav>
    <section className="hero"><div className="hero-copy"><p className="eyebrow">Medicine procurement, brought into focus</p><h1>Move every request from need to decision.</h1><p>Procura gives buying teams one place to capture medicine requirements, compare qualified supplier quotations, resolve exceptions, and record approvals.</p><div className="trust-row"><span><Check size={15}/>Clear requirements</span><span><Check size={15}/>Comparable quotations</span><span><Check size={15}/>Accountable approvals</span></div></div>
      <section className="auth-card" aria-labelledby="auth-title"><div className="auth-tabs"><button className={mode === "signup" ? "active" : ""} onClick={() => setMode("signup")}>Create account</button><button className={mode === "login" ? "active" : ""} onClick={() => setMode("login")}>Sign in</button></div><h2 id="auth-title">{mode === "signup" ? "Start your workspace" : "Welcome back"}</h2><p>{mode === "signup" ? "Choose the workspace that matches your role." : "Continue to your procurement workspace."}</p>
        <form onSubmit={authenticate}>{mode === "signup" && <><fieldset className="account-type"><legend>Account type</legend><label className={accountType === "buyer" ? "active" : ""}><input type="radio" name="account_type" value="buyer" checked={accountType === "buyer"} onChange={() => setAccountType("buyer")} />Buyer</label><label className={accountType === "supplier" ? "active" : ""}><input type="radio" name="account_type" value="supplier" checked={accountType === "supplier"} onChange={() => setAccountType("supplier")} />Supplier</label></fieldset><label>Full name<input name="name" minLength={2} maxLength={80} autoComplete="name" required /></label><label>Organization<input name="organization" minLength={2} maxLength={120} autoComplete="organization" required /></label></>}<label>Email address<input name="email" type="email" maxLength={320} autoComplete="email" required /></label><label>Password<input name="password" type="password" minLength={12} maxLength={128} autoComplete={mode === "signup" ? "new-password" : "current-password"} required /></label>{mode === "signup" && <small>Use 12 or more characters with upper and lowercase letters, a number, and a symbol.</small>}{failure && <div className="auth-error" role="alert">{failure}</div>}<button className="auth-submit" disabled={busy}>{busy ? "Please wait…" : mode === "signup" ? `Create ${accountType} workspace` : "Sign in"}<ArrowRight size={17}/></button></form>
      </section></section>
    <section className="feature-band" id="about"><article data-reveal><span>01</span><h2>Capture the full requirement</h2><p>Turn a conversation into a complete procurement brief and clarify only what is missing.</p></article><article data-reveal><span>02</span><h2>Compare qualified suppliers</h2><p>See which quotations meet the request, why others were excluded, and which option leads.</p></article><article data-reveal><span>03</span><h2>Resolve exceptions together</h2><p>Give reviewers the evidence, reasons, and recommended action needed to keep work moving.</p></article></section><section className="security-strip" id="workflow" data-reveal><Shield size={26}/><div><h2>A clear path from request to recommendation</h2><p>Procura checks supplier fit, explains every exclusion, ranks eligible quotations, and sends exceptions to the right reviewer so teams can move faster without losing control.</p></div></section><footer>Procura · Procurement decisions, clearly managed</footer>
  </main>;
}

function CustomerDashboard({ onStart }: { onStart: () => void }) {
  const [data, setData] = useState<CustomerDashboardData>(); const [failed, setFailed] = useState(false);
  useEffect(() => { api.customerDashboard().then(setData).catch(() => setFailed(true)); }, []);
  if (failed) return <main className="page-shell"><div className="error-state" role="alert">Dashboard data is unavailable.</div></main>;
  if (!data) return <main className="page-shell"><div className="progress-line" role="status"><span className="pulse-dot" />Loading your workspace…</div></main>;
  return <main className="page-shell"><header className="page-head"><div><p className="eyebrow">Customer workspace</p><h1>Procurement dashboard</h1><p>Track your organization&apos;s requests, recommendations, and review handoffs.</p></div><button className="primary-page-action" onClick={onStart}><Plus size={16}/>Start a request</button></header><div className="metric-grid customer-metrics" data-tour="dashboard"><div className="metric"><span>Requests opened</span><strong>{data.conversation_count}</strong></div><div className="metric"><span>Requests evaluated</span><strong>{data.execution_count}</strong></div><div className="metric"><span>Recommendations</span><strong>{data.recommendation_count}</strong></div><div className="metric"><span>Needs attention</span><strong>{data.review_count}</strong></div></div><section className="dashboard-grid"><article className="data-card"><div className="card-title"><PackageCheck size={17}/><h2>Recent decisions</h2></div>{data.recent_decisions.length ? <div className="decision-list">{data.recent_decisions.map((item, index) => <div key={item.trace_id}><span className="decision-index">{String(index + 1).padStart(2, "0")}</span><div><strong>Procurement review</strong><small>{item.decision.replaceAll("_", " ")}</small></div><StatusBadge status={item.decision === "clarification" ? "clarification" : item.review_required ? "review" : "eligible"}/></div>)}</div> : <div className="dashboard-empty"><FileSearch size={24}/><strong>No procurement decisions yet</strong><p>Start a request to create your first supplier comparison.</p></div>}</article><article className="data-card next-step"><span>Recommended next step</span><h2>Create a procurement review</h2><p>Include medicine, strength, dosage form, packs, destination, delivery need, and currency for the fastest result.</p><button onClick={onStart}>Start a request<ArrowRight size={15}/></button></article></section></main>;
}

function SupplierDashboard() {
  const [data, setData] = useState<SupplierDashboardData>(); const [failed, setFailed] = useState(false); const [saving, setSaving] = useState(false); const [feedback, setFeedback] = useState("");
  const load = useCallback(() => api.supplierDashboard().then(value => { setData(value); setFailed(false); }).catch(() => setFailed(true)), []);
  useEffect(() => { load(); }, [load]);
  async function submitProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setFeedback(""); const form = new FormData(event.currentTarget);
    try { await api.submitSupplierProfile({ display_name:String(form.get("display_name") || ""), destinations:String(form.get("destinations") || "").split(",").map(value => value.trim()).filter(Boolean), cold_chain:form.get("cold_chain") === "on", authorization_expiry:String(form.get("authorization_expiry") || "") }); setFeedback("Profile update submitted for staff verification."); await load(); }
    catch (error) { setFeedback(error instanceof Error ? error.message : "Profile update could not be submitted."); }
    finally { setSaving(false); }
  }
  async function submitQuote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setFeedback(""); const form = new FormData(event.currentTarget);
    try { await api.submitSupplierQuote({ medicine_name:String(form.get("medicine_name") || ""), strength:String(form.get("strength") || ""), dosage_form:String(form.get("dosage_form") || ""), pack_size:Number(form.get("pack_size")), available_quantity_packs:Number(form.get("available_quantity_packs")), unit_price:Number(form.get("unit_price")), currency:String(form.get("currency") || ""), lead_time_days:Number(form.get("lead_time_days")) }); event.currentTarget.reset(); setFeedback("Quotation submitted for staff verification."); await load(); }
    catch (error) { setFeedback(error instanceof Error ? error.message : "Quotation could not be submitted."); }
    finally { setSaving(false); }
  }
  async function withdrawQuote(quote: SupplierDashboardData["supplier"]["quotes"][number]) {
    setSaving(true); setFeedback("");
    try { await api.submitSupplierQuote({ quote_id:quote.id, action:"withdraw", medicine_name:quote.line.medicine_name, strength:quote.line.strength, dosage_form:quote.line.dosage_form, pack_size:quote.line.pack_size, available_quantity_packs:quote.line.quantity_packs, unit_price:quote.line.unit_price, currency:quote.currency, lead_time_days:quote.lead_time_days }); setFeedback("Withdrawal submitted for staff verification."); await load(); }
    catch (error) { setFeedback(error instanceof Error ? error.message : "Withdrawal could not be submitted."); }
    finally { setSaving(false); }
  }
  if (failed) return <main className="page-shell"><div className="error-state" role="alert">Supplier evidence is unavailable or your account is not linked.</div></main>;
  if (!data) return <main className="page-shell"><div className="progress-line" role="status"><span className="pulse-dot" />Loading supplier evidence…</div></main>;
  const supplier = data.supplier;
  const submissions = data.submissions ?? [];
  return <main className="page-shell supplier-page" data-tour="supplier-overview"><header className="page-head"><div><p className="eyebrow">Supplier workspace</p><h1>{supplier.display_name}</h1><p>Maintain the evidence and quotations buyers use in supplier comparisons.</p></div><StatusBadge status={data.compliance_state === "authorized" ? "eligible" : "review"} /></header>
    <div className="metric-grid supplier-metrics"><div className="metric"><span>Active quotations</span><strong>{data.quote_count}</strong></div><div className="metric"><span>Pending changes</span><strong>{submissions.filter(item => item.status === "pending").length}</strong></div><div className="metric"><span>Reliability</span><strong>{Math.round(supplier.reliability_score * 100)}%</strong></div><div className="metric"><span>Cold chain</span><strong>{supplier.capability.cold_chain ? "Capable" : "Not listed"}</strong></div></div>
    {feedback && <div className="supplier-feedback" role="status">{feedback}</div>}
    <div className="supplier-manage-grid"><section className="data-card" data-tour="supplier-compliance"><div className="card-title"><ClipboardCheck size={17}/><h2>Profile and authorization</h2></div><dl className="supplier-evidence"><dt>Authorization</dt><dd>{supplier.authorization.status}</dd><dt>Expiry</dt><dd>{supplier.authorization.expiry_date || "Not recorded"}</dd><dt>Supported markets</dt><dd>{supplier.capability.destinations.join(", ") || "Not recorded"}</dd></dl><form className="management-form" onSubmit={submitProfile}><label>Supplier name<input name="display_name" defaultValue={supplier.display_name} required minLength={2} maxLength={120}/></label><label>Destinations<input name="destinations" defaultValue={supplier.capability.destinations.join(", ")} placeholder="Ghana, Kenya" required/></label><label>Authorization expiry<input name="authorization_expiry" type="date" defaultValue={supplier.authorization.expiry_date || ""} required/></label><label className="check-label"><input name="cold_chain" type="checkbox" defaultChecked={supplier.capability.cold_chain}/>Cold-chain capable</label><button disabled={saving}>Submit profile for verification</button></form></section>
      <section className="data-card" data-tour="supplier-quotes"><div className="card-title"><PackageCheck size={17}/><h2>Active quotations</h2></div>{supplier.quotes.length ? supplier.quotes.map(quote => <div className="supplier-quote" key={quote.id}><div><strong>{quote.line.medicine_name} {quote.line.strength}</strong><span>{quote.line.dosage_form} · pack {quote.line.pack_size} · {quote.line.quantity_packs.toLocaleString()} available · {quote.lead_time_days} days</span></div><strong>{quote.currency} {quote.line.unit_price.toFixed(2)} / pack</strong><button onClick={() => withdrawQuote(quote)} disabled={saving}>Request withdrawal</button></div>) : <p className="muted-block">No verified quotations yet.</p>}
        <form className="management-form quote-form" onSubmit={submitQuote}><h3>Submit a quotation</h3><label>Medicine<input name="medicine_name" required maxLength={120}/></label><label>Strength<input name="strength" required maxLength={40}/></label><label>Dosage form<input name="dosage_form" required maxLength={40}/></label><label>Pack size<input name="pack_size" type="number" min="1" required/></label><label>Available packs<input name="available_quantity_packs" type="number" min="1" required/></label><label>Price per pack<input name="unit_price" type="number" min="0.01" step="0.01" required/></label><label>Currency<input name="currency" defaultValue="USD" minLength={3} maxLength={3} required/></label><label>Lead time (days)<input name="lead_time_days" type="number" min="1" max="365" required/></label><button disabled={saving}>Submit quotation for verification</button></form></section>
    </div>
    <section className="data-card submission-history"><div className="card-title"><h2>Change history</h2><span>{submissions.length} submissions</span></div>{submissions.length ? submissions.map(item => <div key={item.id}><span>{item.kind}</span><strong>{item.status}</strong><time>{new Date(item.created_at).toLocaleDateString()}</time>{item.reviewer_note && <small>{item.reviewer_note}</small>}</div>) : <p className="muted-block">No changes submitted.</p>}</section>
    <div className="supplier-boundary"><Shield size={18}/><p>Changes become active only after staff verification. A quotation submission never creates or confirms an order.</p></div>
  </main>;
}
