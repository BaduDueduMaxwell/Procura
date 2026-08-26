import hashlib
import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.config import Settings, get_settings
from app.domain.models import AuthUser
from app.models.database import ResourceOwnerRow, SessionLocal, SessionRow, UserRow
from fastapi import Depends, HTTPException, Request, Response
from pwdlib import PasswordHash
from sqlalchemy import delete, select

password_hash = PasswordHash.recommended()


class AuthRateLimiter:
    def __init__(self, limit: int = 10, window_seconds: int = 900):
        self.limit, self.window_seconds = limit, window_seconds
        self.attempts: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        bucket = self.attempts[key]
        while bucket and bucket[0] < now - self.window_seconds:
            bucket.popleft()
        if len(bucket) >= self.limit:
            raise HTTPException(429, "Too many authentication attempts. Try again later.")
        bucket.append(now)


auth_limiter = AuthRateLimiter()


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def public_user(row: UserRow) -> AuthUser:
    return AuthUser(id=row.id, email=row.email, display_name=row.display_name, organization=row.organization, role=row.role, created_at=row.created_at)


def create_session(user_id: str, response: Response, settings: Settings) -> None:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(days=settings.session_days)
    with SessionLocal() as db:
        db.add(SessionRow(id=str(uuid4()), user_id=user_id, token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=expires))
        db.commit()
    response.set_cookie(settings.session_cookie_name, token, max_age=settings.session_days * 86400, httponly=True, secure=settings.app_env == "production", samesite="lax", path="/")


def clear_session(request: Request, response: Response, settings: Settings) -> None:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        with SessionLocal() as db:
            db.execute(delete(SessionRow).where(SessionRow.token_hash == hashlib.sha256(token.encode()).hexdigest()))
            db.commit()
    response.delete_cookie(settings.session_cookie_name, path="/", samesite="lax")


def current_user(request: Request, settings: Settings = Depends(get_settings)) -> AuthUser:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(401, "Sign in required")
    with SessionLocal() as db:
        session = db.scalar(select(SessionRow).where(SessionRow.token_hash == hashlib.sha256(token.encode()).hexdigest()))
        expires = session.expires_at.replace(tzinfo=UTC) if session and session.expires_at.tzinfo is None else session.expires_at if session else None
        if not session or not expires or expires <= datetime.now(UTC):
            if session:
                db.delete(session); db.commit()
            raise HTTPException(401, "Session expired")
        user = db.get(UserRow, session.user_id)
        if not user or not user.is_active:
            raise HTTPException(401, "Account unavailable")
        return public_user(user)


def staff_user(user: AuthUser = Depends(current_user)) -> AuthUser:
    if user.role not in {"reviewer", "admin"}:
        raise HTTPException(403, "Staff access required")
    return user


def admin_user(user: AuthUser = Depends(current_user)) -> AuthUser:
    if user.role != "admin":
        raise HTTPException(403, "Administrator access required")
    return user


def upsert_bootstrap_user(db, *, email: str | None, password: str | None, display_name: str, role: str) -> UserRow | None:
    if not email or not password:
        return None
    normalized_email = normalize_email(email)
    user = db.scalar(select(UserRow).where(UserRow.email == normalized_email))
    if not user:
        user = UserRow(
            id=str(uuid4()),
            email=normalized_email,
            display_name=display_name,
            organization="Procura",
            password_hash=password_hash.hash(password),
            role=role,
        )
        db.add(user)
    else:
        user.display_name = display_name
        user.organization = "Procura"
        user.password_hash = password_hash.hash(password)
        user.role = role
        user.is_active = True
    return user


def seed_local_accounts(settings: Settings) -> None:
    reviewer_email = settings.bootstrap_reviewer_email if settings.app_env == "production" else "reviewer@procura.example"
    reviewer_password = settings.bootstrap_reviewer_password if settings.app_env == "production" else "Procura-Reviewer-2026!"
    admin_email = settings.bootstrap_admin_email if settings.app_env == "production" else "operations@procura.example"
    admin_password = settings.bootstrap_admin_password if settings.app_env == "production" else "Procura-Admin-2026!"
    supplier_email = settings.bootstrap_supplier_email if settings.app_env == "production" else "supplier@procura.example"
    supplier_password = settings.bootstrap_supplier_password if settings.app_env == "production" else "Procura-Supplier-2026!"
    with SessionLocal() as db:
        upsert_bootstrap_user(db, email=reviewer_email, password=reviewer_password, display_name="Procurement Reviewer", role="reviewer")
        upsert_bootstrap_user(db, email=admin_email, password=admin_password, display_name="Operations Administrator", role="admin")
        normalized_supplier_email = normalize_email(supplier_email) if supplier_email else None
        supplier_user = db.scalar(select(UserRow).where(UserRow.email == normalized_supplier_email)) if normalized_supplier_email else None
        if not supplier_email or not supplier_password:
            db.commit()
            return
        if not supplier_user:
            supplier_user = UserRow(id=str(uuid4()), email=normalized_supplier_email, display_name="Northstar Account", organization="Northstar Health Supply", password_hash=password_hash.hash(supplier_password), role="supplier")
            db.add(supplier_user); db.flush()
        else:
            supplier_user.display_name = "Northstar Account"
            supplier_user.organization = "Northstar Health Supply"
            supplier_user.password_hash = password_hash.hash(supplier_password)
            supplier_user.role = "supplier"
            supplier_user.is_active = True
        existing_link = db.scalar(select(ResourceOwnerRow).where(ResourceOwnerRow.resource_type == "supplier_profile", ResourceOwnerRow.resource_id == "northstar", ResourceOwnerRow.user_id == supplier_user.id))
        if not existing_link:
            db.add(ResourceOwnerRow(id=str(uuid4()), resource_type="supplier_profile", resource_id="northstar", user_id=supplier_user.id))
        db.commit()
