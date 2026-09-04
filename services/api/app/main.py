import json
import statistics
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select

from app.config import get_settings
from app.domain.errors import FileValidationError, PersistenceError, VersionConflictError
from app.domain.models import (
    AdminOverview,
    AdminUserPage,
    AdminUserSummary,
    AgentResponse,
    AuthUser,
    Conversation,
    CustomerDashboardSummary,
    DashboardDecision,
    HumanReviewCase,
    IntakeActionRequest,
    IntakeDashboardSummary,
    IntakeLinePatch,
    IntakeSuggestionDecisionRequest,
    LoginRequest,
    MedicineCatalogItem,
    MessageRequest,
    Notification,
    NotificationReadRequest,
    OperationsSummary,
    ProcurementIntake,
    ProcurementLifecycle,
    PublishProcurementRequest,
    ReviewBrief,
    ReviewDecisionRequest,
    SignupRequest,
    SupplierDashboardSummary,
    SupplierProfileSubmissionRequest,
    SupplierQuoteDraft,
    SupplierQuoteDraftRequest,
    SupplierQuoteSubmissionRequest,
    SupplierRequestAssignment,
    SupplierRequestResponse,
    SupplierRequestResponseRequest,
    SupplierSubmission,
    SupplierSubmissionDecisionRequest,
    TextIntakeRequest,
    TraceSummary,
)
from app.intake.service import BuyerIntakeService
from app.models.database import (
    ExecutionRow,
    NotificationRow,
    ProcurementIntakeRow,
    ProcurementLifecycleRow,
    QuoteRow,
    RequestSupplierRow,
    ResourceOwnerRow,
    ReviewRow,
    SessionLocal,
    SupplierResponseRow,
    SupplierRow,
    SupplierSubmissionRow,
    UserRow,
    init_db,
)
from app.observability.adapters import Observability
from app.services.agent_service import AgentService
from app.services.auth import (
    admin_user,
    auth_limiter,
    clear_session,
    create_session,
    current_user,
    normalize_email,
    password_hash,
    public_user,
    seed_local_accounts,
    staff_user,
)
from app.services.catalog import list_medicine_catalog
from app.services.procurement_lifecycle import (
    add_event,
    add_notification,
    current_supplier,
    evaluate_response_set,
    evidence_fingerprint,
    notification,
    procurement_lifecycle,
    publish_execution,
    submit_supplier_response,
    supplier_assignments,
)
from app.services.role_assistants import create_review_brief, draft_supplier_quote
from app.services.scope import SCOPE_REJECTION_TOOL
from app.services.seed import seed_supplier_database, synthetic_suppliers
from app.services.tools import canonicalize_dosage_form, canonicalize_medicine_name, canonicalize_strength

settings = get_settings()
policy = settings.policy_path.read_text()
if "procura-policy-v1" not in policy: raise RuntimeError("Policy version missing")
observability = Observability(settings)
service = AgentService(settings, policy, observability)
intake_service = BuyerIntakeService(settings, policy, observability)

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    seed_supplier_database()
    seed_local_accounts(settings)
    try:
        yield
    finally:
        await service.close()

