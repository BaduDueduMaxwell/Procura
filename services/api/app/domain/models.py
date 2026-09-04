from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, EmailStr, Field, field_validator


class ReviewReason(StrEnum):
    MISSING_INFORMATION = "missing_information"
    AMBIGUOUS_REQUEST = "ambiguous_request"
    MISSING_AUTHORIZATION = "missing_authorization"
    EXPIRED_AUTHORIZATION = "expired_authorization"
    PACK_SIZE_MISMATCH = "pack_size_mismatch"
    COLD_CHAIN_MISMATCH = "cold_chain_mismatch"
    UNSUPPORTED_DESTINATION = "unsupported_destination"
    CURRENCY_MISMATCH = "currency_mismatch"
    PRICE_ANOMALY = "price_anomaly"
    NO_ELIGIBLE_QUOTE = "no_eligible_quote"
    MODEL_FAILURE = "invalid_model_output"
    TOOL_FAILURE = "tool_failure"
    CONFLICTING_DATA = "conflicting_supplier_data"
    LOW_CONFIDENCE = "low_confidence"


class MedicineRequirement(BaseModel):
    medicine_name: str | None = None
    strength: str | None = None
    dosage_form: str | None = None
    quantity: int | None = Field(default=None, gt=0)
    pack_size: int | None = Field(default=None, gt=0)
    unit: str = "packs"
    cold_chain_required: bool = False


