from collections import Counter
from collections.abc import Callable
from difflib import SequenceMatcher, get_close_matches
from typing import Literal

from app.domain.models import CatalogueSuggestion, IntakeFinding, IntakeLine
from app.intake.brand_catalogue import find_ghana_brand
from app.services.seed import synthetic_suppliers
from app.services.tools import canonicalize_dosage_form, canonicalize_medicine_name, canonicalize_strength

REQUIRED_FIELDS = {
    "medicine_name": "medicine name", "strength": "strength", "dosage_form": "dosage form",
    "quantity": "quantity", "unit": "quantity unit", "pack_size": "pack size",
    "destination": "destination", "max_lead_time_days": "delivery requirement", "currency": "currency",
}


def catalogue_variants() -> set[tuple[str, str, str, int]]:
    return {
        (
            canonicalize_medicine_name(quote.line.medicine_name) or "",
            canonicalize_strength(quote.line.strength) or "",
            canonicalize_dosage_form(quote.line.dosage_form) or "",
            quote.line.pack_size,
        )
        for supplier in synthetic_suppliers()
        for quote in supplier.quotes
    }


def normalize_line(line: IntakeLine) -> IntakeLine:
    data = line.model_dump()
    data["medicine_name"] = canonicalize_medicine_name(line.medicine_name)
    data["strength"] = canonicalize_strength(line.strength)
    data["dosage_form"] = canonicalize_dosage_form(line.dosage_form)
    if line.unit:
        data["unit"] = {"pack": "packs", "unit": "units"}.get(line.unit.strip().lower(), line.unit.strip().lower())
    if line.destination:
        destination = line.destination.strip().title()
        data["destination"] = {"Accra": "Ghana", "Nairobi": "Kenya", "Kampala": "Uganda", "Lagos": "Nigeria"}.get(destination, destination)
    if line.currency:
        data["currency"] = line.currency.strip().upper()
    normalized = set(line.normalized_fields)
    for field in ("medicine_name", "strength", "dosage_form", "unit", "destination", "currency"):
        if data.get(field) != getattr(line, field):
            normalized.add(field)
    data["normalized_fields"] = sorted(normalized)
    return IntakeLine.model_validate(data)


def _finding(line: IntakeLine, code: str, severity: Literal["information", "warning", "blocker", "critical"], message: str, field: str | None, correctable: bool, action: str, source: str = "procura-policy-v1") -> IntakeFinding:
    return IntakeFinding(code=code, severity=severity, message=message, field=field, row_id=line.id, evidence_source=source, correctable_by_buyer=correctable, suggested_action=action)


def match_catalogue(line: IntakeLine) -> IntakeLine:
    data = line.model_dump()
    name = canonicalize_medicine_name(line.medicine_name or line.brand_name)
    if not name:
        return IntakeLine.model_validate(data)
    catalogue_names = sorted({item[0] for item in catalogue_variants()})
    brand_match = find_ghana_brand(name)
    suggested = brand_match[1].generic_name if brand_match else None
    reason = "Recognized Ghana FDA registered brand; confirm the generic medicine before continuing"
    if not suggested and name not in catalogue_names:
        matches = get_close_matches(name, catalogue_names, n=2, cutoff=0.72)
        if len(matches) == 1 or (matches and SequenceMatcher(None, name, matches[0]).ratio() >= 0.82):
            suggested = matches[0]
            reason = "Closest spelling match in the repository catalogue"
    if suggested and suggested != name and not (line.suggestion and line.suggestion.status == "rejected"):
        previous_status = line.suggestion.status if line.suggestion and line.suggestion.suggested_value == suggested else "pending"
        if brand_match:
            catalogue, record = brand_match
            suggestion = CatalogueSuggestion(
                original_value=name,
                suggested_value=suggested,
                match_reason=reason,
                source_record_id=record.source_record_id,
                source_url=str(record.source_url),
                source_name=catalogue.source_name,
                catalogue_version=catalogue.catalogue_version,
                brand_name=record.brand_name,
                manufacturer=record.manufacturer,
                representative_company=record.representative_company,
                registered_active_ingredient=record.registered_active_ingredient,
                registered_strength=record.strength,
                registered_dosage_form=record.dosage_form,
                registration_expiry=record.registration_expiry,
                status=previous_status,
                actor_id=line.suggestion.actor_id if line.suggestion else None,
                decided_at=line.suggestion.decided_at if line.suggestion else None,
            )
        else:
            suggestion = CatalogueSuggestion(
                original_value=name,
                suggested_value=suggested,
                match_reason=reason,
                source_record_id=f"catalogue:{suggested}",
                status=previous_status,
                actor_id=line.suggestion.actor_id if line.suggestion else None,
                decided_at=line.suggestion.decided_at if line.suggestion else None,
            )
        data["suggestion"] = suggestion.model_dump()
    return IntakeLine.model_validate(data)