app = FastAPI(title="Procura API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.web_origin], allow_credentials=True, allow_methods=["GET", "POST", "PATCH"], allow_headers=["Content-Type", "Idempotency-Key"])


@app.middleware("http")
async def security_boundary(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin and origin != settings.web_origin:
            return Response("Origin not allowed", status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else response.headers.get("Cache-Control", "no-cache")
    return response


def require_owner(resource_type: str, resource_id: str, user: AuthUser) -> None:
    with SessionLocal() as db:
        owner = db.scalar(select(ResourceOwnerRow).where(ResourceOwnerRow.resource_type == resource_type, ResourceOwnerRow.resource_id == resource_id, ResourceOwnerRow.user_id == user.id))
        if not owner and user.role != "admin":
            raise HTTPException(404, "Resource not found")


def execution_decision(row: ExecutionRow) -> DashboardDecision:
    trace = TraceSummary.model_validate_json(row.trace_data)
    result = AgentResponse.model_validate_json(row.response)
    return DashboardDecision(
        **trace.model_dump(),
        medicine_name=result.request.medicine.medicine_name,
        strength=result.request.medicine.strength,
        dosage_form=result.request.medicine.dosage_form,
    )


def is_scope_rejection(row: ExecutionRow) -> bool:
    trace = TraceSummary.model_validate_json(row.trace_data)
    return SCOPE_REJECTION_TOOL in trace.tool_sequence


@app.get("/health")
def health():
    return {
        "status": "ok",
        "provider": service.provider.name,
        "intake_engine": "langgraph",
        "policy_version": "procura-policy-v1",
    }


def buyer_or_admin(user: AuthUser = Depends(current_user)) -> AuthUser:
    if user.role not in {"buyer", "admin"}:
        raise HTTPException(403, "Buyer workspace required")
    return user


def intake_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FileValidationError):
        return HTTPException(422, str(exc))
    if isinstance(exc, VersionConflictError):
        return HTTPException(409, str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(404, str(exc))
    if isinstance(exc, PersistenceError):
        return HTTPException(503, "The intake could not be saved. Your source file was not retained.")
    if isinstance(exc, ValueError):
        return HTTPException(422, str(exc))
    return HTTPException(503, "The intake could not be processed safely. Retry without losing your source file.")


@app.post("/api/intakes/text", response_model=ProcurementIntake, status_code=201)
def create_text_intake(body: TextIntakeRequest, user: AuthUser = Depends(buyer_or_admin)):
    try:
        return intake_service.create_text(user, body.content, body.idempotency_key)
    except Exception as exc:
        observability.capture(exc, workflow_stage="text_intake", error_category="intake_failure")
        raise intake_error(exc) from exc


@app.post("/api/intakes/files", response_model=ProcurementIntake, status_code=201)
async def create_file_intake(
    file: UploadFile = File(...),
    idempotency_key: str = Form(..., min_length=8, max_length=120),
    user: AuthUser = Depends(buyer_or_admin),
):
    content = await file.read(settings.intake_max_file_bytes + 1)
    await file.close()
    try:
        return intake_service.create_file(user, file.filename or "upload", content, file.content_type, idempotency_key)
    except Exception as exc:
        observability.capture(exc, workflow_stage="file_intake", error_category="intake_failure")
        raise intake_error(exc) from exc


@app.get("/api/intakes", response_model=list[ProcurementIntake])
def list_intakes(user: AuthUser = Depends(buyer_or_admin)):
    try:
        return intake_service.list_intakes(user)
    except Exception as exc:
        raise intake_error(exc) from exc


@app.get("/api/intakes/summary", response_model=IntakeDashboardSummary)
def intake_dashboard(user: AuthUser = Depends(buyer_or_admin)):
    try:
        return intake_service.dashboard(user)
    except Exception as exc:
        raise intake_error(exc) from exc


@app.get("/api/intakes/template.csv")
def intake_template(_: AuthUser = Depends(buyer_or_admin)):
    content = "medicine,strength,dosage form,quantity,pack size,destination,lead time,currency\n"
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="procura-intake-template.csv"'},
    )


@app.get("/api/intakes/{intake_id}", response_model=ProcurementIntake)
def get_intake(intake_id: str, user: AuthUser = Depends(buyer_or_admin)):
    try:
        return intake_service.get(user, intake_id)
    except Exception as exc:
        raise intake_error(exc) from exc


@app.patch("/api/intakes/{intake_id}/lines/{line_id}", response_model=ProcurementIntake)
def patch_intake_line(
    intake_id: str,
    line_id: str,
    body: IntakeLinePatch,
    user: AuthUser = Depends(buyer_or_admin),
):
    try:
        return intake_service.patch_line(user, intake_id, line_id, body)
    except Exception as exc:
        raise intake_error(exc) from exc


@app.post("/api/intakes/{intake_id}/lines/{line_id}/suggestion", response_model=ProcurementIntake)
def decide_intake_suggestion(
    intake_id: str,
    line_id: str,
    body: IntakeSuggestionDecisionRequest,
    user: AuthUser = Depends(buyer_or_admin),
):
    try:
        return intake_service.decide_suggestion(
            user, intake_id, line_id, body.action, body.version, body.idempotency_key
        )
    except Exception as exc:
        raise intake_error(exc) from exc


@app.post("/api/intakes/{intake_id}/revalidate", response_model=ProcurementIntake)
def revalidate_intake(
    intake_id: str,
    body: IntakeActionRequest,
    user: AuthUser = Depends(buyer_or_admin),
):
    try:
        return intake_service.revalidate(user, intake_id, body.version, body.idempotency_key)
    except Exception as exc:
        raise intake_error(exc) from exc


@app.post("/api/intakes/{intake_id}/submit", response_model=ProcurementIntake)
def submit_intake(
    intake_id: str,
    body: IntakeActionRequest,
    user: AuthUser = Depends(buyer_or_admin),
):
    try:
        return intake_service.submit(user, intake_id, body.version, body.idempotency_key)
    except Exception as exc:
        raise intake_error(exc) from exc


@app.post("/api/auth/signup", response_model=AuthUser, status_code=201)
def signup(body: SignupRequest, request: Request, response: Response):
    email = normalize_email(str(body.email))
    auth_limiter.check(f"signup:{request.client.host if request.client else 'unknown'}")
    with SessionLocal() as db:
        if db.scalar(select(UserRow).where(UserRow.email == email)):
            raise HTTPException(409, "An account with that email already exists")
        row = UserRow(id=str(uuid4()), email=email, display_name=body.display_name, organization=body.organization, password_hash=password_hash.hash(body.password), role=body.account_type)
        db.add(row); db.flush()
        if body.account_type == "supplier":
            supplier_id = f"supplier-{row.id}"
            db.add(SupplierRow(id=supplier_id, display_name=body.organization, authorization_status="missing", authorization_expiry=None, destinations_json="[]", cold_chain=False, reliability_score=0, synthetic=True))
            db.add(ResourceOwnerRow(id=str(uuid4()), resource_type="supplier_profile", resource_id=supplier_id, user_id=row.id))
        db.commit(); db.refresh(row)
        user = public_user(row)
    create_session(user.id, response, settings)
    return user


@app.post("/api/auth/login", response_model=AuthUser)
def login(body: LoginRequest, request: Request, response: Response):
    email = normalize_email(str(body.email))
    auth_limiter.check(f"login:{request.client.host if request.client else 'unknown'}:{email}")
    with SessionLocal() as db:
        row = db.scalar(select(UserRow).where(UserRow.email == email))
        if not row or not row.is_active or not password_hash.verify(body.password, row.password_hash):
            raise HTTPException(401, "Invalid email or password")
        user = public_user(row)
    create_session(user.id, response, settings)
    return user


@app.post("/api/auth/logout", status_code=204)
def logout(request: Request, response: Response):
    clear_session(request, response, settings)
    response.status_code = 204


@app.get("/api/auth/me", response_model=AuthUser)
def me(user: AuthUser = Depends(current_user)): return user


@app.get("/api/dashboard/summary", response_model=CustomerDashboardSummary)
def customer_dashboard(user: AuthUser = Depends(current_user)):
    if user.role not in {"buyer", "admin"}:
        raise HTTPException(403, "Customer workspace required")
    with SessionLocal() as db:
        conversation_ids = list(db.scalars(select(ResourceOwnerRow.resource_id).where(ResourceOwnerRow.resource_type == "conversation", ResourceOwnerRow.user_id == user.id)).all())
        all_rows = db.scalars(select(ExecutionRow).where(ExecutionRow.conversation_id.in_(conversation_ids)).order_by(ExecutionRow.created_at.desc())).all() if conversation_ids else []
        rows = [row for row in all_rows if not is_scope_rejection(row)]
        # Opening the workspace creates an empty conversation shell. Count it as
        # a request only after the buyer submits a message, and use the latest
        # execution so clarification turns cannot inflate the dashboard totals.
        latest_rows: dict[str, ExecutionRow] = {}
        for row in rows:
            latest_rows.setdefault(row.conversation_id, row)
        requests = list(latest_rows.values())
        evaluated = [row for row in requests if row.decision != "clarification"]
        review_cases = [HumanReviewCase.model_validate_json(row.data) for row in db.scalars(select(ReviewRow)).all()]
        review_count = sum(case.conversation_id in conversation_ids and case.status == "open" for case in review_cases)
        recent_decisions = [execution_decision(row) for row in requests[:5]]
        return CustomerDashboardSummary(
            conversation_count=len(requests),
            execution_count=len(evaluated),
            recommendation_count=sum(row.decision == "recommended" for row in requests),
            review_count=review_count,
            recent_decisions=recent_decisions,
        )


@app.get("/api/catalog/medicines", response_model=list[MedicineCatalogItem])
def medicine_catalog(
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=6, ge=1, le=20),
    user: AuthUser = Depends(current_user),
):
    if user.role not in {"buyer", "admin"}:
        raise HTTPException(403, "Customer workspace required")
    return list_medicine_catalog(q, limit)


@app.get("/api/supplier/dashboard", response_model=SupplierDashboardSummary)
def supplier_dashboard(user: AuthUser = Depends(current_user)):
    if user.role != "supplier":
        raise HTTPException(403, "Supplier workspace required")
    with SessionLocal() as db:
        link = db.scalar(select(ResourceOwnerRow).where(ResourceOwnerRow.resource_type == "supplier_profile", ResourceOwnerRow.user_id == user.id))
        submission_rows = db.scalars(select(SupplierSubmissionRow).where(SupplierSubmissionRow.user_id == user.id).order_by(SupplierSubmissionRow.created_at.desc())).all()
    if not link:
        raise HTTPException(404, "Supplier profile not found")
    supplier = next((item for item in synthetic_suppliers() if item.id == link.resource_id), None)
    if not supplier:
        raise HTTPException(404, "Supplier profile not found")
    submissions = [supplier_submission(row) for row in submission_rows]
    return SupplierDashboardSummary(supplier=supplier, quote_count=len(supplier.quotes), eligible_destination_count=len(supplier.capability.destinations), compliance_state=supplier.authorization.status, submissions=submissions)


def supplier_submission(row: SupplierSubmissionRow) -> SupplierSubmission:
    return SupplierSubmission(id=row.id, supplier_id=row.supplier_id, kind=row.kind, payload=json.loads(row.payload), status=row.status, reviewer_note=row.reviewer_note, reviewed_at=row.reviewed_at, created_at=row.created_at)


def linked_supplier_id(user: AuthUser, db) -> str:
    if user.role != "supplier":
        raise HTTPException(403, "Supplier workspace required")
    link = db.scalar(select(ResourceOwnerRow).where(ResourceOwnerRow.resource_type == "supplier_profile", ResourceOwnerRow.user_id == user.id))
    if not link:
        raise HTTPException(404, "Supplier profile not found")
    return link.resource_id


@app.post("/api/executions/{trace_id}/publish", response_model=ProcurementLifecycle, status_code=201)
def publish_procurement(trace_id: str, body: PublishProcurementRequest, user: AuthUser = Depends(current_user)):
    if user.role not in {"buyer", "admin"}:
        raise HTTPException(403, "Buyer workspace required")
    with SessionLocal() as db:
        execution = db.get(ExecutionRow, trace_id)
        if not execution:
            raise HTTPException(404, "Procurement decision not found")
        owner = db.scalar(select(ResourceOwnerRow).where(ResourceOwnerRow.resource_type == "conversation", ResourceOwnerRow.resource_id == execution.conversation_id))
        if not owner or (owner.user_id != user.id and user.role != "admin"):
            raise HTTPException(404, "Procurement decision not found")
        try:
            return publish_execution(db, execution, owner.user_id, body.idempotency_key)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(404, "Procurement decision not found") from exc


@app.get("/api/procurement-requests", response_model=list[ProcurementLifecycle])
def procurement_requests(user: AuthUser = Depends(current_user)):
    if user.role not in {"buyer", "reviewer", "admin"}:
        raise HTTPException(403, "Buyer or staff workspace required")
    with SessionLocal() as db:
        query = select(ProcurementLifecycleRow).order_by(ProcurementLifecycleRow.updated_at.desc())
        if user.role == "buyer":
            query = query.where(ProcurementLifecycleRow.buyer_id == user.id)
        return [procurement_lifecycle(db, row) for row in db.scalars(query).all()]


@app.get("/api/procurement-requests/{request_id}", response_model=ProcurementLifecycle)
def procurement_request(request_id: str, user: AuthUser = Depends(current_user)):
    with SessionLocal() as db:
        row = db.get(ProcurementLifecycleRow, request_id)
        if not row:
            raise HTTPException(404, "Procurement request not found")
        allowed = user.role in {"reviewer", "admin"} or row.buyer_id == user.id
        if user.role == "supplier":
            supplier_id = linked_supplier_id(user, db)
            allowed = bool(db.scalar(select(RequestSupplierRow).where(RequestSupplierRow.request_id == row.id, RequestSupplierRow.supplier_id == supplier_id)))
        if not allowed:
            raise HTTPException(404, "Procurement request not found")
        return procurement_lifecycle(db, row)


@app.get("/api/supplier/requests", response_model=list[SupplierRequestAssignment])
def supplier_requests(user: AuthUser = Depends(current_user)):
    with SessionLocal() as db:
        return supplier_assignments(db, linked_supplier_id(user, db))


@app.post("/api/supplier/requests/{request_id}/responses", response_model=SupplierRequestResponse, status_code=201)
def respond_to_buyer_request(request_id: str, body: SupplierRequestResponseRequest, user: AuthUser = Depends(current_user)):
    with SessionLocal() as db:
        supplier_id = linked_supplier_id(user, db)
        lifecycle = db.get(ProcurementLifecycleRow, request_id)
        supplier = current_supplier(supplier_id)
        if not lifecycle or not supplier:
            raise HTTPException(404, "Buyer request not found")
        try:
            return submit_supplier_response(db, lifecycle, supplier, user.id, body)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc


@app.get("/api/notifications", response_model=list[Notification])
def notifications(user: AuthUser = Depends(current_user)):
    with SessionLocal() as db:
        rows = db.scalars(select(NotificationRow).where(NotificationRow.user_id == user.id).order_by(NotificationRow.created_at.desc()).limit(50)).all()
        return [notification(row) for row in rows]


@app.post("/api/notifications/{notification_id}/read", response_model=Notification)
def read_notification(notification_id: str, _: NotificationReadRequest, user: AuthUser = Depends(current_user)):
    with SessionLocal() as db:
        row = db.get(NotificationRow, notification_id)
        if not row or row.user_id != user.id:
            raise HTTPException(404, "Notification not found")
        row.is_read = True
        db.commit(); db.refresh(row)
        return notification(row)


def create_supplier_submission(user: AuthUser, kind: str, payload: dict, idempotency_key: str) -> SupplierSubmission:
    with SessionLocal() as db:
        existing = db.scalar(select(SupplierSubmissionRow).where(SupplierSubmissionRow.idempotency_key == idempotency_key))
        if existing:
            if existing.user_id != user.id:
                raise HTTPException(409, "Idempotency key is already in use")
            return supplier_submission(existing)
        supplier_id = linked_supplier_id(user, db)
        row = SupplierSubmissionRow(id=str(uuid4()), supplier_id=supplier_id, user_id=user.id, kind=kind, payload=json.dumps(payload), status="pending", idempotency_key=idempotency_key)
        db.add(row); db.commit(); db.refresh(row)
        return supplier_submission(row)


@app.post("/api/supplier/submissions/profile", response_model=SupplierSubmission, status_code=201)
def submit_supplier_profile(body: SupplierProfileSubmissionRequest, user: AuthUser = Depends(current_user)):
    payload = body.model_dump(mode="json", exclude={"idempotency_key"})
    return create_supplier_submission(user, "profile", payload, body.idempotency_key)


@app.post("/api/supplier/submissions/quotes", response_model=SupplierSubmission, status_code=201)
def submit_supplier_quote(body: SupplierQuoteSubmissionRequest, user: AuthUser = Depends(current_user)):
    payload = body.model_dump(mode="json", exclude={"idempotency_key"})
    return create_supplier_submission(user, "quote", payload, body.idempotency_key)


@app.post("/api/supplier/quote-drafts", response_model=SupplierQuoteDraft)
def prepare_supplier_quote(body: SupplierQuoteDraftRequest, user: AuthUser = Depends(current_user)):
    if user.role != "supplier":
        raise HTTPException(403, "Supplier workspace required")
    return draft_supplier_quote(body.content, service.provider.name)


@app.get("/api/supplier-submissions", response_model=list[SupplierSubmission])
def list_supplier_submissions(_: AuthUser = Depends(staff_user)):
    with SessionLocal() as db:
        rows = db.scalars(select(SupplierSubmissionRow).order_by(SupplierSubmissionRow.created_at.desc())).all()
        return [supplier_submission(row) for row in rows]


@app.post("/api/supplier-submissions/{submission_id}/decision", response_model=SupplierSubmission)
def decide_supplier_submission(submission_id: str, body: SupplierSubmissionDecisionRequest, user: AuthUser = Depends(staff_user)):
    with SessionLocal() as db:
        row = db.get(SupplierSubmissionRow, submission_id)
        if not row:
            raise HTTPException(404, "Supplier submission not found")
        keys = json.loads(row.decision_keys or "[]")
        if body.idempotency_key in keys:
            return supplier_submission(row)
        if row.status != "pending":
            raise HTTPException(409, "Supplier submission has already been decided")
        if body.action == "approve":
            payload = json.loads(row.payload)
            supplier = db.get(SupplierRow, row.supplier_id)
            if not supplier:
                raise HTTPException(404, "Supplier profile not found")
            if row.kind == "profile":
                expiry = date.fromisoformat(payload["authorization_expiry"])
                supplier.display_name = payload["display_name"]
                supplier.destinations_json = json.dumps(payload["destinations"])
                supplier.cold_chain = payload["cold_chain"]
                supplier.authorization_expiry = expiry
                supplier.authorization_status = "authorized" if expiry >= datetime.now(UTC).date() else "expired"
            else:
                quote_id = payload.get("quote_id")
                existing_quote = db.get(QuoteRow, quote_id) if quote_id else None
                if existing_quote and existing_quote.supplier_id != row.supplier_id:
                    raise HTTPException(403, "Quotation does not belong to this supplier")
                if payload["action"] == "withdraw":
                    if not existing_quote:
                        raise HTTPException(404, "Quotation not found")
                    db.delete(existing_quote)
                else:
                    quote = existing_quote or QuoteRow(id=f"supplier-quote-{row.id}", supplier_id=row.supplier_id)
                    quote.currency = payload["currency"]
                    quote.lead_time_days = payload["lead_time_days"]
                    quote.medicine_name = canonicalize_medicine_name(payload["medicine_name"])
                    quote.strength = canonicalize_strength(payload["strength"])
                    quote.dosage_form = canonicalize_dosage_form(payload["dosage_form"])
                    quote.pack_size = payload["pack_size"]
                    quote.quantity_packs = payload["available_quantity_packs"]
                    quote.unit_price = payload["unit_price"]
                    db.add(quote)
        row.status = "approved" if body.action == "approve" else "rejected"
        row.reviewer_id = user.id
        row.reviewer_note = body.note
        row.reviewed_at = datetime.now(UTC)
        keys.append(body.idempotency_key); row.decision_keys = json.dumps(keys)
        db.commit(); db.refresh(row)
        return supplier_submission(row)


@app.post("/api/conversations", response_model=Conversation, status_code=201)
def create_conversation(user: AuthUser = Depends(current_user)):
    if user.role not in {"buyer", "admin"}:
        raise HTTPException(403, "Customer workspace required")
    conversation = service.create_conversation()
    with SessionLocal() as db:
        db.add(ResourceOwnerRow(id=str(uuid4()), resource_type="conversation", resource_id=conversation.id, user_id=user.id)); db.commit()
    return conversation


@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
def get_conversation(conversation_id: str, user: AuthUser = Depends(current_user)):
    require_owner("conversation", conversation_id, user)
    result = service.get_conversation(conversation_id)
    if not result: raise HTTPException(404, "Conversation not found")
    return result


@app.post("/api/conversations/{conversation_id}/messages", response_model=AgentResponse)
async def post_message(conversation_id: str, body: MessageRequest, user: AuthUser = Depends(current_user)):
    if user.role not in {"buyer", "admin"}:
        raise HTTPException(403, "Customer workspace required")
    require_owner("conversation", conversation_id, user)
    try: return await service.execute(conversation_id, body.content, body.idempotency_key, body.simulate_tool_timeout)
    except KeyError as exc: raise HTTPException(404, "Conversation not found") from exc


@app.get("/api/conversations/{conversation_id}/events")
def events(conversation_id: str, user: AuthUser = Depends(current_user)):
    require_owner("conversation", conversation_id, user)
    async def stream():
        for event in ["Request understood", "Checking supplier eligibility", "Comparing quotations", "Applying review policy", "Recommendation ready"]:
            yield f"event: progress\ndata: {json.dumps({'message': event})}\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/reviews", response_model=list[HumanReviewCase])