class ProcurementRequest(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    medicine: MedicineRequirement
    destination: str | None = None
    required_delivery_date: date | None = None
    max_lead_time_days: int | None = Field(default=None, gt=0)
    currency: str | None = None
    buyer_notes: str | None = None
    synthetic: Literal[True] = True

    def missing_fields(self) -> list[str]:
        values = {
            "medicine name": self.medicine.medicine_name,
            "strength": self.medicine.strength,
            "dosage form": self.medicine.dosage_form,
            "quantity": self.medicine.quantity,
            "pack size": self.medicine.pack_size,
            "destination": self.destination,
            "delivery requirement": self.max_lead_time_days or self.required_delivery_date,
            "currency": self.currency,
        }
        return [key for key, value in values.items() if not value]


class SupplierAuthorization(BaseModel):
    status: Literal["authorized", "missing", "expired"]
    expiry_date: date | None = None


class SupplierCapability(BaseModel):
    destinations: list[str]
    cold_chain: bool


class QuoteLine(BaseModel):
    medicine_name: str
    strength: str
    dosage_form: str
    pack_size: int
    quantity_packs: int = Field(gt=0, description="Maximum packs currently available from the supplier")
    unit_price: float = Field(gt=0)


class SupplierQuote(BaseModel):
    id: str
    supplier_id: str
    currency: str
    lead_time_days: int
    line: QuoteLine

    @property
    def total_price(self) -> float:
        return round(self.line.quantity_packs * self.line.unit_price, 2)


class Supplier(BaseModel):
    id: str
    display_name: str
    authorization: SupplierAuthorization
    capability: SupplierCapability
    reliability_score: float = Field(ge=0, le=1)
    quotes: list[SupplierQuote]
    synthetic: Literal[True] = True


class ToolResult(BaseModel):
    tool: str
    passed: bool
    detail: str


class EligibilityResult(BaseModel):
    supplier_id: str
    quote_id: str
    eligible: bool
    reasons: list[str]
    tool_results: list[ToolResult]


class QuoteScore(BaseModel):
    supplier_id: str
    supplier_display_name: str | None = None
    quote_id: str
    total_price: float
    unit_price: float = 0
    currency: str
    requested_quantity_packs: int = 0
    available_quantity_packs: int = 0
    offered_pack_size: int = 0
    lead_time_days: int
    reliability: float
    score: float | None = None
    eligible: bool
    reasons: list[str] = []


class AgentDecision(BaseModel):
    status: Literal["clarification", "recommended", "review_required", "failed_safe"]
    recommendation_supplier_id: str | None = None
    summary: str
    human_review_required: bool = False
    escalation_reasons: list[str] = []
    policy_version: str = "procura-policy-v1"
    trace_id: str
    no_transaction_completed: Literal[True] = True


class HumanReviewCase(BaseModel):
    id: str
    conversation_id: str
    trace_id: str
    status: Literal["open", "approved", "rejected", "clarification_requested"] = "open"
    reasons: list[str]
    request: ProcurementRequest
    quotes: list[QuoteScore]
    recommendation_supplier_id: str | None = None
    policy_version: str = "procura-policy-v1"
    reviewer_action: str | None = None
    reviewer_note: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Message(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Conversation(BaseModel):
    id: str
    messages: list[Message] = []
    draft: ProcurementRequest | None = None
    pending_medicine_suggestion: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TraceSummary(BaseModel):
    trace_id: str
    conversation_id: str
    latency_ms: float
    model: str
    provider: str
    decision: str
    review_required: bool
    policy_version: str
    prompt_version: str = "procura-agent-v1"
    token_input: int | None = None
    token_output: int | None = None
    estimated_cost_usd: float | None = None
    exported_to_langfuse: bool = False
    tool_sequence: list[str] = []
    scores: dict[str, float] = {}
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DashboardDecision(TraceSummary):
    medicine_name: str | None = None
    strength: str | None = None
    dosage_form: str | None = None


class AgentResponse(BaseModel):
    conversation_id: str
    message: Message
    request: ProcurementRequest
    quotes: list[QuoteScore] = []
    decision: AgentDecision
    progress_events: list[str]


class ReviewDecisionRequest(BaseModel):
    action: Literal["approve", "reject", "request_clarification"]
    note: str = Field(min_length=2, max_length=1000)
    idempotency_key: str = Field(min_length=4, max_length=100)


class MessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    idempotency_key: str = Field(min_length=4, max_length=100)
    simulate_tool_timeout: bool = False


class OperationsSummary(BaseModel):
    request_count: int
    autonomous_recommendation_count: int
    human_review_count: int
    error_count: int
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    token_usage: int | None
    estimated_cost_usd: float | None
    evaluation_pass_rate: float | None
    langfuse_status: str
    sentry_status: str
    recent_traces: list[DashboardDecision]
    intake_count: int = 0
    intake_ready_count: int = 0
    intake_submitted_count: int = 0
    median_time_to_valid_submission_ms: float | None = None


class AuthUser(BaseModel):
    id: str
    email: EmailStr
    display_name: str
    organization: str
    role: Literal["buyer", "supplier", "reviewer", "admin"]
    created_at: datetime


class AdminUserSummary(AuthUser):
    is_active: bool


class AdminUserPage(BaseModel):
    items: list[AdminUserSummary]
    total: int
    page: int
    limit: int


class AdminOverview(BaseModel):
    total_users: int
    active_users: int
    users_by_role: dict[str, int]
    supplier_count: int
    medicine_count: int
    medicine_variant_count: int
    quotation_count: int
    open_review_count: int
    pending_supplier_submission_count: int


class SignupRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=2, max_length=80)
    organization: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=12, max_length=128)
    account_type: Literal["buyer", "supplier"] = "buyer"

    @field_validator("display_name", "organization")
    @classmethod
    def clean_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if any(ord(char) < 32 for char in value):
            raise ValueError("control characters are not allowed")
        return value

    @field_validator("password")
    @classmethod
    def strong_password(cls, value: str) -> str:
        checks = (any(c.islower() for c in value), any(c.isupper() for c in value), any(c.isdigit() for c in value), any(not c.isalnum() for c in value))
        if not all(checks):
            raise ValueError("password must include upper, lower, number, and symbol")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class CustomerDashboardSummary(BaseModel):
    conversation_count: int
    execution_count: int
    recommendation_count: int
    review_count: int
    recent_decisions: list[DashboardDecision]


class MedicineCatalogItem(BaseModel):
    medicine_name: str
    strength: str
    dosage_form: str
    pack_size: int
    quotation_count: int
    authorized_supplier_count: int
    available_quantity_packs: int
    currencies: list[str]
    destinations: list[str]
    cold_chain_available: bool
    minimum_lead_time_days: int
    unit_price_from: float
    unit_price_to: float
    request_starter: str


class SupplierDashboardSummary(BaseModel):
    supplier: Supplier
    quote_count: int
    eligible_destination_count: int
    compliance_state: str
    submissions: list["SupplierSubmission"] = []


