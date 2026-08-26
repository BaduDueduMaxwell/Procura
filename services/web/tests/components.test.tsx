import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StatusBadge } from "@/components/StatusBadge";
import { DecisionCards, formatReviewReason } from "@/components/DecisionCards";
import type { AgentResponse } from "@/lib/types";
import Home from "@/app/page";
import { api, formatApiError } from "@/lib/api";

const stored = new Map<string, string>();
Object.defineProperty(window, "localStorage", { configurable: true, value: { getItem: (key: string) => stored.get(key) ?? null, setItem: (key: string, value: string) => stored.set(key, value), removeItem: (key: string) => stored.delete(key), clear: () => stored.clear() } });
afterEach(() => { cleanup(); vi.restoreAllMocks(); window.localStorage.clear(); window.history.replaceState({}, "", "/"); });

describe("critical decision rendering", () => {
  it("turns legacy exception names into actionable review reasons", () => {
    expect(formatReviewReason("Safe failure: ValueError")).toBe("The verification sequence was incomplete, so Procura stopped before evaluating suppliers.");
    expect(formatReviewReason("Escalation: Safe failure: ToolTimeoutError")).toContain("Supplier verification timed out");
  });
  it("announces eligibility with text, not color alone", () => { render(<StatusBadge status="eligible" />); expect(screen.getByText("Eligible")).toBeVisible(); });
  it("does not label clarification as eligible", () => { render(<StatusBadge status="clarification" />); expect(screen.getByText("Needs information")).toBeVisible(); expect(screen.queryByText("Eligible")).not.toBeInTheDocument(); });
  it("shows review boundary and no-transaction statement", () => {
    const result: AgentResponse = { conversation_id:"c", message:{id:"m",role:"assistant",content:"Review",created_at:new Date().toISOString()}, progress_events:[], request:{ id:"r",synthetic:true, medicine:{medicine_name:"amoxicillin",strength:"500 mg",dosage_form:"capsule",quantity:2000,pack_size:50,unit:"packs",cold_chain_required:false},destination:"Ghana",max_lead_time_days:21,currency:"USD"}, quotes:[], decision:{status:"review_required",summary:"Staff review needed",human_review_required:true,escalation_reasons:["Pack mismatch"],policy_version:"procura-policy-v1",trace_id:"t",no_transaction_completed:true} };
    render(<DecisionCards result={result} />); expect(screen.getByRole("status")).toHaveTextContent("Human review required");
  });
  it("shows the requested total, capacity, and every exclusion reason", () => {
    const result: AgentResponse = { conversation_id:"c", message:{id:"m",role:"assistant",content:"Review",created_at:new Date().toISOString()}, progress_events:[], request:{ id:"r",synthetic:true, medicine:{medicine_name:"paracetamol",strength:"500 mg",dosage_form:"tablet",quantity:1500,pack_size:20,unit:"packs",cold_chain_required:false},destination:"Ghana",max_lead_time_days:18,currency:"USD"}, quotes:[{supplier_id:"dynamic-supplier",supplier_display_name:"Aster Medical Supply",quote_id:"q",total_price:3270,unit_price:2.18,currency:"USD",requested_quantity_packs:1500,available_quantity_packs:5000,offered_pack_size:100,lead_time_days:16,reliability:.89,eligible:false,reasons:["Pack size mismatch: requested 20, offered 100","Authorization missing"]}], decision:{status:"review_required",summary:"Review",human_review_required:true,escalation_reasons:["Pack size mismatch: requested 20, offered 100","Authorization missing"],policy_version:"procura-policy-v1",trace_id:"t",no_transaction_completed:true} };
    render(<DecisionCards result={result} />);
    expect(screen.getByText("Total for 1,500 requested packs")).toBeVisible();
    expect(screen.getByText("5,000 available · pack 100 · USD 2.18 per pack")).toBeVisible();
    expect(screen.getByText("Aster Medical Supply")).toBeVisible();
    expect(screen.getAllByText("Pack size mismatch: requested 20, offered 100")).toHaveLength(2);
    expect(screen.getAllByText("Authorization missing")).toHaveLength(2);
  });
});

