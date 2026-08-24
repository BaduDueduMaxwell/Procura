import { CheckCircle2, CircleAlert, CircleX } from "lucide-react";

export function StatusBadge({ status }: { status: "eligible" | "ineligible" | "review" | "clarification" }) {
  const label = status === "eligible" ? "Eligible" : status === "ineligible" ? "Ineligible" : status === "clarification" ? "Needs information" : "Review required";
  const Icon = status === "eligible" ? CheckCircle2 : status === "ineligible" ? CircleX : CircleAlert;
  return <span className={`badge badge-${status}`}><Icon size={14} aria-hidden="true" />{label}</span>;
}