class SupplierProfileSubmissionRequest(BaseModel):
    display_name: str = Field(min_length=2, max_length=120)
    destinations: list[str] = Field(min_length=1, max_length=12)
    cold_chain: bool
    authorization_expiry: date
    idempotency_key: str = Field(min_length=4, max_length=100)

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("destinations")
    @classmethod
    def clean_destinations(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(" ".join(value.split()).title() for value in values if value.strip()))
        if not cleaned:
            raise ValueError("at least one destination is required")
        return cleaned


class SupplierQuoteSubmissionRequest(BaseModel):
    quote_id: str | None = Field(default=None, max_length=100)
    action: Literal["upsert", "withdraw"] = "upsert"
    medicine_name: str = Field(min_length=2, max_length=120)
    strength: str = Field(min_length=1, max_length=40)
    dosage_form: str = Field(min_length=2, max_length=40)
    pack_size: int = Field(gt=0, le=10000)
    available_quantity_packs: int = Field(gt=0, le=10000000)
    unit_price: float = Field(gt=0, le=10000000)
    currency: str = Field(min_length=3, max_length=3)
    lead_time_days: int = Field(gt=0, le=365)
    idempotency_key: str = Field(min_length=4, max_length=100)

    @field_validator("medicine_name", "strength", "dosage_form")
    @classmethod
    def clean_quote_text(cls, value: str) -> str:
        return " ".join(value.split()).lower()

    @field_validator("currency")
    @classmethod
    def clean_currency(cls, value: str) -> str:
        return value.upper()


class SupplierQuoteDraftRequest(BaseModel):
    content: str = Field(min_length=5, max_length=2000)


class SupplierQuoteDraft(BaseModel):
    medicine_name: str | None = None
    strength: str | None = None
    dosage_form: str | None = None
    pack_size: int | None = None
    available_quantity_packs: int | None = None
    unit_price: float | None = None
    currency: str | None = None
    lead_time_days: int | None = None
    missing_fields: list[str]
    ready_to_submit: bool
    summary: str
    provider: str
    prompt_version: Literal["procura-supplier-quote-v1"] = "procura-supplier-quote-v1"
    trace_id: str
    no_submission_created: Literal[True] = True


class ReviewBrief(BaseModel):
    review_id: str
    trace_id: str
    summary: str
    evidence_points: list[str]
    suggested_action: Literal["approve", "reject", "request_clarification"]
    suggestion_reason: str
    policy_version: str
    provider: str
    prompt_version: Literal["procura-review-brief-v1"] = "procura-review-brief-v1"
    human_decision_required: Literal[True] = True


class SupplierSubmission(BaseModel):
    id: str
    supplier_id: str
    kind: Literal["profile", "quote"]
    payload: dict
    status: Literal["pending", "approved", "rejected"] = "pending"
    reviewer_note: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime


class SupplierSubmissionDecisionRequest(BaseModel):
    action: Literal["approve", "reject"]
    note: str = Field(min_length=2, max_length=1000)
    idempotency_key: str = Field(min_length=4, max_length=100)


class PublishProcurementRequest(BaseModel):
    idempotency_key: str = Field(min_length=4, max_length=100)


class SupplierRequestResponseRequest(BaseModel):
    available_quantity_packs: int = Field(gt=0, le=10000000)
    unit_price: float = Field(gt=0, le=10000000)
    currency: str = Field(min_length=3, max_length=3)
    lead_time_days: int = Field(gt=0, le=365)
    idempotency_key: str = Field(min_length=4, max_length=100)

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()


class LifecycleEvent(BaseModel):
    id: str
    event_type: str
    message: str
    actor_role: str
    created_at: datetime


class Notification(BaseModel):
    id: str
    request_id: str | None = None
    title: str
    message: str
    is_read: bool
    created_at: datetime


class NotificationReadRequest(BaseModel):
    idempotency_key: str = Field(min_length=4, max_length=100)


class SupplierRequestResponse(BaseModel):
    id: str
    request_id: str
    supplier_id: str
    available_quantity_packs: int
    unit_price: float
    currency: str
    lead_time_days: int
    status: Literal["submitted", "approved", "rejected", "clarification_requested", "evidence_changed"]
    review_id: str | None = None
    created_at: datetime


