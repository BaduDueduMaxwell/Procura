import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from app.domain.models import (
    HumanReviewCase,
    LifecycleEvent,
    Notification,
    ProcurementLifecycle,
    ProcurementRequest,
    QuoteLine,
    Supplier,
    SupplierQuote,
    SupplierRequestAssignment,
    SupplierRequestResponse,
    SupplierRequestResponseRequest,
)
from app.models.database import (
    LifecycleEventRow,
    NotificationRow,
    ProcurementLifecycleRow,
    RequestSupplierRow,
    ResourceOwnerRow,
    ReviewRow,
    SupplierResponseRow,
    UserRow,
)
from app.services.seed import synthetic_suppliers
from app.services.tools import compare_quote_prices, evaluate_quote, rank_eligible_quotes, search_synthetic_suppliers
from sqlalchemy import select


def utcnow() -> datetime:
    return datetime.now(UTC)


def supplier_response(row: SupplierResponseRow) -> SupplierRequestResponse:
    payload = json.loads(row.response_json)
    return SupplierRequestResponse(
        id=row.id,
        request_id=row.request_id,
        supplier_id=row.supplier_id,
        status=row.status,
        review_id=row.review_id,
        created_at=row.created_at,
        **payload,
    )


def lifecycle_event(row: LifecycleEventRow) -> LifecycleEvent:
    return LifecycleEvent(id=row.id, event_type=row.event_type, message=row.message, actor_role=row.actor_role, created_at=row.created_at)


def notification(row: NotificationRow) -> Notification:
    return Notification(id=row.id, request_id=row.request_id, title=row.title, message=row.message, is_read=row.is_read, created_at=row.created_at)


