import json
from datetime import UTC, datetime

from sqlalchemy import select

from app.domain.errors import PersistenceError, VersionConflictError
from app.domain.models import ProcurementIntake
from app.models.database import ProcurementIntakeRow, SessionLocal


def _model(row: ProcurementIntakeRow) -> ProcurementIntake:
    return ProcurementIntake.model_validate_json(row.data)


class SqlAlchemyIntakeRepository:
    def create(self, intake: ProcurementIntake, idempotency_key: str) -> ProcurementIntake:
        try:
            with SessionLocal() as db:
                existing = db.scalar(select(ProcurementIntakeRow).where(ProcurementIntakeRow.create_idempotency_key == idempotency_key))
                if existing:
                    if existing.buyer_id != intake.buyer_id:
                        raise VersionConflictError("The idempotency key is already in use")
                    return _model(existing)
                row = ProcurementIntakeRow(
                    id=intake.id,
                    buyer_id=intake.buyer_id,
                    organization=intake.organization,
                    source_type=intake.source_type,
                    filename=intake.filename,
                    status=intake.status,
                    version=intake.version,
                    trace_id=intake.trace_id,
                    create_idempotency_key=idempotency_key,
                    data=intake.model_dump_json(),
                    action_keys="[]",
                    created_at=intake.created_at,
                    updated_at=intake.updated_at,
                )
                db.add(row)
                db.commit()
                return intake
        except VersionConflictError:
            raise
        except Exception as exc:
            raise PersistenceError("The intake could not be saved") from exc

    def get(self, intake_id: str, buyer_id: str, allow_admin: bool = False) -> ProcurementIntake:
        with SessionLocal() as db:
            row = db.get(ProcurementIntakeRow, intake_id)
            if not row or (row.buyer_id != buyer_id and not allow_admin):
                raise LookupError("Procurement intake not found")
            return _model(row)

    def action_result(self, intake_id: str, buyer_id: str, allow_admin: bool, idempotency_key: str) -> ProcurementIntake | None:
        """Return the saved result when a client safely retries the same action."""
        with SessionLocal() as db:
            row = db.get(ProcurementIntakeRow, intake_id)
            if not row or (row.buyer_id != buyer_id and not allow_admin):
                raise LookupError("Procurement intake not found")
            return _model(row) if idempotency_key in json.loads(row.action_keys or "[]") else None

    def save(self, intake: ProcurementIntake, expected_version: int, idempotency_key: str) -> ProcurementIntake:
        try:
            with SessionLocal() as db:
                row = db.get(ProcurementIntakeRow, intake.id)
                if not row:
                    raise LookupError("Procurement intake not found")
                keys = json.loads(row.action_keys or "[]")
                if idempotency_key in keys:
                    return _model(row)
                if row.version != expected_version:
                    raise VersionConflictError("This intake changed in another session. Refresh before editing it.")
                now = datetime.now(UTC)
                saved = intake.model_copy(update={"version": row.version + 1, "updated_at": now})
                row.status = saved.status
                row.version = saved.version
                row.data = saved.model_dump_json()
                row.updated_at = now
                row.action_keys = json.dumps([*keys[-99:], idempotency_key])
                db.commit()
                return saved
        except (LookupError, VersionConflictError):
            raise
        except Exception as exc:
            raise PersistenceError("The intake update could not be saved") from exc

    def list_for_buyer(self, buyer_id: str) -> list[ProcurementIntake]:
        with SessionLocal() as db:
            rows = db.scalars(select(ProcurementIntakeRow).where(ProcurementIntakeRow.buyer_id == buyer_id).order_by(ProcurementIntakeRow.updated_at.desc())).all()
            return [_model(row) for row in rows]

    def list_all(self) -> list[ProcurementIntake]:
        with SessionLocal() as db:
            rows = db.scalars(select(ProcurementIntakeRow).order_by(ProcurementIntakeRow.updated_at.desc())).all()
            return [_model(row) for row in rows]