def reviews(_: AuthUser = Depends(staff_user)):
    with SessionLocal() as db: return [HumanReviewCase.model_validate_json(r.data) for r in db.scalars(select(ReviewRow).order_by(ReviewRow.created_at.desc())).all()]


@app.get("/api/reviews/{review_id}", response_model=HumanReviewCase)
def review(review_id: str, _: AuthUser = Depends(staff_user)):
    with SessionLocal() as db:
        row = db.get(ReviewRow, review_id)
        if not row: raise HTTPException(404, "Review not found")
        return HumanReviewCase.model_validate_json(row.data)


@app.get("/api/reviews/{review_id}/brief", response_model=ReviewBrief)
def review_brief(review_id: str, _: AuthUser = Depends(staff_user)):
    with SessionLocal() as db:
        row = db.get(ReviewRow, review_id)
        if not row:
            raise HTTPException(404, "Review not found")
        return create_review_brief(HumanReviewCase.model_validate_json(row.data), service.provider.name)


@app.post("/api/reviews/{review_id}/decision", response_model=HumanReviewCase)
def review_decision(review_id: str, body: ReviewDecisionRequest, user: AuthUser = Depends(staff_user)):
    with SessionLocal() as db:
        row = db.get(ReviewRow, review_id)
        if not row: raise HTTPException(404, "Review not found")
        keys = json.loads(row.action_keys)
        case = HumanReviewCase.model_validate_json(row.data)
        if body.idempotency_key in keys: return case
        if case.status != "open": raise HTTPException(409, "Review already decided")
        supplier_response = db.scalar(select(SupplierResponseRow).where(SupplierResponseRow.review_id == review_id))
        lifecycle = db.get(ProcurementLifecycleRow, supplier_response.request_id) if supplier_response else None
        if body.action == "approve" and supplier_response and lifecycle:
            supplier = current_supplier(supplier_response.supplier_id)
            if not supplier:
                raise HTTPException(409, "The supplier profile is unavailable. Approval remains blocked.")
            request = case.request
            payload = json.loads(supplier_response.response_json)
            current_hash = evidence_fingerprint(request, supplier, payload)
            _, scores, target_score = evaluate_response_set(db, lifecycle, supplier_response)
            case.quotes = scores
            if not target_score or not target_score.eligible:
                case.reasons = list(target_score.reasons if target_score else ["Supplier evidence could not be revalidated"])
                row.data = case.model_dump_json()
                supplier_response.status = "evidence_changed"
                add_event(db, lifecycle.id, user.id, user.role, "approval_blocked", "Approval was blocked because current supplier evidence is no longer eligible.")
                add_notification(db, lifecycle.buyer_id, lifecycle.id, "Approval paused", "Current supplier evidence no longer passes the request checks.")
                db.commit()
                raise HTTPException(409, "Approval blocked: current supplier evidence is no longer eligible. Review the refreshed reasons.")
            if current_hash != supplier_response.evidence_hash:
                supplier_response.evidence_hash = current_hash
                supplier_response.status = "evidence_changed"
                case.reasons = ["Supplier evidence changed after the response was submitted. The refreshed checks require reviewer confirmation."]
                row.data = case.model_dump_json()
                add_event(db, lifecycle.id, user.id, user.role, "evidence_refreshed", "Supplier evidence changed and was revalidated. A second reviewer confirmation is required.")
                db.commit()
                raise HTTPException(409, "Supplier evidence changed. Procura refreshed the checks; review them before approving again.")
        case.status = {"approve": "approved", "reject": "rejected", "request_clarification": "clarification_requested"}[body.action]
        case.reviewer_action, case.reviewer_note, case.reviewed_at = body.action, f"{body.note} — {user.display_name}", datetime.now(UTC)
        if supplier_response and lifecycle:
            supplier_response.status = case.status
            lifecycle.status = case.status
            lifecycle.updated_at = datetime.now(UTC)
            action_message = {
                "approve": "Staff approved the supplier response after revalidating current evidence.",
                "reject": "Staff rejected the supplier response.",
                "request_clarification": "Staff requested clarification on the supplier response.",
            }[body.action]
            add_event(db, lifecycle.id, user.id, user.role, f"review_{body.action}", action_message)
            add_notification(db, lifecycle.buyer_id, lifecycle.id, "Request review updated", action_message)
            add_notification(db, supplier_response.user_id, lifecycle.id, "Response review updated", action_message)
        keys.append(body.idempotency_key); row.action_keys = json.dumps(keys); row.data = case.model_dump_json(); db.commit()
        return case


