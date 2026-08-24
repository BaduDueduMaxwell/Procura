import type { AgentResponse, AuthUser, Conversation, CustomerDashboard, Operations, ReviewCase, SupplierDashboard, Trace } from "./types";
import * as Sentry from "@sentry/nextjs";

const API = process.env.NEXT_PUBLIC_API_URL ?? (process.env.NODE_ENV === "production" ? "" : "http://localhost:8000");

class ApiError extends Error { constructor(public status: number, message: string) { super(message); } }
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try { response = await fetch(`${API}${path}`, { ...options, credentials: "include", headers: { "Content-Type": "application/json", ...options?.headers } }); }
  catch (error) { Sentry.captureException(error, { tags: { error_category: "frontend_network", workflow_stage: "api_request" } }); throw error; }
  if (!response.ok) {
    const error = new ApiError(response.status, (await response.json().catch(() => ({}))).detail || "Procura API is unavailable");
    Sentry.captureException(error, { tags: { error_category: "frontend_api", workflow_stage: "api_response" } });
    throw error;
  }
  return response.status === 204 ? undefined as T : response.json();
}
export const api = {
  me: () => request<AuthUser>("/api/auth/me"),
  signup: (body: { email: string; display_name: string; organization: string; password: string }) => request<AuthUser>("/api/auth/signup", { method: "POST", body: JSON.stringify(body) }),
  login: (email: string, password: string) => request<AuthUser>("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),
  customerDashboard: () => request<CustomerDashboard>("/api/dashboard/summary"),
  supplierDashboard: () => request<SupplierDashboard>("/api/supplier/dashboard"),
  createConversation: () => request<Conversation>("/api/conversations", { method: "POST" }),
  sendMessage: (id: string, content: string, simulate = false) => request<AgentResponse>(`/api/conversations/${id}/messages`, { method: "POST", body: JSON.stringify({ content, idempotency_key: crypto.randomUUID(), simulate_tool_timeout: simulate }) }),
  reviews: () => request<ReviewCase[]>("/api/reviews"),
  decideReview: (id: string, action: "approve" | "reject" | "request_clarification", note: string) => request<ReviewCase>(`/api/reviews/${id}/decision`, { method: "POST", body: JSON.stringify({ action, note, idempotency_key: crypto.randomUUID() }) }),
  operations: () => request<Operations>("/api/operations/summary"),
  trace: (id: string) => request<Trace>(`/api/traces/${id}`),
  simulateTimeout: () => request<AgentResponse>("/api/dev/simulate-tool-timeout", { method: "POST" })
};
