"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Activity, ArrowRight, ArrowUp, Bell, Building2, Check, ChevronLeft, ChevronRight, CircleHelp, ClipboardCheck, FileSearch, LayoutDashboard, LogOut, MessageSquareText, PackageCheck, PanelRight, Plus, RefreshCw, Search, Send, Shield, TriangleAlert, UsersRound, WifiOff, X } from "lucide-react";
import { api } from "@/lib/api";
import type { AdminOverview, AdminUserPage, AgentResponse, AuthUser, CustomerDashboard as CustomerDashboardData, DashboardDecision, MedicineCatalogItem, Notification, Operations, ProcurementLifecycle, ReviewBrief, ReviewCase, SupplierDashboard as SupplierDashboardData, SupplierQuoteDraft, SupplierRequestAssignment, SupplierSubmission } from "@/lib/types";
import { DecisionCards, formatReviewReason } from "@/components/DecisionCards";
import { EvidencePanel } from "@/components/EvidencePanel";
import { StatusBadge } from "@/components/StatusBadge";
import { BuyerIntake } from "@/components/BuyerIntake";

type Screen = "dashboard" | "intake" | "chat" | "supplier" | "reviews" | "supplierReviews" | "operations" | "admin";
type TourStep = { title: string; description: string; screen: Screen; target?: string };
type Notice = { id: number; title: string; detail: string; tone: "progress" | "success" | "attention" | "error" };
const examples = [
  "1,500 packs of paracetamol 500 mg tablets, pack size 20, delivered to Accra within 18 days in USD.",
  "300 packs of insulin 100 units/ml vials, pack size 10, cold chain, delivered to Ghana within 21 days in USD.",
  "We need ceftriaxone delivered to Nairobi."
];
const screenRoutes: Record<Screen, string> = { dashboard: "/dashboard", intake: "/intake", chat: "/workspace", reviews: "/reviews", supplierReviews: "/reviews/suppliers", operations: "/operations", admin: "/admin", supplier: "/supplier" };

function medicineLabel(name?: string, strength?: string, fallback = "Incomplete request") {
  if (!name) return fallback;
  const normalizedName = `${name.charAt(0).toUpperCase()}${name.slice(1)}`;
  return strength ? `${normalizedName} ${strength}` : normalizedName;
}

function submissionLabel(item: SupplierSubmission) {
  if (item.kind === "profile") return "Supplier profile update";
  const name = typeof item.payload.medicine_name === "string" ? item.payload.medicine_name : undefined;
  const strength = typeof item.payload.strength === "string" ? item.payload.strength : undefined;
  return medicineLabel(name, strength, "Quotation update");
}

function screenForPath(path: string): Screen | undefined {
  if (path === "/dashboard") return "dashboard";
  if (path === "/intake" || path.startsWith("/intake/")) return "intake";
  if (path === "/workspace" || path.startsWith("/workspace/decisions/")) return "chat";
  if (path === "/reviews/suppliers" || path.startsWith("/reviews/suppliers/")) return "supplierReviews";
  if (path === "/reviews" || path.startsWith("/reviews/")) return "reviews";
  if (path === "/operations" || path.startsWith("/operations/traces/")) return "operations";
  if (path === "/admin") return "admin";
  if (path === "/supplier" || path.startsWith("/supplier/")) return "supplier";
  return undefined;
}

function allowedScreen(user: AuthUser, requested?: Screen): Screen {
  if (user.role === "supplier") return "supplier";
  if (user.role === "reviewer") return requested === "supplierReviews" ? "supplierReviews" : "reviews";
  if (user.role === "admin") return !requested || requested === "supplier" ? "operations" : requested;
  if (!requested || requested === "supplier" || requested === "reviews" || requested === "supplierReviews" || requested === "operations" || requested === "admin") return "dashboard";
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
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const noticeId = useRef(0);

  const navigate = useCallback((next: Screen, replace = false, path = screenRoutes[next]) => {
    setScreen(next);
    if (window.location.pathname !== path) window.history[replace ? "replaceState" : "pushState"]({}, "", path);
  }, []);

  const notify = useCallback((title: string, detail: string, tone: Notice["tone"] = "progress") => {
    const id = ++noticeId.current;
    setNotices(current => [...current, { id, title, detail, tone }]);
    window.setTimeout(() => setNotices(current => current.filter(item => item.id !== id)), 4500);
  }, []);

  const openDecision = useCallback(async (traceId: string, replace = false) => {
    const path = `/workspace/decisions/${encodeURIComponent(traceId)}`;
    navigate("chat", replace, path);
    setError(undefined); setLoading(true); setProgress("Loading saved decision");
    try {
      const result = await api.execution(traceId);
      const conversation = await api.conversation(result.conversation_id);
      setConversationId(result.conversation_id); setLatest(result);
      setMessages(conversation.messages.map(message => ({
        role: message.role,
        content: message.content,
        result: message.id === result.message.id ? result : undefined,
      })));
    } catch {
      setError("This saved decision could not be loaded. It may no longer be available to this account.");
      notify("Decision unavailable", "Return to the dashboard and choose another record.", "error");
    } finally { setProgress(undefined); setLoading(false); }
  }, [navigate, notify]);

  const startNew = async () => {
    setError(undefined); setMessages([]); setLatest(undefined);
    try { setConversationId((await api.createConversation()).id); notify("New request ready", "Describe the medicine and delivery requirement to begin."); }
    catch { setError("The Procura API is offline. Start the backend, then retry."); notify("Request could not be created", "Check the connection and try again.", "error"); }
  };
  useEffect(() => {
    api.me().then(account => {
      setUser(account);
      const requested = screenForPath(window.location.pathname);
      const allowed = allowedScreen(account, requested);
      navigate(allowed, true, allowed === requested ? window.location.pathname : screenRoutes[allowed]);
    }).catch(() => {
      if (window.location.pathname !== "/") window.history.replaceState({}, "", "/");
    }).finally(() => setAuthReady(true));
  }, [navigate]);
  useEffect(() => {
    if (!user) return;
    const syncRoute = () => setScreen(allowedScreen(user, screenForPath(window.location.pathname)));
    window.addEventListener("popstate", syncRoute);
    return () => window.removeEventListener("popstate", syncRoute);
  }, [navigate, user]);
  useEffect(() => {
    if (!user || !["buyer", "admin"].includes(user.role)) return;
    const traceId = window.location.pathname.match(/^\/workspace\/decisions\/([^/]+)$/)?.[1];
    if (!traceId) return;
    const timer = window.setTimeout(() => openDecision(decodeURIComponent(traceId), true), 0);
    return () => window.clearTimeout(timer);
  }, [openDecision, user]);
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
    setError(undefined); setLoading(true); setMessages(current => [...current, { role: "user", content }]);
    notify("Request submitted", "Procura is checking requirements and supplier quotations.");
    let id = conversationId;
    const progressSteps = ["Request understood", "Checking supplier eligibility", "Comparing quotations", "Applying review policy"];
    let progressIndex = 0;
    setProgress(progressSteps[progressIndex]);
    const progressTimer = window.setInterval(() => {
      progressIndex = Math.min(progressIndex + 1, progressSteps.length - 1);
      setProgress(progressSteps[progressIndex]);
    }, 900);
    try {
      if (!id) { id = (await api.createConversation()).id; setConversationId(id); }
      const result = await api.sendMessage(id, content);
      setInput("");
      setProgress(result.decision.status === "recommended" ? "Recommendation ready" : result.decision.status === "clarification" ? "Clarification ready" : "Review handoff ready"); setLatest(result);
      setMessages(current => [...current, { role: "assistant", content: result.message.content, result }]);
      if (result.decision.status === "recommended") notify("Review complete", "An eligible supplier recommendation is ready.", "success");
      else if (result.decision.status === "clarification") notify("More information needed", "Answer the clarification to continue the review.", "attention");
      else notify("Review complete", "The request has been routed for staff attention.", "attention");
    } catch { setError("The request could not be completed. Your text was not lost. Retry when the API is available."); notify("Review interrupted", "Your request is preserved and can be retried.", "error"); }
    finally { window.clearInterval(progressTimer); setTimeout(() => setProgress(undefined), 300); setLoading(false); }
  }

  if (!authReady) return <main className="auth-loading" role="status"><span className="pulse-dot" />Loading Procura…</main>;
  if (!user) return <Landing onAuthenticated={account => { setUser(account); navigate(allowedScreen(account), true); }} />;
  return <div className="app-shell">
    <Nav screen={screen} setScreen={navigate} onNew={() => { navigate("intake"); notify("New request ready", "Enter one requirement or upload a procurement list."); }} onGuide={() => setTourStep(0)} user={user} onLogout={() => api.logout().finally(() => { setUser(undefined); setConversationId(undefined); window.history.replaceState({}, "", "/"); })} />
    {screen === "dashboard" && ["buyer", "admin"].includes(user.role) && <CustomerDashboard onStart={() => { navigate("intake"); notify("New request ready", "Enter one requirement or upload a procurement list."); }} onOpenDecision={traceId => openDecision(traceId)} />}
    {screen === "intake" && ["buyer", "admin"].includes(user.role) && <BuyerIntake onNotice={notify} />}
    {screen === "supplier" && user.role === "supplier" && <SupplierDashboard />}
    {screen === "chat" && ["buyer", "admin"].includes(user.role) && <main className="workspace">
      <header className="mobile-header"><Brand /><button className="icon-button" onClick={() => setDrawer(true)} aria-label="Open decision evidence"><PanelRight size={20} /></button></header>
      <section className="conversation" aria-label="Procurement conversation">
        <div className="conversation-head"><div><p className="eyebrow">Procurement review</p><h1>Describe what you need</h1></div><div className="head-actions"><button className="quiet-button tablet-evidence" onClick={() => setDrawer(true)} aria-label="Open decision evidence"><PanelRight size={16} />Evidence</button><button className="quiet-button desktop-only" onClick={startNew}><Plus size={16} />New request</button></div></div>
        <div className="messages" aria-live="polite">
          {messages.length === 0 && <EmptyState onExample={example => submit(undefined, example)} onCatalogItem={starter => { setInput(starter); window.setTimeout(() => composerRef.current?.focus(), 0); }} />}
          {messages.map((message, index) => <article className={`message ${message.role}`} key={index}>
            <div className="message-label">{message.role === "user" ? "You" : "Procura"}</div>
            <div className="message-body"><p>{message.content}</p>{message.result && <><DecisionCards result={message.result} /><PublishRequestAction result={message.result} /></>}</div>
          </article>)}
          {progress && <div className="progress-line" role="status"><span className="pulse-dot" />{progress}</div>}
          {error && <div className="error-state" role="alert"><WifiOff size={20} /><div><strong>Connection interrupted</strong><p>{error}</p></div><button onClick={() => submit(undefined, messages.filter(m => m.role === "user").at(-1)?.content)}><RefreshCw size={15} />Retry</button></div>}
          <div ref={endRef} />
        </div>
        <form className="composer" data-tour="composer" onSubmit={submit}>
          <label htmlFor="request-input" className="sr-only">Procurement request</label>
          <textarea ref={composerRef} id="request-input" value={input} onChange={event => setInput(event.target.value)} maxLength={4000} rows={2} placeholder="Describe a medicine, quantity, destination, and delivery need…" onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(); } }} />
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
    {screen === "admin" && user.role === "admin" && <AdminControlCenter />}
    <div className="toast-region" aria-live="polite" aria-label="Request notifications">{notices.map(notice => <div className={`toast toast-${notice.tone}`} key={notice.id} role="status"><span className="toast-indicator"/><div><strong>{notice.title}</strong><p>{notice.detail}</p></div><button onClick={() => setNotices(current => current.filter(item => item.id !== notice.id))} aria-label={`Dismiss ${notice.title}`}><X size={15}/></button></div>)}</div>
    {tourStep !== null && <ProductTour user={user} stepIndex={tourStep} onStep={setTourStep} onNavigate={navigate} onClose={closeTour} />}
  </div>;
}