describe("public SaaS entry", () => {
  it("explains the procurement workflow and provides account access", async () => {
    vi.spyOn(api, "me").mockRejectedValueOnce(new Error("signed out"));
    render(<Home />);
    expect(await screen.findByRole("heading", { name: /move every request from need to decision/i })).toBeVisible();
    expect(screen.getByLabelText("Email address")).toHaveAttribute("type", "email");
    fireEvent.click(screen.getByLabelText("Supplier"));
    expect(screen.getByRole("button", { name: /create supplier workspace/i })).toBeVisible();
    expect(screen.getByText(/clear path from request to recommendation/i)).toBeVisible();
    screen.getAllByRole("button", { name: "Sign in" })[0].click();
    expect(await screen.findByRole("heading", { name: "Welcome back" })).toBeVisible();
    expect(screen.queryByText(/reviewer@procura.example/i)).not.toBeInTheDocument();
  });
});

describe("API validation messages", () => {
  it("turns structured password validation into readable guidance", () => {
    expect(formatApiError({ detail: [{ loc: ["body", "password"], msg: "String should have at least 12 characters" }] })).toBe("Password must be at least 12 characters.");
    expect(formatApiError({ detail: [{ loc: ["body", "password"], msg: "Value error, password must include upper, lower, number, and symbol" }] })).toBe("Password must include uppercase and lowercase letters, a number, and a symbol.");
  });

  it("never renders validation objects as object strings", () => {
    const message = formatApiError({ detail: [{ loc: ["body", "organization"], msg: "String should have at least 2 characters" }] });
    expect(message).toContain("Organization");
    expect(message).not.toContain("[object Object]");
  });
});