@app.get("/api/traces/{trace_id}", response_model=TraceSummary)
def trace(trace_id: str, user: AuthUser = Depends(current_user)):
    with SessionLocal() as db:
        row = db.get(ExecutionRow, trace_id)
        if not row: raise HTTPException(404, "Trace not found")
        require_owner("conversation", row.conversation_id, user)
        return TraceSummary.model_validate_json(row.trace_data)


@app.get("/api/executions/{trace_id}", response_model=AgentResponse)
def execution(trace_id: str, user: AuthUser = Depends(current_user)):
    """Return the persisted decision result for an owner or operations administrator."""
    with SessionLocal() as db:
        row = db.get(ExecutionRow, trace_id)
        if not row:
            raise HTTPException(404, "Decision not found")
        require_owner("conversation", row.conversation_id, user)
        return AgentResponse.model_validate_json(row.response)


@app.get("/api/operations/summary", response_model=OperationsSummary)
def operations(_: AuthUser = Depends(admin_user)):
    with SessionLocal() as db:
        all_rows = db.scalars(select(ExecutionRow).order_by(ExecutionRow.created_at.desc())).all()
        rows = [row for row in all_rows if not is_scope_rejection(row)]
        traces = [execution_decision(row) for row in rows[:8]]
        latencies = sorted(r.latency_ms for r in rows)
        p50 = statistics.median(latencies) if len(latencies) >= 2 else None
        p95 = latencies[max(0, round(.95 * len(latencies)) - 1)] if len(latencies) >= 5 else None
        all_traces = [TraceSummary.model_validate_json(r.trace_data) for r in rows]
        measured_tokens = [
            (trace.token_input or 0) + (trace.token_output or 0)
            for trace in all_traces
            if trace.token_input is not None or trace.token_output is not None
        ]
        measured_costs = [trace.estimated_cost_usd for trace in all_traces if trace.estimated_cost_usd is not None]
        eval_path = Path(__file__).parents[1] / "evals" / "results" / "latest.json"
        eval_rate = json.loads(eval_path.read_text()).get("pass_rate") if eval_path.exists() else None
        intake_rows = [ProcurementIntake.model_validate_json(item.data) for item in db.scalars(select(ProcurementIntakeRow)).all()]
        intake_times = [item.time_to_valid_submission_ms for item in intake_rows if item.time_to_valid_submission_ms is not None]
        return OperationsSummary(request_count=len(rows), autonomous_recommendation_count=sum(r.decision == "recommended" for r in rows), human_review_count=sum(r.decision in ("review_required", "failed_safe") for r in rows), error_count=sum(r.decision == "failed_safe" for r in rows), p50_latency_ms=p50, p95_latency_ms=p95, token_usage=sum(measured_tokens) if measured_tokens else None, estimated_cost_usd=round(sum(measured_costs), 6) if measured_costs else None, evaluation_pass_rate=eval_rate, langfuse_status="Configured" if observability.langfuse_enabled else "Langfuse not configured", sentry_status="Configured" if observability.sentry_enabled else "Sentry not configured", recent_traces=traces, intake_count=len(intake_rows), intake_ready_count=sum(item.status == "ready" for item in intake_rows), intake_submitted_count=sum(item.status == "submitted" for item in intake_rows), median_time_to_valid_submission_ms=statistics.median(intake_times) if intake_times else None)