function Brand() { return <div className="brand"><div className="brand-mark">P</div><div><strong>Procura</strong><span>Procurement operations</span></div></div>; }
function Nav({ screen, setScreen, onNew, onGuide, user, onLogout }: { screen: Screen; setScreen: (s: Screen) => void; onNew: () => void; onGuide: () => void; user: AuthUser; onLogout: () => void }) {
  const items: [Screen, string, typeof MessageSquareText][] = [["dashboard", "Dashboard", LayoutDashboard], ["intake", "Buyer intake", FileSearch], ["chat", "Workspace", MessageSquareText], ["reviews", "Request reviews", ClipboardCheck], ["supplierReviews", "Supplier approvals", Building2], ["operations", "Operations", Activity], ["admin", "Administration", UsersRound]];
  const visible = user.role === "supplier" ? [["supplier", "Supplier portal", Building2]] as [Screen, string, typeof MessageSquareText][] : user.role === "buyer" ? items.slice(0, 3) : user.role === "reviewer" ? items.slice(3, 5) : items;
  const canCreateRequest = user.role === "buyer" || user.role === "admin";
  return <nav className={`side-nav nav-${user.role}`} aria-label="Primary navigation"><Brand />{canCreateRequest && <button className="new-button" data-tour="new-request" onClick={onNew}><Plus size={17} />New request</button>}<NotificationCenter/><div className="nav-items">{visible.map(([id, label, Icon]) => <button key={id} aria-label={label} data-tour={`nav-${id}`} aria-current={screen === id ? "page" : undefined} onClick={() => setScreen(id)}><Icon size={18} /><span>{label}</span></button>)}</div><button className="guide-button" onClick={onGuide} aria-label="Product guide"><CircleHelp size={17} /><span>Product guide</span></button><div className="account-card"><span>{user.display_name}</span><small>{user.role === "admin" ? "operations admin" : user.role}</small><button onClick={onLogout} aria-label="Sign out"><LogOut size={15} /></button></div><div className="nav-footer"><Shield size={16} /><span>Policy<br/><strong>procura-policy-v1</strong></span></div></nav>;
}

function NotificationCenter() {
  const [items, setItems] = useState<Notification[]>([]); const [open, setOpen] = useState(false);
  const load = useCallback(() => api.notifications().then(setItems).catch(() => undefined), []);
  useEffect(() => { load(); }, [load]);
  const unread = items.filter(item => !item.is_read).length;
  async function markRead(item: Notification) { if (!item.is_read) await api.readNotification(item.id); await load(); }
  return <div className="notification-center"><button type="button" className="notification-trigger" aria-label="Notifications" aria-expanded={open} aria-controls="notification-list" onClick={() => setOpen(value => !value)}><Bell size={17}/><span>Notifications</span>{unread > 0 && <strong aria-label={`${unread} unread notifications`}>{unread}</strong>}</button>{open && <section id="notification-list" className="notification-panel" aria-label="Notifications"><div><h2>Notifications</h2><button onClick={() => setOpen(false)} aria-label="Close notifications"><X size={14}/></button></div>{items.length ? items.map(item => <button type="button" key={item.id} className={item.is_read ? "read" : "unread"} onClick={() => markRead(item)}><strong>{item.title}</strong><span>{item.message}</span><time>{new Date(item.created_at).toLocaleString()}</time></button>) : <p>No notifications yet.</p>}</section>}</div>;
}

