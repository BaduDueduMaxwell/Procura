from datetime import UTC, datetime

from app.config import get_settings
from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase): pass


class AppStateRow(Base):
    __tablename__ = "app_state"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))


class ConversationRow(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    data: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class ReviewRow(Base):
    __tablename__ = "reviews"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    data: Mapped[str] = mapped_column(Text)
    action_keys: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class ExecutionRow(Base):
    __tablename__ = "executions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String, index=True)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True)
    response: Mapped[str] = mapped_column(Text)
    decision: Mapped[str] = mapped_column(String)
    latency_ms: Mapped[float] = mapped_column(Float)
    trace_data: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class UserRow(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80))
    organization: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="buyer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class SessionRow(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class ResourceOwnerRow(Base):
    __tablename__ = "resource_owners"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(24), index=True)
    resource_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True)


class SupplierRow(Base):
    __tablename__ = "suppliers"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120))
    authorization_status: Mapped[str] = mapped_column(String(20))
    authorization_expiry: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    destinations_json: Mapped[str] = mapped_column(Text)
    cold_chain: Mapped[bool] = mapped_column(Boolean)
    reliability_score: Mapped[float] = mapped_column(Float)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=True)


class SupplierSubmissionRow(Base):
    __tablename__ = "supplier_submissions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    supplier_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String(24))
    payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    decision_keys: Mapped[str] = mapped_column(Text, default="[]")
    reviewer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class QuoteRow(Base):
    __tablename__ = "supplier_quotes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    supplier_id: Mapped[str] = mapped_column(String, index=True)
    currency: Mapped[str] = mapped_column(String(3))
    lead_time_days: Mapped[int] = mapped_column(Integer)
    medicine_name: Mapped[str] = mapped_column(String(120))
    strength: Mapped[str] = mapped_column(String(40))
    dosage_form: Mapped[str] = mapped_column(String(40))
    pack_size: Mapped[int] = mapped_column(Integer)
    quantity_packs: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[float] = mapped_column(Float)


class ProcurementLifecycleRow(Base):
    __tablename__ = "procurement_lifecycles"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    trace_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    conversation_id: Mapped[str] = mapped_column(String, index=True)
    buyer_id: Mapped[str] = mapped_column(String, index=True)
    request_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="open_for_responses", index=True)
    publish_idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class RequestSupplierRow(Base):
    __tablename__ = "request_suppliers"
    __table_args__ = (UniqueConstraint("request_id", "supplier_id", name="uq_request_supplier"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(String, index=True)
    supplier_id: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String(24), default="invited")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class SupplierResponseRow(Base):
    __tablename__ = "supplier_responses"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(String, index=True)
    supplier_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    response_json: Mapped[str] = mapped_column(Text)
    evidence_hash: Mapped[str] = mapped_column(String(64))
    review_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="submitted", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class LifecycleEventRow(Base):
    __tablename__ = "lifecycle_events"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(String, index=True)
    actor_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    actor_role: Mapped[str] = mapped_column(String(20))
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    message: Mapped[str] = mapped_column(String(400))
    data_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class NotificationRow(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    request_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(120))
    message: Mapped[str] = mapped_column(String(400))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


def sqlalchemy_database_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


settings = get_settings()
database_url = sqlalchemy_database_url(settings.database_url)
connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine = create_engine(database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
