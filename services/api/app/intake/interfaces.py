from dataclasses import dataclass
from typing import Protocol

from app.domain.models import IntakeLine, ProcurementIntake


@dataclass(frozen=True)
class ParsedIntake:
    source_type: str
    filename: str | None
    lines: list[IntakeLine]
    sheet_names: list[str]


class FileParser(Protocol):
    def parse(self, filename: str, content: bytes, content_type: str | None = None) -> ParsedIntake: ...


class ProcurementInterpreter(Protocol):
    name: str

    def interpret(self, text: str) -> IntakeLine: ...


class IntakeRepository(Protocol):
    def create(self, intake: ProcurementIntake, idempotency_key: str) -> ProcurementIntake: ...
    def get(self, intake_id: str, buyer_id: str, allow_admin: bool = False) -> ProcurementIntake: ...
    def save(self, intake: ProcurementIntake, expected_version: int, idempotency_key: str) -> ProcurementIntake: ...
    def list_for_buyer(self, buyer_id: str) -> list[ProcurementIntake]: ...