function PublishRequestAction({ result }: { result: AgentResponse }) {
  const [published, setPublished] = useState<ProcurementLifecycle>(); const [busy, setBusy] = useState(false); const [failure, setFailure] = useState("");
  if (["clarification", "failed_safe"].includes(result.decision.status)) return null;
  async function publish() { setBusy(true); setFailure(""); try { setPublished(await api.publishExecution(result.decision.trace_id)); } catch (error) { setFailure(error instanceof Error ? error.message : "The request could not be opened to suppliers."); } finally { setBusy(false); } }
  return <section className="publish-request" aria-live="polite"><div><strong>{published ? "Open for supplier responses" : "Ready for supplier responses"}</strong><p>{published ? `${published.invited_supplier_count} matching supplier${published.invited_supplier_count === 1 ? "" : "s"} can now respond in Procura.` : "Open this request in the supplier portal. This does not place an order."}</p></div>{published ? <StatusBadge status="eligible"/> : <button type="button" onClick={publish} disabled={busy}>{busy ? "Opening request…" : "Open to matching suppliers"}<ArrowRight size={14}/></button>}{failure && <p className="inline-error" role="alert">{failure}</p>}</section>;
}
function EmptyState({ onExample, onCatalogItem }: { onExample: (s: string) => void; onCatalogItem: (s: string) => void }) {
  const [catalog, setCatalog] = useState<MedicineCatalogItem[]>([]);
  const [query, setQuery] = useState("");
  const [catalogOpen, setCatalogOpen] = useState(false);
  const [catalogError, setCatalogError] = useState(false);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const searchSequence = useRef(0);
  const catalogRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!catalogOpen) return;
    const sequence = ++searchSequence.current;
    const timer = window.setTimeout(() => {
      setCatalogLoading(true); setCatalogError(false);
      api.medicineCatalog(query.trim(), 20).then(items => {
        if (sequence === searchSequence.current) setCatalog(items);
      }).catch(() => {
        if (sequence === searchSequence.current) setCatalogError(true);
      }).finally(() => {
        if (sequence === searchSequence.current) setCatalogLoading(false);
      });
    }, query ? 220 : 0);
    return () => window.clearTimeout(timer);
  }, [query, catalogOpen]);
  useEffect(() => {
    const close = (event: PointerEvent) => {
      if (catalogRef.current && !catalogRef.current.contains(event.target as Node)) setCatalogOpen(false);
    };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, []);
  const chooseCatalogItem = (starter: string) => { setCatalogOpen(false); onCatalogItem(starter); };
  return <div className="empty-state catalog-empty">
    <div className="workspace-intro"><span>Start a request</span><h2>Find current supplier coverage</h2><p>Search by medicine, strength, or dosage form. You can also write any procurement need directly below.</p></div>
    <section className={`catalog-panel ${catalogOpen ? "is-open" : ""}`} data-tour="catalog" aria-labelledby="catalog-heading" ref={catalogRef}>
      <div className="catalog-head"><div><span>Medicine search</span><h3 id="catalog-heading">Choose a product variant</h3></div><small>{catalogOpen ? "Scroll or type to filter" : "Select search to browse"}</small></div>
      <label className="catalog-search"><Search size={18}/><span className="sr-only">Search available medicines</span><input type="search" role="combobox" aria-expanded={catalogOpen} aria-controls="medicine-search-results" aria-autocomplete="list" value={query} onFocus={() => setCatalogOpen(true)} onClick={() => setCatalogOpen(true)} onChange={event => { setQuery(event.target.value); setCatalogOpen(true); }} onKeyDown={event => { if (event.key === "Escape") { setCatalogOpen(false); event.currentTarget.blur(); } }} placeholder="Search medicine, strength, or form" autoComplete="off"/></label>
      {catalogOpen && <div className="catalog-popover" id="medicine-search-results" role="listbox" aria-label="Medicine search results"><div className="catalog-status" role="status">{catalogLoading ? "Searching current quotations…" : query ? `${catalog.length} matching variant${catalog.length === 1 ? "" : "s"}` : `${catalog.length} available variants`}<span>Scroll for more results.</span></div>
      {catalogError ? <p className="catalog-message" role="alert">Medicine availability could not be loaded. You can still describe the request below.</p> : !catalogLoading && catalog.length === 0 ? <p className="catalog-message">No active quotation matches this search. You can still type the medicine into your request.</p> : <div className="catalog-results">{catalog.map(item => <article role="option" aria-selected="false" tabIndex={0} onClick={() => chooseCatalogItem(item.request_starter)} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); chooseCatalogItem(item.request_starter); } }} key={`${item.medicine_name}-${item.strength}-${item.dosage_form}-${item.pack_size}`}>
        <div className="catalog-result-name"><strong>{item.medicine_name}</strong><span>{item.strength} · {item.dosage_form} · pack {item.pack_size}</span></div>
        <div className={`catalog-result-evidence ${item.authorized_supplier_count === 0 ? "needs-review" : ""}`}><span>{item.authorized_supplier_count === 0 ? "No verified supplier" : `${item.authorized_supplier_count} verified supplier${item.authorized_supplier_count === 1 ? "" : "s"}`}</span><span>{item.quotation_count} quotation{item.quotation_count === 1 ? "" : "s"}</span><span>{item.minimum_lead_time_days} day fastest</span></div>
        <span className="catalog-result-action">Use in request<ArrowRight size={14}/></span>
      </article>)}</div>}</div>}
    </section>
    <div className="examples compact-examples"><span>Complete examples</span>{examples.map((example, i) => <button key={example} onClick={() => onExample(example)}><span>0{i + 1}</span>{i === 0 ? "Paracetamol" : i === 1 ? "Cold-chain insulin" : "Needs clarification"}<Send size={13} /></button>)}</div>
  </div>;
}