def validate_required(line: IntakeLine) -> list[IntakeFinding]:
    return [
        _finding(line, f"missing_{field}", "blocker", f"Provide the {label} before submission.", field, True, f"Enter {label}")
        for field, label in REQUIRED_FIELDS.items()
        if getattr(line, field) in (None, "")
    ]


def validate_catalogue(line: IntakeLine) -> list[IntakeFinding]:
    if line.suggestion and line.suggestion.status == "pending":
        return [_finding(line, "catalogue_suggestion", "warning", f"Did you mean {line.suggestion.suggested_value}?", "medicine_name", True, "Accept the suggestion or edit the medicine", line.suggestion.source_record_id)]
    if not line.medicine_name:
        return []
    names = {item[0] for item in catalogue_variants()}
    if canonicalize_medicine_name(line.medicine_name) not in names:
        return [_finding(line, "catalogue_match_required", "blocker", "No exact catalogue match was found. Correct the medicine or select a catalogue suggestion.", "medicine_name", True, "Search and select the intended medicine", "synthetic-catalogue")]
    if line.strength and line.dosage_form and line.pack_size:
        variant = (
            canonicalize_medicine_name(line.medicine_name) or "",
            canonicalize_strength(line.strength) or "",
            canonicalize_dosage_form(line.dosage_form) or "",
            line.pack_size,
        )
        if variant not in catalogue_variants():
            return [_finding(line, "catalogue_variant_mismatch", "blocker", "The strength, dosage form, and pack size do not match one catalogue variant.", "medicine_name", True, "Choose an available catalogue variant", "synthetic-catalogue")]
    return []


def validate_units(line: IntakeLine) -> list[IntakeFinding]:
    if line.unit and line.unit not in {"packs", "units"}:
        return [_finding(line, "ambiguous_quantity_unit", "blocker", f"The quantity unit '{line.unit}' is not supported.", "unit", True, "Choose packs or units")]
    if line.unit == "units":
        return [_finding(line, "pack_conversion_confirmation", "blocker", "The requested quantity is in individual units. Confirm the equivalent number of packs.", "unit", True, "Convert the quantity to packs")]
    return []


VALIDATORS: tuple[Callable[[IntakeLine], list[IntakeFinding]], ...] = (validate_required, validate_catalogue, validate_units)


def duplicate_fingerprint(line: IntakeLine) -> tuple[object, ...]:
    """Identify exact repeated requirements without using price or supplier data."""
    return (
        canonicalize_medicine_name(line.medicine_name),
        canonicalize_strength(line.strength),
        canonicalize_dosage_form(line.dosage_form),
        line.quantity,
        line.unit,
        line.pack_size,
        line.destination,
        line.max_lead_time_days,
        line.currency,
    )


def validate_lines(lines: list[IntakeLine]) -> list[IntakeLine]:
    fingerprints = Counter(duplicate_fingerprint(line) for line in lines)
    result: list[IntakeLine] = []
    for line in lines:
        findings = [finding for validator in VALIDATORS for finding in validator(line)]
        fingerprint = duplicate_fingerprint(line)
        if line.medicine_name and fingerprints[fingerprint] > 1 and line.duplicate_resolution != "keep_both":
            findings.append(_finding(line, "possible_duplicate", "blocker", "This product appears more than once in the list.", "medicine_name", True, "Confirm or remove the duplicate"))
        if line.suggestion and line.suggestion.status == "pending":
            status = "suggestion_available"
        elif any(item.severity == "critical" for item in findings):
            status = "critical_review_required"
        elif any(item.severity == "blocker" for item in findings):
            status = "needs_correction"
        else:
            status = "ready"
        result.append(line.model_copy(update={"findings": findings, "status": status}))
    return result