def procurement_lifecycle(db, row: ProcurementLifecycleRow) -> ProcurementLifecycle:
    invitations = list(db.scalars(select(RequestSupplierRow).where(RequestSupplierRow.request_id == row.id)).all())
    responses = list(db.scalars(select(SupplierResponseRow).where(SupplierResponseRow.request_id == row.id).order_by(SupplierResponseRow.created_at.desc())).all())
    events = list(db.scalars(select(LifecycleEventRow).where(LifecycleEventRow.request_id == row.id).order_by(LifecycleEventRow.created_at.asc())).all())
    return ProcurementLifecycle(
        id=row.id,
        trace_id=row.trace_id,
        conversation_id=row.conversation_id,
        buyer_id=row.buyer_id,
        request=ProcurementRequest.model_validate_json(row.request_json),
        status=row.status,
        invited_supplier_count=len(invitations),
        responses=[supplier_response(item) for item in responses],
        events=[lifecycle_event(item) for item in events],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def add_event(db, request_id: str, actor_user_id: str | None, actor_role: str, event_type: str, message: str) -> None:
    db.add(LifecycleEventRow(id=str(uuid4()), request_id=request_id, actor_user_id=actor_user_id, actor_role=actor_role, event_type=event_type, message=message, data_json="{}"))


def add_notification(db, user_id: str, request_id: str | None, title: str, message: str) -> None:
    db.add(NotificationRow(id=str(uuid4()), user_id=user_id, request_id=request_id, title=title, message=message, is_read=False))


def supplier_user_ids(db, supplier_ids: set[str]) -> list[str]:
    if not supplier_ids:
        return []
    return list(db.scalars(select(ResourceOwnerRow.user_id).where(ResourceOwnerRow.resource_type == "supplier_profile", ResourceOwnerRow.resource_id.in_(supplier_ids))).all())


def staff_user_ids(db) -> list[str]:
    return list(db.scalars(select(UserRow.id).where(UserRow.role.in_(["reviewer", "admin"]), UserRow.is_active.is_(True))).all())


def current_supplier(supplier_id: str) -> Supplier | None:
    return next((supplier for supplier in synthetic_suppliers() if supplier.id == supplier_id), None)


def evidence_fingerprint(request: ProcurementRequest, supplier: Supplier, payload: dict) -> str:
    evidence = {
        "request": request.model_dump(mode="json"),
        "supplier": {
            "id": supplier.id,
            "authorization": supplier.authorization.model_dump(mode="json"),
            "capability": supplier.capability.model_dump(mode="json"),
            "reliability_score": supplier.reliability_score,
        },
        "response": payload,
        "policy_version": "procura-policy-v1",
    }
    return hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def quote_from_response(request: ProcurementRequest, response: SupplierResponseRow) -> SupplierQuote:
    payload = json.loads(response.response_json)
    medicine = request.medicine
    return SupplierQuote(
        id=response.id,
        supplier_id=response.supplier_id,
        currency=payload["currency"],
        lead_time_days=payload["lead_time_days"],
        line=QuoteLine(
            medicine_name=medicine.medicine_name or "",
            strength=medicine.strength or "",
            dosage_form=medicine.dosage_form or "",
            pack_size=medicine.pack_size or 0,
            quantity_packs=payload["available_quantity_packs"],
            unit_price=payload["unit_price"],
        ),
    )


def evaluate_response_set(db, lifecycle: ProcurementLifecycleRow, target: SupplierResponseRow):
    request = ProcurementRequest.model_validate_json(lifecycle.request_json)
    rows = list(db.scalars(select(SupplierResponseRow).where(SupplierResponseRow.request_id == lifecycle.id)).all())
    supplier_map = {supplier.id: supplier for supplier in synthetic_suppliers()}
    matches = [(supplier_map[row.supplier_id], quote_from_response(request, row)) for row in rows if row.supplier_id in supplier_map]
    prices = compare_quote_prices(request, matches)
    evaluated = [(supplier, quote, evaluate_quote(request, supplier, quote, prices[quote.id])) for supplier, quote in matches]
    scores = rank_eligible_quotes(request, evaluated)
    target_score = next((score for score in scores if score.quote_id == target.id), None)
    return request, scores, target_score


def publish_execution(db, execution, buyer_id: str, idempotency_key: str) -> ProcurementLifecycle:
    existing = db.scalar(select(ProcurementLifecycleRow).where(ProcurementLifecycleRow.trace_id == execution.id))
    if existing:
        if existing.buyer_id != buyer_id:
            raise PermissionError("request owner mismatch")
        return procurement_lifecycle(db, existing)
    key_owner = db.scalar(select(ProcurementLifecycleRow).where(ProcurementLifecycleRow.publish_idempotency_key == idempotency_key))
    if key_owner:
        raise ValueError("Idempotency key is already in use for another procurement request")
    response = json.loads(execution.response)
    request = ProcurementRequest.model_validate(response["request"])
    if request.missing_fields():
        raise ValueError("Complete the required medicine, quantity, destination, delivery, and currency fields before publishing")
    if response["decision"]["status"] in {"clarification", "failed_safe"}:
        raise ValueError("This request is not ready for supplier responses")
    matches = search_synthetic_suppliers(request, synthetic_suppliers())
    matched_supplier_ids = {supplier.id for supplier, _ in matches}
    linked_supplier_ids = set(
        db.scalars(
            select(ResourceOwnerRow.resource_id).where(
                ResourceOwnerRow.resource_type == "supplier_profile",
                ResourceOwnerRow.resource_id.in_(matched_supplier_ids),
            )
        ).all()
    ) if matched_supplier_ids else set()
    supplier_ids = matched_supplier_ids & linked_supplier_ids
    if not supplier_ids:
        raise ValueError("No matching supplier portal is currently available for this request")
    row = ProcurementLifecycleRow(
        id=str(uuid4()), trace_id=execution.id, conversation_id=execution.conversation_id, buyer_id=buyer_id,
        request_json=request.model_dump_json(), status="open_for_responses", publish_idempotency_key=idempotency_key,
    )
    db.add(row); db.flush()
    for supplier_id in sorted(supplier_ids):
        db.add(RequestSupplierRow(id=str(uuid4()), request_id=row.id, supplier_id=supplier_id, status="invited"))
    medicine = request.medicine.medicine_name or "Procurement request"
    add_event(db, row.id, buyer_id, "buyer", "request_published", f"{medicine.title()} opened for responses from {len(supplier_ids)} matching supplier(s).")
    for user_id in supplier_user_ids(db, supplier_ids):
        add_notification(db, user_id, row.id, "New buyer request", f"A {medicine} request matches your supplier profile. Review it and submit an offer.")
    db.commit(); db.refresh(row)
    return procurement_lifecycle(db, row)


def supplier_assignments(db, supplier_id: str) -> list[SupplierRequestAssignment]:
    invitations = list(db.scalars(select(RequestSupplierRow).where(RequestSupplierRow.supplier_id == supplier_id).order_by(RequestSupplierRow.created_at.desc())).all())
    result = []
    for invitation in invitations:
        lifecycle = db.get(ProcurementLifecycleRow, invitation.request_id)
        if not lifecycle:
            continue
        response = db.scalar(select(SupplierResponseRow).where(SupplierResponseRow.request_id == lifecycle.id, SupplierResponseRow.supplier_id == supplier_id).order_by(SupplierResponseRow.created_at.desc()))
        result.append(SupplierRequestAssignment(request=procurement_lifecycle(db, lifecycle), invitation_status=invitation.status, supplier_response=supplier_response(response) if response else None))
    return result


def submit_supplier_response(db, lifecycle: ProcurementLifecycleRow, supplier: Supplier, user_id: str, body: SupplierRequestResponseRequest) -> SupplierRequestResponse:
    existing = db.scalar(select(SupplierResponseRow).where(SupplierResponseRow.idempotency_key == body.idempotency_key))
    if existing:
        if existing.user_id != user_id:
            raise PermissionError("idempotency key is already in use")
        return supplier_response(existing)
    invitation = db.scalar(select(RequestSupplierRow).where(RequestSupplierRow.request_id == lifecycle.id, RequestSupplierRow.supplier_id == supplier.id))
    if not invitation:
        raise PermissionError("supplier is not invited to this request")
    if invitation.status == "responded":
        raise ValueError("A response has already been submitted for this buyer request")
    payload = body.model_dump(mode="json", exclude={"idempotency_key"})
    request = ProcurementRequest.model_validate_json(lifecycle.request_json)
    row = SupplierResponseRow(
        id=str(uuid4()), request_id=lifecycle.id, supplier_id=supplier.id, user_id=user_id,
        response_json=json.dumps(payload), evidence_hash=evidence_fingerprint(request, supplier, payload),
        status="submitted", idempotency_key=body.idempotency_key,
    )
    db.add(row); db.flush()
    _, scores, target_score = evaluate_response_set(db, lifecycle, row)
    reasons = list(target_score.reasons if target_score else ["Supplier evidence could not be evaluated"])
    if target_score and target_score.eligible:
        reasons = ["Supplier response requires organizational approval"]
    case = HumanReviewCase(
        id=str(uuid4()), conversation_id=lifecycle.conversation_id, trace_id=lifecycle.trace_id,
        reasons=reasons, request=request, quotes=scores,
        recommendation_supplier_id=supplier.id if target_score and target_score.eligible else None,
    )
    row.review_id = case.id
    db.add(ReviewRow(id=case.id, data=case.model_dump_json()))
    invitation.status = "responded"
    lifecycle.status = "review_pending"
    lifecycle.updated_at = utcnow()
    medicine = request.medicine.medicine_name or "request"
    add_event(db, lifecycle.id, user_id, "supplier", "supplier_response_submitted", f"{supplier.display_name} submitted a response for {medicine}.")
    add_notification(db, lifecycle.buyer_id, lifecycle.id, "Supplier response received", f"{supplier.display_name} submitted an offer. Staff review is now pending.")
    add_notification(db, user_id, lifecycle.id, "Response submitted", "Your offer was recorded and is awaiting staff review.")
    for staff_id in staff_user_ids(db):
        add_notification(db, staff_id, lifecycle.id, "Supplier response needs review", f"Review {supplier.display_name}'s response for {medicine}.")
    db.commit(); db.refresh(row)
    return supplier_response(row)