function tourSteps(role: AuthUser["role"]): TourStep[] {
  if (role === "supplier") return [
    { title: "Welcome to your supplier workspace", description: "Keep your market coverage, authorization evidence, capabilities, and quotations visible to procurement teams.", screen: "supplier" },
    { title: "Your account at a glance", description: "Start here to see active quotations, supported destinations, reliability, and cold-chain capability.", screen: "supplier", target: "supplier-overview" },
    { title: "Keep evidence current", description: "Review the authorization and market evidence used when Procura evaluates your quotations.", screen: "supplier", target: "supplier-compliance" },
    { title: "Review submitted quotations", description: "Confirm the medicine, pack format, delivery lead time, and price currently available to buyers.", screen: "supplier", target: "supplier-quotes" }
  ];
  if (role === "reviewer") return [
    { title: "Welcome to the review workspace", description: "Resolve procurement exceptions and verify supplier evidence without operational administration access.", screen: "reviews" },
    { title: "Resolve request exceptions", description: "Inspect the request, tool evidence, escalation reasons, and recommendation before recording a decision.", screen: "reviews", target: "reviews" },
    { title: "Verify supplier evidence", description: "Approve or reject profile and quotation changes before they become available to buyer comparisons.", screen: "supplierReviews", target: "supplier-reviews" }
  ];
  const steps: TourStep[] = [
    { title: `Welcome to Procura`, description: "Here is the quickest path from a medicine requirement to a clear, reviewable supplier decision.", screen: "dashboard" },
    { title: "Start from the dashboard", description: "See request volume, recommendations, review handoffs, and your most recent decisions in one place.", screen: "dashboard", target: "dashboard" },
    { title: "Open the procurement workspace", description: "Select Workspace whenever you want to describe a new need or continue a procurement review.", screen: "dashboard", target: "nav-chat" },
    { title: "Search current medicine coverage", description: "Search a focused set of medicine variants with active quotations, then place verified product facts into your request.", screen: "chat", target: "catalog" },
    { title: "Describe the complete requirement", description: "Enter the medicine, strength, form, quantity, pack size, destination, deadline, and currency in ordinary language.", screen: "chat", target: "composer" },
    { title: "Follow the decision evidence", description: "Supplier checks, exclusions, policy details, and the decision record remain visible beside the conversation.", screen: "chat", target: "evidence" }
  ];
  if (role === "admin") steps.push(
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
  const [cases, setCases] = useState<ReviewCase[]>([]); const [selected, setSelected] = useState<ReviewCase>(); const [brief, setBrief] = useState<ReviewBrief>(); const [briefLoading, setBriefLoading] = useState(false); const [decisionError, setDecisionError] = useState(""); const [error, setError] = useState(false);
  const chooseCase = (item: ReviewCase | undefined, updateUrl = true) => { setSelected(item); setBrief(undefined); if (!item) return; if (updateUrl) window.history.pushState({}, "", `/reviews/${item.id}`); setBriefLoading(true); api.reviewBrief(item.id).then(setBrief).catch(() => setBrief(undefined)).finally(() => setBriefLoading(false)); };
  const load = () => api.reviews().then(items => { setCases(items); setSelected(current => { const routeId = window.location.pathname.match(/^\/reviews\/([^/]+)$/)?.[1]; const next = items.find(x => x.id === routeId) || items.find(x => x.id === current?.id) || items[0]; if (next) { setBriefLoading(true); api.reviewBrief(next.id).then(setBrief).catch(() => setBrief(undefined)).finally(() => setBriefLoading(false)); } return next; }); }).catch(() => setError(true));
  useEffect(() => { load(); }, []);
  async function decide(action: "approve" | "reject" | "request_clarification") { if (!selected) return; setDecisionError(""); try { const updated = await api.decideReview(selected.id, action, `Reviewed in Procura: ${action}`); setSelected(updated); load(); } catch (error) { setDecisionError(error instanceof Error ? error.message : "The review action could not be recorded."); await load(); } }
  return <main className="page-shell" data-tour="reviews"><header className="page-head"><div><p className="eyebrow">Human in the loop</p><h1>Staff review</h1><p>Resolve escalations without triggering orders or supplier communication.</p></div><StatusBadge status="review" /></header>
    {error ? <div className="error-state"><TriangleAlert /><p>Review data is unavailable.</p></div> : cases.length === 0 ? <div className="blank-panel"><ClipboardCheck size={28} /><h2>No open review cases</h2><p>Unsafe procurement workflows will appear here.</p></div> : <div className="review-layout"><aside className="case-list" aria-label="Review cases">{cases.map(item => <button key={item.id} className={selected?.id === item.id ? "selected" : ""} onClick={() => chooseCase(item)}><span className={`case-status ${item.status}`} /> <div><strong>{medicineLabel(item.request.medicine.medicine_name, item.request.medicine.strength)}</strong><small>{formatReviewReason(item.reasons[0])}</small></div><time>{new Date(item.created_at).toLocaleDateString()}</time></button>)}</aside>{selected && <section className="case-detail"><div className="case-title"><div><span>Case {selected.id.slice(0, 8)}</span><h2>{medicineLabel(selected.request.medicine.medicine_name, selected.request.medicine.strength, "Incomplete procurement request")}</h2></div><span className={`state-label ${selected.status}`}>{selected.status.replaceAll("_", " ")}</span></div>{decisionError && <div className="error-state compact-error" role="alert"><TriangleAlert size={18}/><p>{decisionError}</p></div>}{briefLoading ? <div className="brief-card" role="status">Preparing an evidence brief…</div> : brief && <div className="brief-card"><div><span>Review brief</span><strong>Suggested: {brief.suggested_action.replaceAll("_", " ")}</strong></div><p>{brief.summary}</p><ul>{brief.evidence_points.map(point => <li key={point}>{formatReviewReason(point)}</li>)}</ul><small>{brief.suggestion_reason} A reviewer must make the final decision.</small></div>}<div className="review-callout"><TriangleAlert size={19} /><div><strong>Why review is required</strong><ul>{selected.reasons.map(r => <li key={r}>{formatReviewReason(r)}</li>)}</ul></div></div><div className="review-columns"><div><h3>Request evidence</h3><dl><dt>Strength</dt><dd>{selected.request.medicine.strength || "Missing"}</dd><dt>Destination</dt><dd>{selected.request.destination || "Missing"}</dd><dt>Policy</dt><dd>{selected.policy_version}</dd><dt>Trace</dt><dd><code>{selected.trace_id.slice(0, 12)}…</code></dd></dl></div><div><h3>Supplier evidence</h3>{selected.quotes.slice(0, 3).map(q => <div className="mini-quote" key={q.quote_id}><strong>{q.supplier_id}</strong><span>{q.currency} {q.total_price.toLocaleString()}</span><StatusBadge status={q.eligible ? "eligible" : "ineligible"} /></div>)}</div></div>{selected.status === "open" ? <div className="review-actions">{selected.recommendation_supplier_id && <button className="primary-action" onClick={() => decide("approve")}><Check size={16} />Approve recommendation</button>}<button onClick={() => decide("request_clarification")}>Request clarification</button><button className="danger-action" onClick={() => decide("reject")}>Reject</button></div> : <div className="audit-record"><Check size={18} /><div><strong>Action recorded</strong><p>{selected.status.replaceAll("_", " ")} · {selected.reviewer_note}</p></div></div>}<p className="fine-print">Current supplier evidence is revalidated before approval. Staff actions are auditable and do not create a transaction.</p></section>}</div>}
  </main>;
}

function SupplierSubmissionReviews() {
  const [items, setItems] = useState<SupplierSubmission[]>([]); const [selected, setSelected] = useState<SupplierSubmission>(); const [failed, setFailed] = useState(false); const [busy, setBusy] = useState(false);
  const load = useCallback(() => api.supplierSubmissions().then(results => { setItems(results); setSelected(current => { const routeId = window.location.pathname.match(/^\/reviews\/suppliers\/([^/]+)$/)?.[1]; return results.find(item => item.id === routeId) || results.find(item => item.id === current?.id) || results[0]; }); setFailed(false); }).catch(() => setFailed(true)), []);
  useEffect(() => { load(); }, [load]);
  async function decide(action: "approve" | "reject") { if (!selected) return; setBusy(true); try { const updated = await api.decideSupplierSubmission(selected.id, action, action === "approve" ? "Supplier evidence verified" : "Supplier evidence rejected"); setSelected(updated); await load(); } finally { setBusy(false); } }
  return <main className="page-shell" data-tour="supplier-reviews"><header className="page-head"><div><p className="eyebrow">Supplier governance</p><h1>Supplier approvals</h1><p>Verify profile, authorization, capability, and quotation changes before they enter procurement comparisons.</p></div><StatusBadge status="review" /></header>
    {failed ? <div className="error-state" role="alert">Supplier submissions are unavailable.</div> : items.length === 0 ? <div className="blank-panel"><Building2 size={28}/><h2>No supplier submissions</h2><p>Supplier profile and quotation changes will appear here.</p></div> : <div className="review-layout"><aside className="case-list" aria-label="Supplier submissions">{items.map(item => <button key={item.id} className={selected?.id === item.id ? "selected" : ""} onClick={() => { setSelected(item); window.history.pushState({}, "", `/reviews/suppliers/${item.id}`); }}><span className={`case-status ${item.status}`}/><div><strong>{submissionLabel(item)}</strong><small>{item.status}</small></div><time>{new Date(item.created_at).toLocaleDateString()}</time></button>)}</aside>{selected && <section className="case-detail"><div className="case-title"><div><span>Submission {selected.id.slice(0, 8)}</span><h2>{submissionLabel(selected)}</h2></div><span className={`state-label ${selected.status}`}>{selected.status}</span></div><div className="submission-evidence"><h3>Submitted evidence</h3><dl>{Object.entries(selected.payload).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{Array.isArray(value) ? value.join(", ") : String(value ?? "Not supplied")}</dd></div>)}</dl></div>{selected.status === "pending" ? <div className="review-actions"><button className="primary-action" onClick={() => decide("approve")} disabled={busy}><Check size={16}/>Approve and publish</button><button className="danger-action" onClick={() => decide("reject")} disabled={busy}>Reject change</button></div> : <div className="audit-record"><Check size={18}/><div><strong>Decision recorded</strong><p>{selected.status} · {selected.reviewer_note}</p></div></div>}<p className="fine-print">Only approved evidence becomes available to buyer comparisons. This action does not place an order.</p></section>}</div>}
  </main>;
}

