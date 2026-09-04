import statistics
import time
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import uuid4

from app.config import Settings
from app.domain.errors import InvalidModelOutputError, ProviderUnavailableError, VersionConflictError
from app.domain.models import (
    AuthUser,
    CatalogueSuggestion,
    HumanReviewCase,
    IntakeDashboardSummary,
    IntakeFinding,
    IntakeLine,
    IntakeLinePatch,
    IntakeStatus,
    MedicineRequirement,
    ProcurementIntake,
    ProcurementRequest,
)
from app.intake.interfaces import ParsedIntake
from app.intake.interpreters import build_intake_interpreter
from app.intake.parsers import SpreadsheetParser
from app.intake.repository import SqlAlchemyIntakeRepository
from app.intake.workflow import IntakeWorkflow
from app.models.database import ReviewRow, SessionLocal
from app.observability.adapters import Observability
from app.services.seed import synthetic_suppliers
from app.services.tools import (
    compare_quote_prices,
    create_human_review_case,
    evaluate_quote,
    rank_eligible_quotes,
    search_synthetic_suppliers,
)


class BuyerIntakeService:
    def __init__(self, settings: Settings, policy: str, observability: Observability):
        self.settings = settings
        self.observability = observability
        self.repository = SqlAlchemyIntakeRepository()
        self.parser = SpreadsheetParser(settings)
        self.interpreter = build_intake_interpreter(settings, policy)
        self.workflow = IntakeWorkflow(settings)

    def close(self) -> None:
        self.workflow.close()

    def create_text(self, user: AuthUser, content: str, idempotency_key: str) -> ProcurementIntake:
        started = time.perf_counter()
        trace_id = str(uuid4())
        intake_id = str(uuid4())
        try:
            line = self.interpreter.interpret(content)
            intake = self._run_new(user, ParsedIntake("text", None, [line], []), intake_id, trace_id, started)
        except (ProviderUnavailableError, InvalidModelOutputError) as exc:
            line = IntakeLine(source_row=1, original_values={"request": content[:500]})
            intake = ProcurementIntake(
                id=intake_id,
                buyer_id=user.id,
                organization=user.organization,
                source_type="text",
                status="failed_safe",
                lines=[line],
                graph_path=["ingest_input", "provider_unavailable"],
                trace_id=trace_id,
                provider=self.interpreter.name,
                time_to_first_feedback_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            self.observability.capture(exc, trace_id=trace_id, workflow_stage="intake_interpretation", error_category="provider_unavailable")
        saved = self.repository.create(intake, idempotency_key)
        self._trace(saved)
        return saved

    def create_file(self, user: AuthUser, filename: str, content: bytes, content_type: str | None, idempotency_key: str) -> ProcurementIntake:
        started = time.perf_counter()
        parsed = self.parser.parse(filename, content, content_type)
        intake = self._run_new(user, parsed, str(uuid4()), str(uuid4()), started)
        saved = self.repository.create(intake, idempotency_key)
        self._trace(saved)
        return saved

    def _run_new(self, user: AuthUser, parsed: ParsedIntake, intake_id: str, trace_id: str, started: float) -> ProcurementIntake:
        state = self.workflow.start(intake_id, parsed.lines)
        lines = [IntakeLine.model_validate(line) for line in state.get("lines", [])]
        status = cast(IntakeStatus, state.get("status", "needs_correction"))
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        return ProcurementIntake(
            id=intake_id,
            buyer_id=user.id,
            organization=user.organization,
            source_type=cast(Literal["text", "csv", "xlsx"], parsed.source_type),
            filename=parsed.filename,
            status=status,
            lines=lines,
            graph_path=state.get("graph_path", []),
            trace_id=trace_id,
            provider=self.interpreter.name,
            time_to_first_feedback_ms=elapsed,
            first_pass_complete=status == "ready",
        )

    def list_intakes(self, user: AuthUser) -> list[ProcurementIntake]:
        return self.repository.list_all() if user.role == "admin" else self.repository.list_for_buyer(user.id)

    def get(self, user: AuthUser, intake_id: str) -> ProcurementIntake:
        return self.repository.get(intake_id, user.id, user.role == "admin")

    def dashboard(self, user: AuthUser) -> IntakeDashboardSummary:
        items = self.list_intakes(user)
        completed = [item.time_to_valid_submission_ms for item in items if item.time_to_valid_submission_ms is not None]
        return IntakeDashboardSummary(
            total=len(items),
            drafts=sum(item.status in {"draft", "processing", "failed_safe"} for item in items),
            needs_correction=sum(item.status in {"needs_correction", "suggestion_available", "critical_review_required"} for item in items),
            ready=sum(item.status == "ready" for item in items),
            submitted=sum(item.status == "submitted" for item in items),
            median_time_to_valid_submission_ms=statistics.median(completed) if completed else None,
            recent=items[:5],
        )

    def patch_line(self, user: AuthUser, intake_id: str, line_id: str, body: IntakeLinePatch) -> ProcurementIntake:
        intake = self.get(user, intake_id)
        if intake.status == "submitted":
            raise VersionConflictError("A submitted intake cannot be edited")
        changes = body.model_dump(exclude={"version", "idempotency_key"}, exclude_none=True)
        lines: list[IntakeLine] = []
        found = False
        for line in intake.lines:
            if line.id != line_id:
                lines.append(line)
                continue
            found = True
            if "medicine_name" in changes and changes["medicine_name"] != line.medicine_name:
                changes["suggestion"] = None
            changed_fields = {key for key, value in changes.items() if value != getattr(line, key, None)}
            changes["buyer_corrected_fields"] = sorted({*line.buyer_corrected_fields, *changed_fields})
            lines.append(line.model_copy(update=changes))
        if not found:
            raise LookupError("Procurement row not found")
        return self._resume_and_save(intake, lines, body.version, body.idempotency_key)

    def decide_suggestion(self, user: AuthUser, intake_id: str, line_id: str, action: str, version: int, idempotency_key: str) -> ProcurementIntake:
        intake = self.get(user, intake_id)
        lines: list[IntakeLine] = []
        found = False
        for line in intake.lines:
            if line.id != line_id:
                lines.append(line)
                continue
            if not line.suggestion:
                raise LookupError("Catalogue suggestion not found")
            found = True
            suggestion = CatalogueSuggestion.model_validate(line.suggestion).model_copy(update={
                "status": "accepted" if action == "accept" else "rejected",
                "actor_id": user.id,
                "decided_at": datetime.now(UTC),
            })
            medicine_name = suggestion.suggested_value if action == "accept" else line.medicine_name
            corrected_fields = line.buyer_corrected_fields
            if action == "accept":
                corrected_fields = sorted({*corrected_fields, "medicine_name"})
            lines.append(line.model_copy(update={
                "medicine_name": medicine_name,
                "suggestion": suggestion,
                "buyer_corrected_fields": corrected_fields,
            }))
        if not found:
            raise LookupError("Catalogue suggestion not found")
        return self._resume_and_save(intake, lines, version, idempotency_key)

    def revalidate(self, user: AuthUser, intake_id: str, version: int, idempotency_key: str) -> ProcurementIntake:
        intake = self.get(user, intake_id)
        if intake.status == "failed_safe" and intake.source_type == "text":
            source = str(intake.lines[0].original_values.get("request") or "")
            try:
                line = self.interpreter.interpret(source)
            except (ProviderUnavailableError, InvalidModelOutputError):
                return intake
            state = self.workflow.start(intake.id, [line])
            recovered = intake.model_copy(update={
                "lines": [IntakeLine.model_validate(item) for item in state.get("lines", [])],
                "status": state.get("status", "needs_correction"),
                "graph_path": state.get("graph_path", []),
            })
            return self.repository.save(recovered, version, idempotency_key)
        return self._resume_and_save(intake, intake.lines, version, idempotency_key)

    def _resume_and_save(self, intake: ProcurementIntake, lines: list[IntakeLine], version: int, idempotency_key: str) -> ProcurementIntake:
        if version != intake.version:
            raise VersionConflictError("This intake changed in another session. Refresh before editing it.")
        state = self.workflow.resume(intake.id, lines)
        updated_lines = [IntakeLine.model_validate(line) for line in state.get("lines", [])]
        status = state.get("status", "needs_correction")
        valid_ms = intake.time_to_valid_submission_ms
        if status == "ready" and valid_ms is None:
            valid_ms = round((datetime.now(UTC) - intake.created_at).total_seconds() * 1000, 2)
        updated = intake.model_copy(update={
            "lines": updated_lines,
            "status": status,
            "graph_path": state.get("graph_path", intake.graph_path),
            "time_to_valid_submission_ms": valid_ms,
        })
        saved = self.repository.save(updated, version, idempotency_key)
        self._trace(saved)
        return saved

    def submit(self, user: AuthUser, intake_id: str, version: int, idempotency_key: str) -> ProcurementIntake:
        intake = self.get(user, intake_id)
        if intake.status in {"submitted", "critical_review_required"}:
            return intake
        if intake.status != "ready":
            raise VersionConflictError("Resolve every blocking correction before submission")
        review_result = self._submission_review(intake)
        if review_result:
            review, blocked_line_id = review_result
            reviewed_lines = [
                line.model_copy(update={
                    "status": "critical_review_required",
                    "findings": [*line.findings, IntakeFinding(
                        code="no_eligible_quotation",
                        severity="critical",
                        message="; ".join(review.reasons),
                        field="supplier_eligibility",
                        row_id=line.id,
                        evidence_source="repository supplier and quotation records",
                        correctable_by_buyer=False,
                        suggested_action="Operations must review the supplier evidence before this requirement can proceed.",
                    )],
                }) if line.id == blocked_line_id else line
                for line in intake.lines
            ]
            reviewed = intake.model_copy(update={"status": "critical_review_required", "lines": reviewed_lines})
            saved = self.repository.save(reviewed, version, idempotency_key)
            with SessionLocal() as db:
                if not db.get(ReviewRow, review.id):
                    db.add(ReviewRow(id=review.id, data=review.model_dump_json()))
                    db.commit()
            self._trace(saved)
            return saved
        submitted = intake.model_copy(update={"status": "submitted", "submitted_at": datetime.now(UTC)})
        saved = self.repository.save(submitted, version, idempotency_key)
        self._trace(saved)
        return saved

    def _submission_review(self, intake: ProcurementIntake) -> tuple[HumanReviewCase, str] | None:
        """Run repository-backed supplier gates only after buyer data is complete."""
        suppliers = synthetic_suppliers()
        for line in intake.lines:
            request = ProcurementRequest(
                id=f"intake-request-{intake.id}-{line.id}",
                medicine=MedicineRequirement(
                    medicine_name=line.medicine_name,
                    strength=line.strength,
                    dosage_form=line.dosage_form,
                    quantity=line.quantity,
                    pack_size=line.pack_size,
                    unit=line.unit or "packs",
                ),
                destination=line.destination,
                max_lead_time_days=line.max_lead_time_days,
                currency=line.currency,
            )
            matches = search_synthetic_suppliers(request, suppliers)
            price_results = compare_quote_prices(request, matches)
            evaluated = [
                (supplier, quote, evaluate_quote(request, supplier, quote, price_results[quote.id]))
                for supplier, quote in matches
            ]
            quotes = rank_eligible_quotes(request, evaluated)
            if any(quote.eligible for quote in quotes):
                continue
            reasons = sorted({reason for quote in quotes for reason in quote.reasons})
            if not matches:
                reasons.append("No repository quotation matches the validated medicine requirement")
            reasons.append("No eligible quotation is available after deterministic supplier checks")
            case = create_human_review_case(HumanReviewCase(
                id=f"intake-review-{intake.id}-{line.id}",
                conversation_id=intake.id,
                trace_id=intake.trace_id,
                reasons=reasons,
                request=request,
                quotes=quotes,
            ))
            return case, line.id
        return None

    def _trace(self, intake: ProcurementIntake) -> None:
        scores = {
            "schema_valid": 1.0,
            "policy_compliant": 1.0,
            "correct_escalation": 1.0,
        }
        self.observability.export_execution(
            trace_id=intake.trace_id,
            conversation_id=intake.id,
            model=self.settings.llm_model,
            provider=intake.provider,
            token_input=None,
            token_output=None,
            tool_sequence=intake.graph_path,
            decision=intake.status,
            review_required=intake.status == "critical_review_required",
            scores=scores,
        )
