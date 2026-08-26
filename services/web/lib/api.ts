import type { AgentResponse, AuthUser, Conversation, CustomerDashboard, MedicineCatalogItem, Operations, ReviewBrief, ReviewCase, SupplierDashboard, SupplierQuoteDraft, SupplierSubmission, Trace } from "./types";
import * as Sentry from "@sentry/nextjs";

const API = process.env.NEXT_PUBLIC_API_URL ?? (process.env.NODE_ENV === "production" ? "" : "http://localhost:8000");

class ApiError extends Error { constructor(public status: number, message: string) { super(message); } }
type ValidationIssue = { loc?: Array<string | number>; msg?: string };
const fieldLabels: Record<string, string> = { display_name: "Full name", organization: "Organization", email: "Email address", password: "Password", content: "Request" };

function issueMessage(issue: ValidationIssue): string | undefined {
  if (!issue.msg) return undefined;
  const field = String(issue.loc?.at(-1) ?? "");
  const label = fieldLabels[field] ?? (field ? field.replaceAll("_", " ") : "Request");
  if (field === "password" && issue.msg.includes("at least 12 characters")) return "Password must be at least 12 characters.";
  if (field === "password" && issue.msg.includes("upper, lower, number, and symbol")) return "Password must include uppercase and lowercase letters, a number, and a symbol.";
  if (field === "email" && issue.msg.toLowerCase().includes("valid email")) return "Enter a valid email address.";
  const message = issue.msg.replace(/^Value error,\s*/i, "");
  return `${label}: ${message.charAt(0).toUpperCase()}${message.slice(1)}.`.replace("..", ".");
}

export function formatApiError(payload: unknown): string {
  if (!payload || typeof payload !== "object") return "Procura API is unavailable";
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = [...new Set(detail.map(item => item && typeof item === "object" ? issueMessage(item as ValidationIssue) : undefined).filter(Boolean))];
    if (messages.length) return messages.join(" ");
  }
  return "The submitted information could not be validated. Check the form and try again.";
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try { response = await fetch(`${API}${path}`, { ...options, credentials: "include", headers: { "Content-Type": "application/json", ...options?.headers } }); }
  catch (error) { Sentry.captureException(error, { tags: { error_category: "frontend_network", workflow_stage: "api_request" } }); throw error; }
  if (!response.ok) {
    const error = new ApiError(response.status, formatApiError(await response.json().catch(() => ({}))));
    if (response.status >= 500) Sentry.captureException(error, { tags: { error_category: "frontend_api", workflow_stage: "api_response" } });
    throw error;
  }
  return response.status === 204 ? undefined as T : response.json();
}
export const api = {
  me: () => request<AuthUser>("/api/auth/me"),
  signup: (body: { email: string; display_name: string; organization: string; password: string; account_type?: "buyer" | "supplier" }) => request<AuthUser>("/api/auth/signup", { method: "POST", body: JSON.stringify(body) }),
  login: (email: string, password: string) => request<AuthUser>("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),
  customerDashboard: () => request<CustomerDashboard>("/api/dashboard/summary"),
  medicineCatalog: (query = "", limit = 6) => request<MedicineCatalogItem[]>(`/api/catalog/medicines?q=${encodeURIComponent(query)}&limit=${limit}`),
  supplierDashboard: () => request<SupplierDashboard>("/api/supplier/dashboard"),
  submitSupplierProfile: (body: { display_name: string; destinations: string[]; cold_chain: boolean; authorization_expiry: string }) => request<SupplierSubmission>("/api/supplier/submissions/profile", { method: "POST", body: JSON.stringify({ ...body, idempotency_key: crypto.randomUUID() }) }),
  submitSupplierQuote: (body: { quote_id?: string; action?: "upsert" | "withdraw"; medicine_name: string; strength: string; dosage_form: string; pack_size: number; available_quantity_packs: number; unit_price: number; currency: string; lead_time_days: number }) => request<SupplierSubmission>("/api/supplier/submissions/quotes", { method: "POST", body: JSON.stringify({ ...body, idempotency_key: crypto.randomUUID() }) }),
  draftSupplierQuote: (content: string) => request<SupplierQuoteDraft>("/api/supplier/quote-drafts", { method: "POST", body: JSON.stringify({ content }) }),
  supplierSubmissions: () => request<SupplierSubmission[]>("/api/supplier-submissions"),
  decideSupplierSubmission: (id: string, action: "approve" | "reject", note: string) => request<SupplierSubmission>(`/api/supplier-submissions/${id}/decision`, { method: "POST", body: JSON.stringify({ action, note, idempotency_key: crypto.randomUUID() }) }),
  createConversation: () => request<Conversation>("/api/conversations", { method: "POST" }),
  sendMessage: (id: string, content: string, simulate = false) => request<AgentResponse>(`/api/conversations/${id}/messages`, { method: "POST", body: JSON.stringify({ content, idempotency_key: crypto.randomUUID(), simulate_tool_timeout: simulate }) }),
  reviews: () => request<ReviewCase[]>("/api/reviews"),
  reviewBrief: (id: string) => request<ReviewBrief>(`/api/reviews/${id}/brief`),
  decideReview: (id: string, action: "approve" | "reject" | "request_clarification", note: string) => request<ReviewCase>(`/api/reviews/${id}/decision`, { method: "POST", body: JSON.stringify({ action, note, idempotency_key: crypto.randomUUID() }) }),
  operations: () => request<Operations>("/api/operations/summary"),
  trace: (id: string) => request<Trace>(`/api/traces/${id}`),
  simulateTimeout: () => request<AgentResponse>("/api/dev/simulate-tool-timeout", { method: "POST" })
};