@app.get("/api/admin/overview", response_model=AdminOverview)
def admin_overview(_: AuthUser = Depends(admin_user)):
    """Return operational inventory counts without credentials or session data."""
    with SessionLocal() as db:
        users = list(db.scalars(select(UserRow)).all())
        quotes = list(db.scalars(select(QuoteRow)).all())
        reviews = [HumanReviewCase.model_validate_json(row.data) for row in db.scalars(select(ReviewRow)).all()]
        roles = {role: sum(user.role == role for user in users) for role in ("buyer", "supplier", "reviewer", "admin")}
        variants = {(quote.medicine_name, quote.strength, quote.dosage_form, quote.pack_size) for quote in quotes}
        medicines = {quote.medicine_name for quote in quotes}
        return AdminOverview(
            total_users=len(users),
            active_users=sum(user.is_active for user in users),
            users_by_role=roles,
            supplier_count=db.scalar(select(func.count()).select_from(SupplierRow)) or 0,
            medicine_count=len(medicines),
            medicine_variant_count=len(variants),
            quotation_count=len(quotes),
            open_review_count=sum(review.status == "open" for review in reviews),
            pending_supplier_submission_count=db.scalar(select(func.count()).select_from(SupplierSubmissionRow).where(SupplierSubmissionRow.status == "pending")) or 0,
        )


