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
afterEach(() => { cleanup(); vi.restoreAllMocks(); window.localStorage.clear(); });

describe("critical decision rendering", () => {
  it("announces eligibility with text, not color alone", () => { render(<StatusBadge status="eligible" />); expect(screen.getByText("Eligible")).toBeVisible(); });
  it("does not label clarification as eligible", () => { render(<StatusBadge status="clarification" />); expect(screen.getByText("Needs information")).toBeVisible(); expect(screen.queryByText("Eligible")).not.toBeInTheDocument(); });
  it("shows review boundary and no-transaction statement", () => {
    const result: AgentResponse = { conversation_id:"c", message:{id:"m",role:"assistant",content:"Review",created_at:new Date().toISOString()}, progress_events:[], request:{ id:"r",synthetic:true, medicine:{medicine_name:"amoxicillin",strength:"500 mg",dosage_form:"capsule",quantity:2000,pack_size:50,unit:"packs",cold_chain_required:false},destination:"Ghana",max_lead_time_days:21,currency:"USD"}, quotes:[], decision:{status:"review_required",summary:"Staff review needed",human_review_required:true,escalation_reasons:["Pack mismatch"],policy_version:"procura-policy-v1",trace_id:"t",no_transaction_completed:true} };
    render(<DecisionCards result={result} />); expect(screen.getByRole("status")).toHaveTextContent("Human review required");
  });
});

describe("public SaaS entry", () => {
  it("explains the procurement workflow and provides account access", async () => {
    vi.spyOn(api, "me").mockRejectedValueOnce(new Error("signed out"));
    render(<Home />);
    expect(await screen.findByRole("heading", { name: /move every request from need to decision/i })).toBeVisible();
    expect(screen.getByLabelText("Email address")).toHaveAttribute("type", "email");
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
});