function OperationsScreen() {
  const [data, setData] = useState<Operations>(); const [selectedTrace, setSelectedTrace] = useState<DashboardDecision>(); const [error, setError] = useState(false);
  useEffect(() => { api.operations().then(result => { setData(result); const routeId = window.location.pathname.match(/^\/operations\/traces\/([^/]+)$/)?.[1]; setSelectedTrace(result.recent_traces.find(trace => trace.trace_id === routeId)); }).catch(() => setError(true)); }, []);
  if (error) return <main className="page-shell"><div className="error-state">Operations data is unavailable.</div></main>;
  if (!data) return <main className="page-shell"><div className="progress-line"><span className="pulse-dot" />Loading measured operations…</div></main>;
  const metrics = [["Intakes", data.intake_count ?? 0], ["Ready", data.intake_ready_count ?? 0], ["Submitted", data.intake_submitted_count ?? 0], ["Time to valid", data.median_time_to_valid_submission_ms ? `${Math.round(data.median_time_to_valid_submission_ms / 1000)} s median` : "Not enough data"], ["Requests", data.request_count], ["Human review", data.human_review_count], ["p95 latency", data.p95_latency_ms ? `${data.p95_latency_ms} ms` : "Not enough data"], ["Eval pass rate", data.evaluation_pass_rate != null ? `${Math.round(data.evaluation_pass_rate * 100)}%` : "Not run"]];
  return <main className="page-shell" data-tour="operations"><header className="page-head"><div><p className="eyebrow">System performance</p><h1>Operations</h1><p>Monitor procurement activity, decision outcomes, review volume, and workflow performance.</p></div></header><div className="metric-grid">{metrics.map(([label, value]) => <div className="metric" key={label}><span>{label}</span><strong>{value}</strong></div>)}</div><div className="ops-grid"><section className="data-card"><div className="card-title"><h2>Recent workflow activity</h2><span>{data.recent_traces.length} records</span></div>{data.recent_traces.length ? <div className="trace-list">{data.recent_traces.map(t => <button type="button" className={selectedTrace?.trace_id === t.trace_id ? "selected" : ""} key={t.trace_id} onClick={() => { setSelectedTrace(t); window.history.pushState({}, "", `/operations/traces/${t.trace_id}`); }} aria-label={`Open ${medicineLabel(t.medicine_name, t.strength)} trace`}><span><strong>{medicineLabel(t.medicine_name, t.strength)}</strong><small>{t.decision.replaceAll("_", " ")} · {t.trace_id.slice(0, 8)}</small></span><strong>{t.latency_ms} ms</strong><ArrowRight size={14}/></button>)}</div> : <p className="muted-block">No workflow activity yet. Complete a request to create the first record.</p>}{selectedTrace && <div className="trace-detail" aria-live="polite"><div className="card-title"><h3>{medicineLabel(selectedTrace.medicine_name, selectedTrace.strength, "Trace evidence")}</h3><button type="button" onClick={() => { setSelectedTrace(undefined); window.history.pushState({}, "", "/operations"); }} aria-label="Close trace evidence"><X size={14}/></button></div><dl><div><dt>Trace ID</dt><dd><code>{selectedTrace.trace_id}</code></dd></div><div><dt>Provider</dt><dd>{selectedTrace.provider} · {selectedTrace.model}</dd></div><div><dt>Decision</dt><dd>{selectedTrace.decision.replaceAll("_", " ")}</dd></div><div><dt>Policy</dt><dd>{selectedTrace.policy_version}</dd></div><div><dt>Tokens</dt><dd>{selectedTrace.token_input ?? "Not available"} in · {selectedTrace.token_output ?? "Not available"} out</dd></div><div><dt>Tool calls</dt><dd>{selectedTrace.tool_sequence.length}</dd></div></dl></div>}</section><section className="data-card"><div className="card-title"><h2>System status</h2></div><div className="integration"><span className={data.langfuse_status === "Configured" ? "good-dot" : "neutral-dot"} /><div><strong>Trace export</strong><p>{data.langfuse_status === "Configured" ? "Connected" : "Using local records"}</p></div></div><div className="integration"><span className={data.sentry_status === "Configured" ? "good-dot" : "neutral-dot"} /><div><strong>Error monitoring</strong><p>{data.sentry_status === "Configured" ? "Connected" : "Using local logs"}</p></div></div><p className="fine-print">Procura preserves local workflow records when external monitoring is not connected.</p></section></div></main>;
}