@app.get("/api/admin/users", response_model=AdminUserPage)
def admin_users(
    q: str = Query(default="", max_length=120),
    role: str | None = Query(default=None, pattern="^(buyer|supplier|reviewer|admin)$"),
    status: str | None = Query(default=None, pattern="^(active|inactive)$"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=50),
    _: AuthUser = Depends(admin_user),
):
    normalized = " ".join(q.lower().split())
    filters = []
    if normalized:
        filters.append(or_(
            func.lower(UserRow.email).contains(normalized, autoescape=True),
            func.lower(UserRow.display_name).contains(normalized, autoescape=True),
            func.lower(UserRow.organization).contains(normalized, autoescape=True),
        ))
    if role:
        filters.append(UserRow.role == role)
    if status:
        filters.append(UserRow.is_active.is_(status == "active"))
    query = select(UserRow).where(*filters)
    count_query = select(func.count()).select_from(UserRow).where(*filters)
    with SessionLocal() as db:
        total = db.scalar(count_query) or 0
        rows = list(db.scalars(query.order_by(UserRow.created_at.desc()).offset((page - 1) * limit).limit(limit)).all())
    return AdminUserPage(
        items=[AdminUserSummary(**public_user(row).model_dump(), is_active=row.is_active) for row in rows],
        total=total,
        page=page,
        limit=limit,
    )


@app.post("/api/dev/simulate-tool-timeout")
async def simulate_timeout(user: AuthUser = Depends(admin_user)):
    if settings.app_env == "production": raise HTTPException(404, "Not found")
    conversation = service.create_conversation()
    with SessionLocal() as db:
        db.add(ResourceOwnerRow(id=str(uuid4()), resource_type="conversation", resource_id=conversation.id, user_id=user.id)); db.commit()
    return await service.execute(conversation.id, "Simulate a tool timeout", f"dev-{conversation.id}", True)