describe("guided product journey", () => {
  it("guides a reviewer through review-only navigation", async () => {
    vi.spyOn(api, "me").mockResolvedValueOnce({ id: "reviewer-1", email: "reviewer@procura.example", display_name: "Operations Reviewer", organization: "Procura", role: "reviewer", created_at: new Date().toISOString() });
    vi.spyOn(api, "reviews").mockResolvedValue([]);
    render(<Home />);
    expect(await screen.findByRole("heading", { name: "Welcome to the review workspace" }, { timeout: 1500 })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Show me around" }));
    expect(await screen.findByRole("heading", { name: "Resolve request exceptions" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Close product guide" }));
    expect(screen.getByRole("button", { name: "Product guide" })).toBeVisible();
    expect(window.localStorage.getItem("procura-guide:reviewer-1")).toBe("seen");
  });

  it("keeps reviewers on review routes and gives admins every internal route", async () => {
    window.localStorage.setItem("procura-guide:reviewer-route", "seen");
    window.history.replaceState({}, "", "/operations");
    vi.spyOn(api, "me").mockResolvedValueOnce({ id: "reviewer-route", email: "reviewer@procura.example", display_name: "Reviewer", organization: "Procura", role: "reviewer", created_at: new Date().toISOString() });
    vi.spyOn(api, "reviews").mockResolvedValue([]);
    const reviewerView = render(<Home />);
    expect(await screen.findByRole("heading", { name: "Staff review" })).toBeVisible();
    expect(window.location.pathname).toBe("/reviews");
    expect(screen.getByRole("button", { name: "Supplier approvals" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Operations" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New request" })).not.toBeInTheDocument();
    reviewerView.unmount();

    window.localStorage.setItem("procura-guide:admin-route", "seen");
    window.history.replaceState({}, "", "/operations");
    vi.spyOn(api, "me").mockResolvedValueOnce({ id: "admin-route", email: "operations@procura.example", display_name: "Operations Administrator", organization: "Procura", role: "admin", created_at: new Date().toISOString() });
    vi.spyOn(api, "createConversation").mockResolvedValue({ id: "admin-conversation", messages: [] });
    vi.spyOn(api, "operations").mockResolvedValue({ request_count:0, autonomous_recommendation_count:0, human_review_count:0, error_count:0, evaluation_pass_rate:1, langfuse_status:"Langfuse not configured", sentry_status:"Sentry not configured", recent_traces:[] });
    render(<Home />);
    expect(await screen.findByRole("heading", { name: "Operations" })).toBeVisible();
    for (const label of ["Dashboard", "Workspace", "Request reviews", "Supplier approvals", "Operations"]) expect(screen.getByRole("button", { name: label })).toBeVisible();
    expect(screen.getByText("operations admin")).toBeVisible();
  });

  it("announces when a new request is ready", async () => {
    window.localStorage.setItem("procura-guide:buyer-1", "seen");
    vi.spyOn(api, "me").mockResolvedValueOnce({ id: "buyer-1", email: "buyer@procura.example", display_name: "Buyer", organization: "Health Office", role: "buyer", created_at: new Date().toISOString() });
    vi.spyOn(api, "createConversation").mockResolvedValue({ id: "conversation-1", messages: [] });
    vi.spyOn(api, "customerDashboard").mockResolvedValue({ conversation_count: 0, execution_count: 0, recommendation_count: 0, review_count: 0, recent_decisions: [] });
    render(<Home />);
    fireEvent.click((await screen.findAllByRole("button", { name: "Start a request" }))[0]);
    expect(await screen.findByText("New request ready")).toBeVisible();
  });

  it("uses stable URLs for authenticated screens", async () => {
    window.localStorage.setItem("procura-guide:buyer-route", "seen");
    window.history.replaceState({}, "", "/workspace");
    vi.spyOn(api, "me").mockResolvedValueOnce({ id: "buyer-route", email: "buyer-route@procura.example", display_name: "Buyer", organization: "Health Office", role: "buyer", created_at: new Date().toISOString() });
    vi.spyOn(api, "createConversation").mockResolvedValue({ id: "conversation-route", messages: [] });
    vi.spyOn(api, "customerDashboard").mockResolvedValue({ conversation_count: 0, execution_count: 0, recommendation_count: 0, review_count: 0, recent_decisions: [] });
    render(<Home />);
    expect(await screen.findByRole("heading", { name: "Describe what you need" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Dashboard" })).toHaveAttribute("aria-label", "Dashboard");
    expect(screen.getByRole("button", { name: "Workspace" })).toHaveAttribute("aria-label", "Workspace");
    fireEvent.click(screen.getByRole("button", { name: "Dashboard" }));
    expect(window.location.pathname).toBe("/dashboard");
    expect(await screen.findByRole("heading", { name: "Procurement dashboard" })).toBeVisible();
  });

  it("opens a buyer decision from the dashboard with its conversation and evidence", async () => {
    window.localStorage.setItem("procura-guide:buyer-decision", "seen");
    const createdAt = new Date().toISOString();
    const trace = { trace_id:"trace-decision-1",conversation_id:"conversation-decision-1",decision:"recommended",latency_ms:4200,provider:"gemini",model:"gemini-3.6-flash",review_required:false,policy_version:"procura-policy-v1",prompt_version:"procura-agent-v1",token_input:650,token_output:80,exported_to_langfuse:false,tool_sequence:["normalize_procurement_request"],created_at:createdAt };
    const result: AgentResponse = { conversation_id:"conversation-decision-1",message:{id:"assistant-1",role:"assistant",content:"Northstar is recommended.",created_at:createdAt},progress_events:[],request:{id:"request-1",synthetic:true,medicine:{medicine_name:"omeprazole",strength:"20 mg",dosage_form:"capsule",quantity:600,pack_size:28,unit:"packs",cold_chain_required:false},destination:"Ghana",max_lead_time_days:18,currency:"USD"},quotes:[],decision:{status:"recommended",recommendation_supplier_id:"northstar",summary:"Northstar is recommended.",human_review_required:false,escalation_reasons:[],policy_version:"procura-policy-v1",trace_id:"trace-decision-1",no_transaction_completed:true} };
    vi.spyOn(api, "me").mockResolvedValueOnce({ id:"buyer-decision",email:"buyer@procura.example",display_name:"Buyer",organization:"Health Office",role:"buyer",created_at:createdAt });
    vi.spyOn(api, "createConversation").mockResolvedValue({ id:"empty-shell",messages:[] });
    vi.spyOn(api, "customerDashboard").mockResolvedValue({ conversation_count:1,execution_count:1,recommendation_count:1,review_count:0,recent_decisions:[trace] });
    const execution = vi.spyOn(api, "execution").mockResolvedValue(result);
    vi.spyOn(api, "conversation").mockResolvedValue({ id:"conversation-decision-1",messages:[{id:"user-1",role:"user",content:"We need omeprazole.",created_at:createdAt},result.message] });

    render(<Home />);
    fireEvent.click(await screen.findByRole("button", { name:/open procurement review 1: recommended/i }));

    expect(await screen.findByText("Northstar is recommended.")).toBeVisible();
    expect(screen.getByText("Request brief")).toBeVisible();
    expect(window.location.pathname).toBe("/workspace/decisions/trace-decision-1");
    expect(execution).toHaveBeenCalledWith("trace-decision-1");
  });

  it("lets buyers search database-backed medicines and prepare a request", async () => {
    window.localStorage.setItem("procura-guide:buyer-catalog", "seen");
    window.history.replaceState({}, "", "/workspace");
    vi.spyOn(api, "me").mockResolvedValueOnce({ id:"buyer-catalog",email:"buyer@procura.example",display_name:"Buyer",organization:"Health Office",role:"buyer",created_at:new Date().toISOString() });
    vi.spyOn(api, "createConversation").mockResolvedValue({ id:"catalog-conversation",messages:[] });
    const paracetamol = { medicine_name:"paracetamol",strength:"500 mg",dosage_form:"tablet",pack_size:20,quotation_count:2,authorized_supplier_count:1,available_quantity_packs:5000,currencies:["USD"],destinations:["Ghana","Kenya"],cold_chain_available:true,minimum_lead_time_days:12,unit_price_from:.41,unit_price_to:.46,request_starter:"We need paracetamol 500 mg tablets, pack size 20." };
    const insulin = { medicine_name:"insulin",strength:"100 units/ml",dosage_form:"vial",pack_size:10,quotation_count:3,authorized_supplier_count:1,available_quantity_packs:300,currencies:["USD"],destinations:["Ghana","Kenya"],cold_chain_available:true,minimum_lead_time_days:14,unit_price_from:39.5,unit_price_to:42,request_starter:"We need insulin 100 units/ml vials, pack size 10." };
    const catalogSearch = vi.spyOn(api, "medicineCatalog").mockImplementation(async query => query ? [paracetamol] : [paracetamol, insulin]);
    const send = vi.spyOn(api, "sendMessage");
    render(<Home />);
    expect(await screen.findByRole("heading", { name:"Choose a product variant" })).toBeVisible();
    const search = screen.getByRole("combobox", { name:"Search available medicines" });
    expect(search).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("listbox", { name:"Medicine search results" })).not.toBeInTheDocument();
    expect(catalogSearch).not.toHaveBeenCalled();
    fireEvent.focus(search);
    expect(await screen.findByRole("listbox", { name:"Medicine search results" })).toBeVisible();
    expect(catalogSearch).toHaveBeenLastCalledWith("", 20);
    fireEvent.change(search, { target:{value:"paracetamol"} });
    expect(await screen.findByText("1 matching variant")).toBeVisible();
    expect(catalogSearch).toHaveBeenLastCalledWith("paracetamol", 20);
    expect(screen.queryByText("insulin")).not.toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("option", { name:/paracetamol 500 mg/i }), { key:"Enter" });
    expect(search).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("listbox", { name:"Medicine search results" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Procurement request")).toHaveValue("We need paracetamol 500 mg tablets, pack size 20.");
    expect(send).not.toHaveBeenCalled();
  });

  it("confirms a supplier quotation submission after the async request", async () => {
    window.localStorage.setItem("procura-guide:supplier-route", "seen");
    vi.spyOn(api, "me").mockResolvedValueOnce({ id: "supplier-route", email: "supplier-route@procura.example", display_name: "Supplier", organization: "Aster", role: "supplier", created_at: new Date().toISOString() });
    vi.spyOn(api, "supplierDashboard").mockResolvedValue({ supplier:{id:"aster",display_name:"Aster",authorization:{status:"missing"},capability:{destinations:[],cold_chain:false},reliability_score:0,quotes:[]}, quote_count:0,eligible_destination_count:0,compliance_state:"missing",submissions:[] });
    vi.spyOn(api, "submitSupplierQuote").mockResolvedValue({ id:"submission-1",supplier_id:"aster",kind:"quote",payload:{},status:"pending",created_at:new Date().toISOString() });
    render(<Home />);
    await screen.findByRole("heading", { name: "Review and submit quotation" });
    fireEvent.change(screen.getByLabelText("Medicine"), { target:{value:"paracetamol"} });
    fireEvent.change(screen.getByLabelText("Strength"), { target:{value:"500 mg"} });
    fireEvent.change(screen.getByLabelText("Dosage form"), { target:{value:"tablet"} });
    fireEvent.change(screen.getByLabelText("Pack size"), { target:{value:"20"} });
    fireEvent.change(screen.getByLabelText("Available packs"), { target:{value:"4000"} });
    fireEvent.change(screen.getByLabelText("Price per pack"), { target:{value:"0.44"} });
    fireEvent.change(screen.getByLabelText("Lead time (days)"), { target:{value:"13"} });
    fireEvent.click(screen.getByRole("button", { name:"Submit quotation for verification" }));
    expect(await screen.findByText("Quotation submitted for staff verification.")).toBeVisible();
  });

  it("prepares a supplier quote form without submitting it", async () => {
    window.localStorage.setItem("procura-guide:supplier-draft", "seen");
    vi.spyOn(api, "me").mockResolvedValueOnce({ id:"supplier-draft", email:"supplier@procura.example", display_name:"Supplier", organization:"Aster", role:"supplier", created_at:new Date().toISOString() });
    vi.spyOn(api, "supplierDashboard").mockResolvedValue({ supplier:{id:"aster",display_name:"Aster",authorization:{status:"authorized"},capability:{destinations:["Ghana"],cold_chain:false},reliability_score:.9,quotes:[]},quote_count:0,eligible_destination_count:1,compliance_state:"authorized",submissions:[] });
    const draft = vi.spyOn(api, "draftSupplierQuote").mockResolvedValue({ medicine_name:"paracetamol",strength:"500 mg",dosage_form:"tablet",pack_size:20,available_quantity_packs:4000,unit_price:.44,currency:"USD",lead_time_days:13,missing_fields:[],ready_to_submit:true,summary:"Quote draft is complete and ready for your confirmation.",provider:"local",prompt_version:"procura-supplier-quote-v1",trace_id:"trace-draft",no_submission_created:true });
    const submit = vi.spyOn(api, "submitSupplierQuote");
    render(<Home />);
    fireEvent.change(await screen.findByLabelText("Quotation details"), { target:{value:"Offer 4,000 packs of paracetamol 500 mg tablets, pack size 20, at USD 0.44 per pack, within 13 days."} });
    fireEvent.click(screen.getByRole("button", { name:"Prepare quote draft" }));
    expect(await screen.findByText("Draft ready for your review")).toBeVisible();
    expect(screen.getByLabelText("Medicine")).toHaveValue("paracetamol");
    expect(screen.getByLabelText("Available packs")).toHaveValue(4000);
    expect(screen.getByText("No quotation has been submitted.")).toBeVisible();
    expect(draft).toHaveBeenCalledOnce();
    expect(submit).not.toHaveBeenCalled();
  });

  it("lets a supplier inspect active quotation evidence", async () => {
    window.localStorage.setItem("procura-guide:supplier-quotes", "seen");
    vi.spyOn(api, "me").mockResolvedValueOnce({ id:"supplier-quotes",email:"supplier@procura.example",display_name:"Supplier",organization:"Aster",role:"supplier",created_at:new Date().toISOString() });
    vi.spyOn(api, "supplierDashboard").mockResolvedValue({ supplier:{id:"aster",display_name:"Aster",authorization:{status:"authorized",expiry_date:"2028-12-31"},capability:{destinations:["Ghana"],cold_chain:true},reliability_score:.9,quotes:[{id:"quote-1",currency:"USD",lead_time_days:13,line:{medicine_name:"paracetamol",strength:"500 mg",dosage_form:"tablet",pack_size:20,quantity_packs:4000,unit_price:.44}}]},quote_count:1,eligible_destination_count:1,compliance_state:"authorized",submissions:[] });
    render(<Home />);
    expect(await screen.findByRole("button", { name:"View 1 active quotations" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name:"View details" }));
    expect(screen.getByText("Available capacity")).toBeVisible();
    expect(screen.getByText("4,000 packs")).toBeVisible();
    expect(screen.getByRole("button", { name:"Hide details" })).toHaveAttribute("aria-expanded", "true");
    expect(window.location.pathname).toBe("/supplier/quotations/quote-1");
  });

  it("shows a reviewer brief without recording a decision", async () => {
    window.localStorage.setItem("procura-guide:review-brief", "seen");
    const reviewCase = { id:"review-1",trace_id:"trace-1",status:"open" as const,reasons:["pack_size_mismatch"],request:{id:"request-1",synthetic:true as const,medicine:{medicine_name:"paracetamol",strength:"500 mg",dosage_form:"tablet",quantity:1500,pack_size:20,unit:"packs",cold_chain_required:false},destination:"Ghana",max_lead_time_days:18,currency:"USD"},quotes:[],policy_version:"procura-policy-v1",created_at:new Date().toISOString() };
    vi.spyOn(api, "me").mockResolvedValueOnce({ id:"review-brief",email:"reviewer@procura.example",display_name:"Reviewer",organization:"Procura",role:"reviewer",created_at:new Date().toISOString() });
    vi.spyOn(api, "reviews").mockResolvedValue([reviewCase]);
    vi.spyOn(api, "reviewBrief").mockResolvedValue({ review_id:"review-1",trace_id:"trace-1",summary:"Review paracetamol against 0 supplier quotations.",evidence_points:["Escalation: pack_size_mismatch"],suggested_action:"request_clarification",suggestion_reason:"Resolve missing evidence.",policy_version:"procura-policy-v1",provider:"local",prompt_version:"procura-review-brief-v1",human_decision_required:true });
    const decide = vi.spyOn(api, "decideReview");
    render(<Home />);
    expect(await screen.findByText("Review brief")).toBeVisible();
    expect(screen.getByText("Suggested: request clarification")).toBeVisible();
    expect(screen.getByText(/reviewer must make the final decision/i)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name:/paracetamol/i }));
    expect(window.location.pathname).toBe("/reviews/review-1");
    expect(decide).not.toHaveBeenCalled();
  });

  it("opens operations trace evidence on a stable URL", async () => {
    window.localStorage.setItem("procura-guide:operations-trace", "seen");
    window.history.replaceState({}, "", "/operations");
    const createdAt = new Date().toISOString();
    vi.spyOn(api, "me").mockResolvedValueOnce({ id:"operations-trace",email:"operations@procura.example",display_name:"Operations",organization:"Procura",role:"admin",created_at:createdAt });
    vi.spyOn(api, "createConversation").mockResolvedValue({ id:"operations-shell",messages:[] });
    vi.spyOn(api, "operations").mockResolvedValue({ request_count:1,autonomous_recommendation_count:1,human_review_count:0,error_count:0,p50_latency_ms:4200,p95_latency_ms:4200,token_usage:730,evaluation_pass_rate:1,langfuse_status:"Langfuse not configured",sentry_status:"Sentry not configured",recent_traces:[{trace_id:"trace-operations-1",conversation_id:"conversation-1",decision:"recommended",latency_ms:4200,provider:"gemini",model:"gemini-3.6-flash",review_required:false,policy_version:"procura-policy-v1",prompt_version:"procura-agent-v1",token_input:650,token_output:80,exported_to_langfuse:false,tool_sequence:["normalize_procurement_request"],created_at:createdAt}] });

    render(<Home />);
    fireEvent.click(await screen.findByRole("button", { name:"Open trace trace-op" }));

    expect(screen.getByText("Trace evidence")).toBeVisible();
    expect(screen.getByText("gemini · gemini-3.6-flash")).toBeVisible();
    expect(window.location.pathname).toBe("/operations/traces/trace-operations-1");
  });
});