function AdminControlCenter() {
  const [overview, setOverview] = useState<AdminOverview>();
  const [users, setUsers] = useState<AdminUserPage>();
  const [medicines, setMedicines] = useState<MedicineCatalogItem[]>([]);
  const [userQuery, setUserQuery] = useState("");
  const [role, setRole] = useState("");
  const [status, setStatus] = useState("");
  const [medicineQuery, setMedicineQuery] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");
  const [loadingUsers, setLoadingUsers] = useState(true);
  const [loadingMedicines, setLoadingMedicines] = useState(true);

  useEffect(() => { api.adminOverview().then(setOverview).catch(() => setError("Administrative data is unavailable.")); }, []);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setLoadingUsers(true);
      api.adminUsers(userQuery.trim(), role, status, page, 20).then(setUsers).catch(() => setError("User accounts could not be loaded.")).finally(() => setLoadingUsers(false));
    }, userQuery ? 220 : 0);
    return () => window.clearTimeout(timer);
  }, [userQuery, role, status, page]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setLoadingMedicines(true);
      api.medicineCatalog(medicineQuery.trim(), 20).then(setMedicines).catch(() => setError("Medicine coverage could not be loaded.")).finally(() => setLoadingMedicines(false));
    }, medicineQuery ? 220 : 0);
    return () => window.clearTimeout(timer);
  }, [medicineQuery]);

  const metrics = overview ? [
    ["User accounts", overview.total_users],
    ["Active accounts", overview.active_users],
    ["Suppliers", overview.supplier_count],
    ["Medicines", overview.medicine_count],
    ["Product variants", overview.medicine_variant_count],
    ["Quotations", overview.quotation_count],
    ["Open reviews", overview.open_review_count],
    ["Pending supplier changes", overview.pending_supplier_submission_count],
  ] : [];
  const totalPages = users ? Math.max(1, Math.ceil(users.total / users.limit)) : 1;
  return <main className="page-shell admin-center"><header className="page-head"><div><p className="eyebrow">Workspace administration</p><h1>Control center</h1><p>Inspect account access, supplier coverage, medicine variants, quotations, and work waiting for review.</p></div></header>
    {error && <div className="error-state" role="alert"><TriangleAlert size={18}/><p>{error}</p></div>}
    {!overview ? <div className="progress-line" role="status"><span className="pulse-dot"/>Loading control center…</div> : <><div className="metric-grid admin-metrics">{metrics.map(([label, value]) => <div className="metric" key={label}><span>{label}</span><strong>{value}</strong></div>)}</div><div className="role-summary" aria-label="Accounts by role">{Object.entries(overview.users_by_role).map(([name, count]) => <span key={name}><strong>{count}</strong> {name}{count === 1 ? "" : "s"}</span>)}</div></>}
    <section className="admin-section" aria-labelledby="accounts-heading"><div className="admin-section-head"><div><span>Access directory</span><h2 id="accounts-heading">User accounts</h2></div><small>{users ? `${users.total} matching account${users.total === 1 ? "" : "s"}` : "Loading"}</small></div>
      <div className="admin-filters"><label className="admin-search"><Search size={16}/><span className="sr-only">Search users</span><input type="search" value={userQuery} onChange={event => { setUserQuery(event.target.value); setPage(1); }} placeholder="Search name, email, or organization"/></label><label><span className="sr-only">Filter by role</span><select value={role} onChange={event => { setRole(event.target.value); setPage(1); }}><option value="">All roles</option><option value="buyer">Buyers</option><option value="supplier">Suppliers</option><option value="reviewer">Reviewers</option><option value="admin">Admins</option></select></label><label><span className="sr-only">Filter by account status</span><select value={status} onChange={event => { setStatus(event.target.value); setPage(1); }}><option value="">All statuses</option><option value="active">Active</option><option value="inactive">Inactive</option></select></label></div>
      {loadingUsers ? <div className="admin-empty" role="status">Loading accounts…</div> : !users?.items.length ? <div className="admin-empty">No accounts match these filters.</div> : <div className="admin-table-wrap"><table className="admin-table"><thead><tr><th>Account</th><th>Organization</th><th>Role</th><th>Status</th><th>Created</th></tr></thead><tbody>{users.items.map(item => <tr key={item.id}><td><strong>{item.display_name}</strong><small>{item.email}</small></td><td>{item.organization}</td><td><span className="role-chip">{item.role}</span></td><td><span className={`account-state ${item.is_active ? "active" : "inactive"}`}>{item.is_active ? "Active" : "Inactive"}</span></td><td>{new Date(item.created_at).toLocaleDateString()}</td></tr>)}</tbody></table></div>}
      {users && totalPages > 1 && <div className="admin-pagination"><button disabled={page === 1} onClick={() => setPage(current => current - 1)}><ChevronLeft size={15}/>Previous</button><span>Page {page} of {totalPages}</span><button disabled={page >= totalPages} onClick={() => setPage(current => current + 1)}>Next<ChevronRight size={15}/></button></div>}
    </section>
    <section className="admin-section" aria-labelledby="catalog-admin-heading"><div className="admin-section-head"><div><span>Procurement coverage</span><h2 id="catalog-admin-heading">Medicine variants</h2></div><small>{medicines.length} shown</small></div><label className="admin-search medicine-admin-search"><Search size={16}/><span className="sr-only">Search medicine variants</span><input type="search" value={medicineQuery} onChange={event => setMedicineQuery(event.target.value)} placeholder="Search medicine, strength, or form"/></label>
      {loadingMedicines ? <div className="admin-empty" role="status">Loading medicine coverage…</div> : !medicines.length ? <div className="admin-empty">No medicine variants match this search.</div> : <div className="medicine-admin-grid">{medicines.map(item => <article key={`${item.medicine_name}-${item.strength}-${item.dosage_form}-${item.pack_size}`}><div><strong>{medicineLabel(item.medicine_name, item.strength)}</strong><span>{item.dosage_form} · pack {item.pack_size}</span></div><dl><div><dt>Quotations</dt><dd>{item.quotation_count}</dd></div><div><dt>Verified suppliers</dt><dd>{item.authorized_supplier_count}</dd></div><div><dt>Capacity</dt><dd>{item.available_quantity_packs.toLocaleString()} packs</dd></div><div><dt>Markets</dt><dd>{item.destinations.length ? item.destinations.join(", ") : "Review required"}</dd></div></dl></article>)}</div>}
    </section><p className="fine-print">This view is read-only. Account credentials and session data are never exposed.</p>
  </main>;
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

function CustomerDashboard({ onStart, onOpenDecision }: { onStart: () => void; onOpenDecision: (traceId: string) => void }) {
  const [data, setData] = useState<CustomerDashboardData>(); const [requests, setRequests] = useState<ProcurementLifecycle[]>([]); const [expanded, setExpanded] = useState<string>(); const [failed, setFailed] = useState(false);
  useEffect(() => { Promise.all([api.customerDashboard(), api.procurementRequests().catch(() => [] as ProcurementLifecycle[])]).then(([summary, lifecycles]) => { setData(summary); setRequests(lifecycles); }).catch(() => setFailed(true)); }, []);
  if (failed) return <main className="page-shell"><div className="error-state" role="alert">Dashboard data is unavailable.</div></main>;
  if (!data) return <main className="page-shell"><div className="progress-line" role="status"><span className="pulse-dot" />Loading your workspace…</div></main>;
  return <main className="page-shell"><header className="page-head"><div><p className="eyebrow">Customer workspace</p><h1>Procurement dashboard</h1><p>Track your organization&apos;s requests, recommendations, and review handoffs.</p></div><button className="primary-page-action" onClick={onStart}><Plus size={16}/>Start a request</button></header><div className="metric-grid customer-metrics" data-tour="dashboard"><div className="metric"><span>Requests opened</span><strong>{data.conversation_count}</strong></div><div className="metric"><span>Requests evaluated</span><strong>{data.execution_count}</strong></div><div className="metric"><span>Recommendations</span><strong>{data.recommendation_count}</strong></div><div className="metric"><span>Needs attention</span><strong>{data.review_count}</strong></div></div><section className="dashboard-grid"><article className="data-card"><div className="card-title"><PackageCheck size={17}/><h2>Recent decisions</h2></div>{data.recent_decisions.length ? <div className="decision-list">{data.recent_decisions.map((item, index) => {
    const requestLabel = medicineLabel(item.medicine_name, item.strength);
    const decisionLabel = item.decision.replaceAll("_", " ");
    const detail = [item.dosage_form, decisionLabel].filter(Boolean).join(" · ");
    return <button type="button" key={item.trace_id} onClick={() => onOpenDecision(item.trace_id)} aria-label={`Open ${requestLabel} decision ${index + 1}: ${decisionLabel}`}><span className="decision-index">{String(index + 1).padStart(2, "0")}</span><span><strong>{requestLabel}</strong><small>{detail}</small></span><StatusBadge status={item.decision === "clarification" ? "clarification" : item.review_required ? "review" : "eligible"}/><ArrowRight className="row-arrow" size={15}/></button>;
  })}</div> : <div className="dashboard-empty"><FileSearch size={24}/><strong>No procurement decisions yet</strong><p>Start a request to create your first supplier comparison.</p></div>}</article><article className="data-card next-step"><span>Recommended next step</span><h2>Create a procurement review</h2><p>Include medicine, strength, dosage form, packs, destination, delivery need, and currency for the fastest result.</p><button onClick={onStart}>Start a request<ArrowRight size={15}/></button></article></section>{requests.length > 0 && <section className="data-card lifecycle-list"><div className="card-title"><h2>Supplier response timeline</h2><span>{requests.length} open or completed</span></div>{requests.map(item => <article key={item.id}><button type="button" onClick={() => setExpanded(expanded === item.id ? undefined : item.id)} aria-expanded={expanded === item.id}><span><strong>{medicineLabel(item.request.medicine.medicine_name, item.request.medicine.strength)}</strong><small>{item.invited_supplier_count} invited · {item.responses.length} response{item.responses.length === 1 ? "" : "s"}</small></span><span className={`state-label ${item.status}`}>{item.status.replaceAll("_", " ")}</span><ArrowRight size={14}/></button>{expanded === item.id && <ol className="timeline">{item.events.map(event => <li key={event.id}><span/><div><strong>{event.message}</strong><small>{event.actor_role} · {new Date(event.created_at).toLocaleString()}</small></div></li>)}</ol>}</article>)}</section>}</main>;
}

