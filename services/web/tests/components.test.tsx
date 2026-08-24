import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StatusBadge } from "@/components/StatusBadge";
import { DecisionCards } from "@/components/DecisionCards";
import type { AgentResponse } from "@/lib/types";
import Home from "@/app/page";
import { api, formatApiError } from "@/lib/api";

const stored = new Map<string, string>();
Object.defineProperty(window, "localStorage", { configurable: true, value: { getItem: (key: string) => stored.get(key) ?? null, setItem: (key: string, value: string) => stored.set(key, value), removeItem: (key: string) => stored.delete(key), clear: () => stored.clear() } });
afterEach(() => { cleanup(); vi.restoreAllMocks(); window.localStorage.clear(); window.history.replaceState({}, "", "/"); });

describe("critical decision rendering", () => {
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
  it("welcomes a first-time reviewer and keeps the guide replayable", async () => {
    vi.spyOn(api, "me").mockResolvedValueOnce({ id: "reviewer-1", email: "reviewer@procura.example", display_name: "Operations Reviewer", organization: "Procura", role: "reviewer", created_at: new Date().toISOString() });
    vi.spyOn(api, "createConversation").mockResolvedValue({ id: "conversation-1", messages: [] });
    vi.spyOn(api, "customerDashboard").mockResolvedValue({ conversation_count: 0, execution_count: 0, recommendation_count: 0, review_count: 0, recent_decisions: [] });
    render(<Home />);
    expect(await screen.findByRole("heading", { name: "Welcome to Procura" }, { timeout: 1500 })).toBeVisible();
    expect(screen.queryByRole("button", { name: "About" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show me around" }));
    expect(await screen.findByRole("heading", { name: "Start from the dashboard" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Close product guide" }));
    expect(screen.getByRole("button", { name: "Product guide" })).toBeVisible();
    expect(window.localStorage.getItem("procura-guide:reviewer-1")).toBe("seen");
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
    fireEvent.click(screen.getByRole("button", { name: "Dashboard" }));
    expect(window.location.pathname).toBe("/dashboard");
    expect(await screen.findByRole("heading", { name: "Procurement dashboard" })).toBeVisible();
  });

  it("confirms a supplier quotation submission after the async request", async () => {
    window.localStorage.setItem("procura-guide:supplier-route", "seen");
    vi.spyOn(api, "me").mockResolvedValueOnce({ id: "supplier-route", email: "supplier-route@procura.example", display_name: "Supplier", organization: "Aster", role: "supplier", created_at: new Date().toISOString() });
    vi.spyOn(api, "supplierDashboard").mockResolvedValue({ supplier:{id:"aster",display_name:"Aster",authorization:{status:"missing"},capability:{destinations:[],cold_chain:false},reliability_score:0,quotes:[]}, quote_count:0,eligible_destination_count:0,compliance_state:"missing",submissions:[] });
    vi.spyOn(api, "submitSupplierQuote").mockResolvedValue({ id:"submission-1",supplier_id:"aster",kind:"quote",payload:{},status:"pending",created_at:new Date().toISOString() });
    render(<Home />);
    await screen.findByRole("heading", { name: "Submit a quotation" });
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
});
