import re
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, HttpUrl, model_validator

from app.config import find_knowledge_path
from app.services.catalog_terms import CATALOG_MEDICINES


def canonicalize_brand_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


class GhanaBrandRecord(BaseModel):
    brand_name: str
    registered_product_name: str
    registered_active_ingredient: str
    generic_name: str
    strength: str
    dosage_form: str
    manufacturer: str
    representative_company: str
    source_record_id: str
    source_url: HttpUrl
    registration_status: str
    registration_expiry: date


class GhanaBrandCatalogue(BaseModel):
    catalogue_version: str
    source_name: str
    registry_url: HttpUrl
    retrieved_at: date
    records: list[GhanaBrandRecord]

    @model_validator(mode="after")
    def validate_reference_data(self) -> "GhanaBrandCatalogue":
        names = [canonicalize_brand_name(record.brand_name) for record in self.records]
        if len(names) != len(set(names)):
            raise ValueError("Ghana brand catalogue contains duplicate brand names")
        unsupported = sorted({record.generic_name for record in self.records} - set(CATALOG_MEDICINES))
        if unsupported:
            raise ValueError(f"Ghana brand catalogue contains unsupported generic names: {unsupported}")
        if any(record.registration_status.casefold() != "valid" for record in self.records):
            raise ValueError("Ghana brand catalogue may contain only valid source records")
        return self


@lru_cache(maxsize=1)
def load_ghana_brand_catalogue(path: Path | None = None) -> GhanaBrandCatalogue:
    source = path or find_knowledge_path("GHANA_MEDICINE_BRANDS.json")
    return GhanaBrandCatalogue.model_validate_json(source.read_text(encoding="utf-8"))


def find_ghana_brand(value: str) -> tuple[GhanaBrandCatalogue, GhanaBrandRecord] | None:
    catalogue = load_ghana_brand_catalogue()
    key = canonicalize_brand_name(value)
    record = next(
        (
            item
            for item in catalogue.records
            if canonicalize_brand_name(item.brand_name) == key
            and item.registration_expiry >= datetime.now(UTC).date()
        ),
        None,
    )
    return (catalogue, record) if record else None