function SupplierDashboard() {
  const [data, setData] = useState<SupplierDashboardData>(); const [buyerRequests, setBuyerRequests] = useState<SupplierRequestAssignment[]>([]); const [expandedRequest, setExpandedRequest] = useState<string>(); const [failed, setFailed] = useState(false); const [saving, setSaving] = useState(false); const [feedback, setFeedback] = useState(""); const [draftText, setDraftText] = useState(""); const [draft, setDraft] = useState<SupplierQuoteDraft>(); const [drafting, setDrafting] = useState(false); const [expandedQuote, setExpandedQuote] = useState<string>(); const [selectedSubmission, setSelectedSubmission] = useState<SupplierSubmission>(); const quoteForm = useRef<HTMLFormElement>(null); const quotesRef = useRef<HTMLElement>(null);
  const load = useCallback(() => Promise.all([api.supplierDashboard(), api.supplierRequests().catch(() => [] as SupplierRequestAssignment[])]).then(([value, assignments]) => { setData(value); setBuyerRequests(assignments); const quoteId = window.location.pathname.match(/^\/supplier\/quotations\/([^/]+)$/)?.[1]; const submissionId = window.location.pathname.match(/^\/supplier\/submissions\/([^/]+)$/)?.[1]; setExpandedQuote(value.supplier.quotes.some(quote => quote.id === quoteId) ? quoteId : undefined); setSelectedSubmission(value.submissions.find(item => item.id === submissionId)); setFailed(false); }).catch(() => setFailed(true)), []);
  useEffect(() => { load(); }, [load]);
  async function submitProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setFeedback(""); const formElement = event.currentTarget; const form = new FormData(formElement);
    try { await api.submitSupplierProfile({ display_name:String(form.get("display_name") || ""), destinations:String(form.get("destinations") || "").split(",").map(value => value.trim()).filter(Boolean), cold_chain:form.get("cold_chain") === "on", authorization_expiry:String(form.get("authorization_expiry") || "") }); Array.from(formElement.elements).forEach(field => { if (field instanceof HTMLInputElement) { if (field.type === "checkbox") field.checked = false; else field.value = ""; } }); setFeedback("Profile update submitted for staff verification."); await load(); }
    catch (error) { setFeedback(error instanceof Error ? error.message : "Profile update could not be submitted."); }
    finally { setSaving(false); }
  }
  async function submitQuote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setFeedback(""); const formElement = event.currentTarget; const form = new FormData(formElement);
    try { await api.submitSupplierQuote({ medicine_name:String(form.get("medicine_name") || ""), strength:String(form.get("strength") || ""), dosage_form:String(form.get("dosage_form") || ""), pack_size:Number(form.get("pack_size")), available_quantity_packs:Number(form.get("available_quantity_packs")), unit_price:Number(form.get("unit_price")), currency:String(form.get("currency") || ""), lead_time_days:Number(form.get("lead_time_days")) }); formElement.reset(); setDraftText(""); setDraft(undefined); setFeedback("Quotation submitted for staff verification."); await load(); }
    catch (error) { setFeedback(error instanceof Error ? error.message : "Quotation could not be submitted."); }
    finally { setSaving(false); }
  }
  async function prepareQuoteDraft() {
    setDrafting(true); setFeedback("");
    try {
      const result = await api.draftSupplierQuote(draftText); setDraft(result);
      const form = quoteForm.current;
      if (form) Object.entries(result).forEach(([name, value]) => { const field = form.elements.namedItem(name); if (field instanceof HTMLInputElement && value != null) field.value = String(value); });
    } catch (error) { setFeedback(error instanceof Error ? error.message : "Quote draft could not be prepared."); }
    finally { setDrafting(false); }
  }
  async function withdrawQuote(quote: SupplierDashboardData["supplier"]["quotes"][number]) {
    setSaving(true); setFeedback("");
    try { await api.submitSupplierQuote({ quote_id:quote.id, action:"withdraw", medicine_name:quote.line.medicine_name, strength:quote.line.strength, dosage_form:quote.line.dosage_form, pack_size:quote.line.pack_size, available_quantity_packs:quote.line.quantity_packs, unit_price:quote.line.unit_price, currency:quote.currency, lead_time_days:quote.lead_time_days }); setFeedback("Withdrawal submitted for staff verification."); await load(); }
    catch (error) { setFeedback(error instanceof Error ? error.message : "Withdrawal could not be submitted."); }
    finally { setSaving(false); }
  }
  async function respondToRequest(event: FormEvent<HTMLFormElement>, requestId: string) {
    event.preventDefault(); setSaving(true); setFeedback(""); const formElement = event.currentTarget; const form = new FormData(formElement);
    try { await api.respondToSupplierRequest(requestId, { available_quantity_packs:Number(form.get("available_quantity_packs")), unit_price:Number(form.get("unit_price")), currency:String(form.get("currency") || "USD"), lead_time_days:Number(form.get("lead_time_days")) }); formElement.reset(); setFeedback("Buyer response submitted for staff review."); await load(); }
    catch (error) { setFeedback(error instanceof Error ? error.message : "The buyer response could not be submitted."); }
    finally { setSaving(false); }
  }
  if (failed) return <main className="page-shell"><div className="error-state" role="alert">Supplier evidence is unavailable or your account is not linked.</div></main>;
  if (!data) return <main className="page-shell"><div className="progress-line" role="status"><span className="pulse-dot" />Loading supplier evidence…</div></main>;
  const supplier = data.supplier;
  const submissions = data.submissions ?? [];
  return <main className="page-shell supplier-page" data-tour="supplier-overview"><header className="page-head"><div><p className="eyebrow">Supplier workspace</p><h1>{supplier.display_name}</h1><p>Maintain the evidence and quotations buyers use in supplier comparisons.</p></div><StatusBadge status={data.compliance_state === "authorized" ? "eligible" : "review"} /></header>
    <div className="metric-grid supplier-metrics"><button className="metric metric-action" onClick={() => { quotesRef.current?.scrollIntoView({ behavior:"smooth", block:"start" }); quotesRef.current?.focus(); }} aria-label={`View ${data.quote_count} active quotations`}><span>Active quotations</span><strong>{data.quote_count}</strong><small>View quotations</small></button><div className="metric"><span>Pending changes</span><strong>{submissions.filter(item => item.status === "pending").length}</strong></div><div className="metric"><span>Reliability</span><strong>{Math.round(supplier.reliability_score * 100)}%</strong></div><div className="metric"><span>Cold chain</span><strong>{supplier.capability.cold_chain ? "Capable" : "Not listed"}</strong></div></div>
    {feedback && <div className="supplier-feedback" role="status">{feedback}</div>}
    <section className="data-card buyer-request-list"><div className="card-title"><MessageSquareText size={17}/><h2>Buyer requests</h2><span>{buyerRequests.filter(item => item.invitation_status === "invited").length} awaiting response</span></div>{buyerRequests.length ? buyerRequests.map(item => { const request = item.request.request; return <article key={item.request.id}><button type="button" className="buyer-request-head" onClick={() => setExpandedRequest(expandedRequest === item.request.id ? undefined : item.request.id)} aria-expanded={expandedRequest === item.request.id}><span><strong>{medicineLabel(request.medicine.medicine_name, request.medicine.strength)}</strong><small>{request.medicine.quantity?.toLocaleString()} packs · pack {request.medicine.pack_size} · {request.destination} · within {request.max_lead_time_days} days</small></span><span className={`state-label ${item.invitation_status}`}>{item.invitation_status}</span><ArrowRight size={14}/></button>{expandedRequest === item.request.id && <div className="buyer-request-detail">{item.supplier_response ? <div className="submitted-response"><Check size={17}/><div><strong>Offer submitted</strong><p>{item.supplier_response.currency} {item.supplier_response.unit_price.toFixed(2)} per pack · {item.supplier_response.available_quantity_packs.toLocaleString()} available · {item.supplier_response.lead_time_days} days</p><small>Status: {item.supplier_response.status.replaceAll("_", " ")}</small></div></div> : <form className="request-response-form" onSubmit={event => respondToRequest(event, item.request.id)}><p>Respond only to this request. Medicine, strength, form, and pack size are locked to the buyer&apos;s requirement.</p><label>Available packs<input name="available_quantity_packs" type="number" min={request.medicine.quantity || 1} defaultValue={request.medicine.quantity} required/></label><label>Price per pack<input name="unit_price" type="number" min="0.01" step="0.01" required/></label><label>Currency<input name="currency" defaultValue={request.currency || "USD"} minLength={3} maxLength={3} required/></label><label>Lead time (days)<input name="lead_time_days" type="number" min="1" max={request.max_lead_time_days || 365} required/></label><button disabled={saving}>Submit response for review</button></form>}<ol className="timeline compact">{item.request.events.map(event => <li key={event.id}><span/><div><strong>{event.message}</strong><small>{new Date(event.created_at).toLocaleString()}</small></div></li>)}</ol></div>}</article>; }) : <p className="muted-block">No buyer request currently matches your verified medicine coverage.</p>}</section>
    <div className="supplier-manage-grid"><section className="data-card" data-tour="supplier-compliance"><div className="card-title"><ClipboardCheck size={17}/><h2>Profile and authorization</h2></div><dl className="supplier-evidence"><dt>Authorization</dt><dd>{supplier.authorization.status}</dd><dt>Expiry</dt><dd>{supplier.authorization.expiry_date || "Not recorded"}</dd><dt>Supported markets</dt><dd>{supplier.capability.destinations.join(", ") || "Not recorded"}</dd></dl><form className="management-form" onSubmit={submitProfile}><label>Supplier name<input name="display_name" defaultValue={supplier.display_name} required minLength={2} maxLength={120}/></label><label>Destinations<input name="destinations" defaultValue={supplier.capability.destinations.join(", ")} placeholder="Ghana, Kenya" required/></label><label>Authorization expiry<input name="authorization_expiry" type="date" defaultValue={supplier.authorization.expiry_date || ""} required/></label><label className="check-label"><input name="cold_chain" type="checkbox" defaultChecked={supplier.capability.cold_chain}/>Cold-chain capable</label><button disabled={saving}>Submit profile for verification</button></form></section>
      <section className="data-card" data-tour="supplier-quotes" ref={quotesRef} tabIndex={-1}><div className="card-title"><PackageCheck size={17}/><h2>Active quotations</h2><span>{data.quote_count} active</span></div>{supplier.quotes.length ? supplier.quotes.map(quote => <article className="supplier-quote" key={quote.id}><div><strong>{quote.line.medicine_name} {quote.line.strength}</strong><span>{quote.line.dosage_form} · pack {quote.line.pack_size} · {quote.line.quantity_packs.toLocaleString()} available · {quote.lead_time_days} days</span></div><strong>{quote.currency} {quote.line.unit_price.toFixed(2)} / pack</strong><button className="quote-view" onClick={() => { const opening = expandedQuote !== quote.id; setExpandedQuote(opening ? quote.id : undefined); window.history.pushState({}, "", opening ? `/supplier/quotations/${quote.id}` : "/supplier"); }} aria-expanded={expandedQuote === quote.id} aria-controls={`quote-${quote.id}`}>{expandedQuote === quote.id ? "Hide details" : "View details"}</button>{expandedQuote === quote.id && <div className="supplier-quote-details" id={`quote-${quote.id}`}><dl><div><dt>Quotation ID</dt><dd>{quote.id}</dd></div><div><dt>Available capacity</dt><dd>{quote.line.quantity_packs.toLocaleString()} packs</dd></div><div><dt>Delivery lead time</dt><dd>{quote.lead_time_days} days</dd></div><div><dt>Unit price</dt><dd>{quote.currency} {quote.line.unit_price.toFixed(2)} per pack</dd></div></dl><button onClick={() => withdrawQuote(quote)} disabled={saving}>Request withdrawal</button><p>Withdrawal requires staff verification and does not affect an active buyer request immediately.</p></div>}</article>) : <p className="muted-block">No verified quotations yet.</p>}
        <div className="quote-assistant"><span>Quotation assistant</span><h3>Describe the offer once</h3><p>Procura will prepare the form for you. You review every field before anything is submitted.</p><label htmlFor="quote-description">Quotation details</label><textarea id="quote-description" value={draftText} onChange={event => setDraftText(event.target.value)} placeholder="Offer 4,000 packs of paracetamol 500 mg tablets, pack size 20, at USD 0.44 per pack, within 13 days." maxLength={2000}/><button type="button" onClick={prepareQuoteDraft} disabled={drafting || draftText.trim().length < 5}>{drafting ? "Preparing draft…" : "Prepare quote draft"}</button>{draft && <div className={`draft-status ${draft.ready_to_submit ? "ready" : "incomplete"}`} role="status"><strong>{draft.ready_to_submit ? "Draft ready for your review" : "More details needed"}</strong><p>{draft.summary}</p><small>No quotation has been submitted.</small></div>}</div>
        <form ref={quoteForm} className="management-form quote-form" onSubmit={submitQuote}><h3>Review and submit quotation</h3><label>Medicine<input name="medicine_name" required maxLength={120}/></label><label>Strength<input name="strength" required maxLength={40}/></label><label>Dosage form<input name="dosage_form" required maxLength={40}/></label><label>Pack size<input name="pack_size" type="number" min="1" required/></label><label>Available packs<input name="available_quantity_packs" type="number" min="1" required/></label><label>Price per pack<input name="unit_price" type="number" min="0.01" step="0.01" required/></label><label>Currency<input name="currency" defaultValue="USD" minLength={3} maxLength={3} required/></label><label>Lead time (days)<input name="lead_time_days" type="number" min="1" max="365" required/></label><button disabled={saving}>Submit quotation for verification</button></form></section>
    </div>
    <section className="data-card submission-history"><div className="card-title"><h2>Change history</h2><span>{submissions.length} submissions</span></div>{submissions.length ? submissions.map(item => <button type="button" className={selectedSubmission?.id === item.id ? "selected" : ""} key={item.id} onClick={() => { const opening = selectedSubmission?.id !== item.id; setSelectedSubmission(opening ? item : undefined); window.history.pushState({}, "", opening ? `/supplier/submissions/${item.id}` : "/supplier"); }} aria-expanded={selectedSubmission?.id === item.id}><span>{submissionLabel(item)}</span><strong>{item.status}</strong><time>{new Date(item.created_at).toLocaleDateString()}</time><ArrowRight size={14}/>{item.reviewer_note && <small>{item.reviewer_note}</small>}{selectedSubmission?.id === item.id && <div className="submission-detail"><dl>{Object.entries(item.payload).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{Array.isArray(value) ? value.join(", ") : String(value ?? "Not supplied")}</dd></div>)}</dl></div>}</button>) : <p className="muted-block">No changes submitted.</p>}</section>
    <div className="supplier-boundary"><Shield size={18}/><p>Changes become active only after staff verification. A quotation submission never creates or confirms an order.</p></div>
  </main>;
}
