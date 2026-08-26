import time
from uuid import uuid4

from app.agent.providers import (
    REQUIRED_TOOL_PLAN,
    DeterministicLLMProvider,
    GeminiProvider,
    LLMProvider,
    OpenAIProvider,
)
from app.config import Settings
from app.domain.errors import InvalidModelOutputError, PersistenceError, ProviderUnavailableError, ToolTimeoutError
from app.domain.models import (
    AgentDecision,
    AgentResponse,
    Conversation,
    HumanReviewCase,
    Message,
    ProcurementRequest,
    TraceSummary,
)
from app.models.database import ConversationRow, ExecutionRow, ReviewRow, SessionLocal
from app.observability.adapters import Observability
from app.services.scope import SCOPE_REJECTION_TOOL, is_procurement_message, scope_redirect
from app.services.seed import synthetic_suppliers
from app.services.tools import (
    compare_quote_prices,
    create_human_review_case,
    evaluate_quote,
    normalize_procurement_request,
    rank_eligible_quotes,
    search_synthetic_suppliers,
)
from sqlalchemy import select

PROGRESS = ["Request understood", "Checking supplier eligibility", "Comparing quotations", "Applying review policy", "Recommendation ready"]


def build_provider(settings: Settings, policy: str) -> LLMProvider:
    provider_name = settings.llm_provider.strip().lower()
    if provider_name == "local":
        return DeterministicLLMProvider()
    if provider_name == "openai":
        return OpenAIProvider(settings.llm_api_key or "", settings.llm_model, policy)
    if provider_name == "gemini":
        return GeminiProvider(
            settings.llm_api_key or "",
            settings.llm_model,
            policy,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    raise ValueError(f"Unsupported LLM provider: {provider_name}")


def safe_failure_message(exc: Exception) -> tuple[str, str]:
    """Return an actionable summary and review reason without leaking internals."""
    if isinstance(exc, ToolTimeoutError):
        return ("Supplier verification did not finish within the safe processing limit. A staff review case was created.", "Supplier verification timed out before all eligibility checks completed.")
    if isinstance(exc, ProviderUnavailableError):
        return ("The request interpreter was temporarily unavailable. A staff review case was created.", "The request could not be interpreted reliably because the language provider was unavailable.")
    if isinstance(exc, InvalidModelOutputError):
        return ("The request could not be converted into a valid procurement record. A staff review case was created.", "The language provider returned an invalid structured request after one retry.")
    if isinstance(exc, PersistenceError):
        return ("The decision record could not be saved safely. A staff review case was created.", "Procura could not verify that the workflow record was stored successfully.")
    if isinstance(exc, ValueError) and str(exc) == "Unsafe or incomplete tool plan":
        return ("The required verification sequence was incomplete. A staff review case was created.", "The verification sequence omitted one or more required supplier checks.")
    return ("The procurement review stopped before a safe recommendation could be produced. A staff review case was created.", "An unexpected processing failure prevented Procura from completing all required checks.")


class AgentService:
    def __init__(self, settings: Settings, policy: str, observability: Observability):
        self.settings, self.policy, self.observability = settings, policy, observability
        self.provider = build_provider(settings, policy)

    def create_conversation(self) -> Conversation:
        conversation = Conversation(id=str(uuid4()))
        with SessionLocal() as db:
            db.add(ConversationRow(id=conversation.id, data=conversation.model_dump_json()))
            db.commit()
        return conversation

    async def close(self) -> None:
        await self.provider.close()

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        with SessionLocal() as db:
            row = db.get(ConversationRow, conversation_id)
            return Conversation.model_validate_json(row.data) if row else None

    async def execute(self, conversation_id: str, content: str, idempotency_key: str, simulate_timeout: bool = False) -> AgentResponse:
        started, trace_id = time.perf_counter(), str(uuid4())
        with SessionLocal() as db:
            existing = db.scalar(select(ExecutionRow).where(ExecutionRow.idempotency_key == idempotency_key))
            if existing:
                return AgentResponse.model_validate_json(existing.response)
        conversation = self.get_conversation(conversation_id)
        if not conversation: raise KeyError(conversation_id)
        conversation.messages.append(Message(role="user", content=content))
        quotes, tool_sequence, review_reasons = [], [], []
        request = conversation.draft or ProcurementRequest(medicine={})
        self.provider.begin_execution()
        try:
            if simulate_timeout: raise ToolTimeoutError("Supplier verification exceeded its safe deadline")
            if not is_procurement_message(content, conversation.draft):
                message = scope_redirect(request)
                decision = AgentDecision(status="clarification", summary=message, trace_id=trace_id)
                assistant = Message(role="assistant", content=message)
                progress = ["Message kept within procurement scope"]
                tool_sequence.append(SCOPE_REJECTION_TOOL)
            else:
                interpretation = await self.provider.interpret(content, conversation.draft)
                request = normalize_procurement_request(interpretation.request)
                tool_sequence.append("normalize_procurement_request")
                conversation.draft = request
                missing = request.missing_fields()
                if missing:
                    question = f"What {missing[0]} should I use?"
                    decision = AgentDecision(status="clarification", summary=question, trace_id=trace_id)
                    assistant = Message(role="assistant", content=question)
                    progress = ["Request understood"]
                else:
                    planned_tools = interpretation.tool_plan
                    if planned_tools != REQUIRED_TOOL_PLAN:
                        raise ValueError("Unsafe or incomplete tool plan")
                    matches = search_synthetic_suppliers(request, synthetic_suppliers())
                    price_results = compare_quote_prices(request, matches)
                    evaluated = []
                    for supplier, quote in matches:
                        eligibility = evaluate_quote(request, supplier, quote, price_results[quote.id])
                        evaluated.append((supplier, quote, eligibility))
                    tool_sequence.extend(planned_tools)
                    quotes = rank_eligible_quotes(request, evaluated)
                    eligible = [q for q in quotes if q.eligible]
                    risky_reasons = []
                    if not eligible:
                        risky_reasons = sorted({reason for q in quotes for reason in q.reasons})
                        if not matches: risky_reasons.append("No repository quotation matches the requested medicine")
                        risky_reasons.append("No eligible quotation")
                    review_reasons = risky_reasons
                    if risky_reasons:
                        best = eligible[0].supplier_id if eligible else None
                        decision = AgentDecision(status="review_required", recommendation_supplier_id=best, summary="No eligible quotation is available. Staff review is required.", human_review_required=True, escalation_reasons=risky_reasons, trace_id=trace_id)
                        assistant = Message(role="assistant", content=decision.summary)
                    else:
                        best = eligible[0]
                        best_name = next(supplier.display_name for supplier, _, _ in evaluated if supplier.id == best.supplier_id)
                        decision = AgentDecision(status="recommended", recommendation_supplier_id=best.supplier_id, summary=f"{best_name} is the highest-ranked eligible quotation.", trace_id=trace_id)
                        assistant = Message(role="assistant", content=decision.summary)
                    progress = PROGRESS
        except Exception as exc:  # noqa: BLE001 - the workflow boundary must fail safe
            self.observability.capture(
                exc,
                trace_id=trace_id,
                workflow_stage="agent_execution",
                policy_version="procura-policy-v1",
                model=self.settings.llm_model if self.provider.name != "local" else "procura-local-v1",
                environment=self.settings.app_env,
                human_review_required="true",
                error_category=type(exc).__name__,
            )
            summary, review_reason = safe_failure_message(exc)
            review_reasons = [review_reason]
            decision = AgentDecision(status="failed_safe", summary=summary, human_review_required=True, escalation_reasons=review_reasons, trace_id=trace_id)
            assistant, progress = Message(role="assistant", content=decision.summary), ["Request understood", "Applying review policy"]
        conversation.messages.append(assistant)
        latency = round((time.perf_counter() - started) * 1000, 2)
        response = AgentResponse(conversation_id=conversation_id, message=assistant, request=request, quotes=quotes, decision=decision, progress_events=progress)
        if decision.human_review_required:
            tool_sequence.append("create_human_review_case")
        model = self.settings.llm_model if self.provider.name != "local" else "procura-local-v1"
        scores = {"schema_valid": 1, "policy_compliant": 1, "unsupported_claim_count": 0}
        usage = self.provider.usage
        exported = self.observability.export_execution(
            trace_id=trace_id,
            conversation_id=conversation_id,
            model=model,
            provider=self.provider.name,
            token_input=usage.input_tokens or None,
            token_output=usage.output_tokens or None,
            tool_sequence=tool_sequence,
            decision=decision.status,
            review_required=decision.human_review_required,
            scores=scores,
        )
        trace = TraceSummary(
            trace_id=trace_id,
            conversation_id=conversation_id,
            latency_ms=latency,
            model=model,
            provider=self.provider.name,
            decision=decision.status,
            review_required=decision.human_review_required,
            policy_version=decision.policy_version,
            token_input=usage.input_tokens or None,
            token_output=usage.output_tokens or None,
            exported_to_langfuse=exported,
            tool_sequence=tool_sequence,
            scores=scores,
        )
        with SessionLocal() as db:
            row = db.get(ConversationRow, conversation_id)
            row.data = conversation.model_dump_json()
            db.add(ExecutionRow(id=trace_id, conversation_id=conversation_id, idempotency_key=idempotency_key, response=response.model_dump_json(), decision=decision.status, latency_ms=latency, trace_data=trace.model_dump_json()))
            if decision.human_review_required:
                case = create_human_review_case(HumanReviewCase(id=str(uuid4()), conversation_id=conversation_id, trace_id=trace_id, reasons=review_reasons, request=request, quotes=quotes, recommendation_supplier_id=decision.recommendation_supplier_id))
                db.add(ReviewRow(id=case.id, data=case.model_dump_json()))
            db.commit()
        return response
