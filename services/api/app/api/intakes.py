from typing import cast

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile

from app.config import get_settings
from app.domain.errors import FileValidationError, PersistenceError, VersionConflictError
from app.domain.models import (
    AuthUser,
    IntakeActionRequest,
    IntakeDashboardSummary,
    IntakeDuplicateDecisionRequest,
    IntakeLinePatch,
    IntakeSuggestionDecisionRequest,
    IntakeVariantDecisionRequest,
    ProcurementIntake,
    TextIntakeRequest,
)
from app.intake.service import BuyerIntakeService
from app.observability.adapters import Observability
from app.services.auth import current_user

router = APIRouter(prefix="/api/intakes", tags=["buyer intake"])
settings = get_settings()


def buyer_or_admin(user: AuthUser = Depends(current_user)) -> AuthUser:
    if user.role not in {"buyer", "admin"}:
        raise HTTPException(403, "Buyer workspace required")
    return user


def service(request: Request) -> BuyerIntakeService:
    return cast(BuyerIntakeService, request.app.state.intake_service)


def observability(request: Request) -> Observability:
    return cast(Observability, request.app.state.observability)


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


@router.post("/text", response_model=ProcurementIntake, status_code=201)
def create_text_intake(
    body: TextIntakeRequest,
    request: Request,
    user: AuthUser = Depends(buyer_or_admin),
):
    try:
        return service(request).create_text(user, body.content, body.idempotency_key)
    except Exception as exc:
        observability(request).capture(exc, workflow_stage="text_intake", error_category="intake_failure")
        raise intake_error(exc) from exc


@router.post("/files", response_model=ProcurementIntake, status_code=201)
async def create_file_intake(
    request: Request,
    file: UploadFile = File(...),
    idempotency_key: str = Form(..., min_length=8, max_length=120),
    user: AuthUser = Depends(buyer_or_admin),
):
    content = await file.read(settings.intake_max_file_bytes + 1)
    await file.close()
    try:
        return service(request).create_file(user, file.filename or "upload", content, file.content_type, idempotency_key)
    except Exception as exc:
        observability(request).capture(exc, workflow_stage="file_intake", error_category="intake_failure")
        raise intake_error(exc) from exc


@router.get("", response_model=list[ProcurementIntake])
def list_intakes(request: Request, user: AuthUser = Depends(buyer_or_admin)):
    try:
        return service(request).list_intakes(user)
    except Exception as exc:
        raise intake_error(exc) from exc


@router.get("/summary", response_model=IntakeDashboardSummary)
def intake_dashboard(request: Request, user: AuthUser = Depends(buyer_or_admin)):
    try:
        return service(request).dashboard(user)
    except Exception as exc:
        raise intake_error(exc) from exc


@router.get("/template.csv")
def intake_template(_: AuthUser = Depends(buyer_or_admin)):
    content = "medicine,strength,dosage form,quantity,units,pack size,destination,lead time,currency\n"
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="procura-intake-template.csv"'},
    )


@router.get("/{intake_id}", response_model=ProcurementIntake)
def get_intake(intake_id: str, request: Request, user: AuthUser = Depends(buyer_or_admin)):
    try:
        return service(request).get(user, intake_id)
    except Exception as exc:
        raise intake_error(exc) from exc


@router.patch("/{intake_id}/lines/{line_id}", response_model=ProcurementIntake)
def patch_intake_line(
    intake_id: str,
    line_id: str,
    body: IntakeLinePatch,
    request: Request,
    user: AuthUser = Depends(buyer_or_admin),
):
    try:
        return service(request).patch_line(user, intake_id, line_id, body)
    except Exception as exc:
        raise intake_error(exc) from exc


@router.post("/{intake_id}/lines/{line_id}/suggestion", response_model=ProcurementIntake)
def decide_intake_suggestion(
    intake_id: str,
    line_id: str,
    body: IntakeSuggestionDecisionRequest,
    request: Request,
    user: AuthUser = Depends(buyer_or_admin),
):
    try:
        return service(request).decide_suggestion(
            user, intake_id, line_id, body.action, body.version, body.idempotency_key
        )
    except Exception as exc:
        raise intake_error(exc) from exc


@router.post("/{intake_id}/lines/{line_id}/variant", response_model=ProcurementIntake)
def select_intake_variant(
    intake_id: str,
    line_id: str,
    body: IntakeVariantDecisionRequest,
    request: Request,
    user: AuthUser = Depends(buyer_or_admin),
):
    try:
        return service(request).select_variant(
            user, intake_id, line_id, body.source_record_id, body.version, body.idempotency_key
        )
    except Exception as exc:
        raise intake_error(exc) from exc


@router.post("/{intake_id}/lines/{line_id}/duplicate", response_model=ProcurementIntake)
def resolve_intake_duplicate(
    intake_id: str,
    line_id: str,
    body: IntakeDuplicateDecisionRequest,
    request: Request,
    user: AuthUser = Depends(buyer_or_admin),
):
    try:
        return service(request).resolve_duplicate(
            user, intake_id, line_id, body.action, body.version, body.idempotency_key
        )
    except Exception as exc:
        raise intake_error(exc) from exc


@router.post("/{intake_id}/revalidate", response_model=ProcurementIntake)
def revalidate_intake(
    intake_id: str,
    body: IntakeActionRequest,
    request: Request,
    user: AuthUser = Depends(buyer_or_admin),
):
    try:
        return service(request).revalidate(user, intake_id, body.version, body.idempotency_key)
    except Exception as exc:
        raise intake_error(exc) from exc


@router.post("/{intake_id}/submit", response_model=ProcurementIntake)
def submit_intake(
    intake_id: str,
    body: IntakeActionRequest,
    request: Request,
    user: AuthUser = Depends(buyer_or_admin),
):
    try:
        return service(request).submit(user, intake_id, body.version, body.idempotency_key)
    except Exception as exc:
        raise intake_error(exc) from exc