class ProcurementLifecycle(BaseModel):
    id: str
    trace_id: str
    conversation_id: str
    buyer_id: str
    request: ProcurementRequest
    status: Literal["open_for_responses", "responses_received", "review_pending", "approved", "rejected", "clarification_requested"]
    invited_supplier_count: int
    responses: list[SupplierRequestResponse] = []
    events: list[LifecycleEvent] = []
    created_at: datetime
    updated_at: datetime


class SupplierRequestAssignment(BaseModel):
    request: ProcurementLifecycle
    invitation_status: Literal["invited", "responded"]
    supplier_response: SupplierRequestResponse | None = None


IntakeStatus = Literal[
    "draft",
    "processing",
    "needs_correction",
    "suggestion_available",
    "ready",
    "submitted",
    "critical_review_required",
    "failed_safe",
]


class IntakeFinding(BaseModel):
    code: str
    severity: Literal["information", "warning", "blocker", "critical"]
    message: str
    field: str | None = None
    row_id: str
    evidence_source: str
    correctable_by_buyer: bool
    suggested_action: str


class CatalogueSuggestion(BaseModel):
    original_value: str
    suggested_value: str
    match_reason: str
    source_record_id: str
    confirmation_required: Literal[True] = True
    status: Literal["pending", "accepted", "rejected"] = "pending"
    actor_id: str | None = None
    decided_at: datetime | None = None


class IntakeLine(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    source_row: int = Field(ge=1)
    sheet_name: str | None = None
    medicine_name: str | None = None
    brand_name: str | None = None
    strength: str | None = None
    dosage_form: str | None = None
    quantity: int | None = Field(default=None, gt=0)
    unit: str | None = None
    pack_size: int | None = Field(default=None, gt=0)
    destination: str | None = None
    max_lead_time_days: int | None = Field(default=None, gt=0)
    currency: str | None = None
    cold_chain_required: bool = False
    original_values: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    normalized_fields: list[str] = Field(default_factory=list)
    buyer_corrected_fields: list[str] = Field(default_factory=list)
    findings: list[IntakeFinding] = Field(default_factory=list)
    suggestion: CatalogueSuggestion | None = None
    status: Literal["ready", "needs_correction", "suggestion_available", "critical_review_required"] = "needs_correction"


class ProcurementIntake(BaseModel):
    id: str
    buyer_id: str
    organization: str
    source_type: Literal["text", "csv", "xlsx"]
    filename: str | None = None
    status: IntakeStatus = "draft"
    version: int = 1
    lines: list[IntakeLine]
    graph_path: list[str] = Field(default_factory=list)
    trace_id: str
    policy_version: str = "procura-policy-v1"
    provider: str = "local"
    time_to_first_feedback_ms: float | None = None
    time_to_valid_submission_ms: float | None = None
    first_pass_complete: bool = False
    submitted_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TextIntakeRequest(BaseModel):
    content: str = Field(min_length=5, max_length=4000)
    idempotency_key: str = Field(min_length=4, max_length=100)


class IntakeLinePatch(BaseModel):
    medicine_name: str | None = Field(default=None, max_length=120)
    brand_name: str | None = Field(default=None, max_length=120)
    strength: str | None = Field(default=None, max_length=40)
    dosage_form: str | None = Field(default=None, max_length=40)
    quantity: int | None = Field(default=None, gt=0, le=10000000)
    unit: str | None = Field(default=None, max_length=20)
    pack_size: int | None = Field(default=None, gt=0, le=100000)
    destination: str | None = Field(default=None, max_length=120)
    max_lead_time_days: int | None = Field(default=None, gt=0, le=3650)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    cold_chain_required: bool | None = None
    version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=4, max_length=100)


class IntakeSuggestionDecisionRequest(BaseModel):
    action: Literal["accept", "reject"]
    version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=4, max_length=100)


class IntakeActionRequest(BaseModel):
    version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=4, max_length=100)


class IntakeDashboardSummary(BaseModel):
    total: int
    drafts: int
    needs_correction: int
    ready: int
    submitted: int
    median_time_to_valid_submission_ms: float | None
    recent: list[ProcurementIntake]


SupplierDashboardSummary.model_rebuild()
