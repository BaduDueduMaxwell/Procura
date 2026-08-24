from datetime import UTC, datetime

from app.config import get_settings
from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase): pass


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


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
