from app.domain.models import IntakeCatalogueOption, IntakeLine, MedicineCatalogItem
from app.intake.validators import catalogue_variants
from app.services.catalog import list_medicine_catalog
from app.services.tools import canonicalize_dosage_form, canonicalize_medicine_name, canonicalize_strength

CATALOGUE_HELP_CODES = {
    "catalogue_variant_mismatch",
    "missing_destination",
    "missing_currency",
    "missing_max_lead_time_days",
    "missing_strength",
    "missing_dosage_form",
    "missing_pack_size",
}


def source_record_id(item: MedicineCatalogItem) -> str:
    """Return a stable identifier for a repository-backed medicine variant."""
    medicine = canonicalize_medicine_name(item.medicine_name)
    strength = canonicalize_strength(item.strength)
    form = canonicalize_dosage_form(item.dosage_form)
    return f"catalogue:{medicine}:{strength}:{form}:pack-{item.pack_size}"


def _differences(line: IntakeLine, item: MedicineCatalogItem) -> list[str]:
    comparisons = (
        ("Medicine", canonicalize_medicine_name(line.medicine_name), canonicalize_medicine_name(item.medicine_name)),
        ("Strength", canonicalize_strength(line.strength), canonicalize_strength(item.strength)),
        ("Dosage form", canonicalize_dosage_form(line.dosage_form), canonicalize_dosage_form(item.dosage_form)),
        ("Pack size", str(line.pack_size) if line.pack_size else None, str(item.pack_size)),
    )
    return [f"{label}: {current or 'missing'} → {available}" for label, current, available in comparisons if current != available]


def option_from_item(line: IntakeLine, item: MedicineCatalogItem) -> IntakeCatalogueOption:
    return IntakeCatalogueOption(
        source_record_id=source_record_id(item),
        medicine_name=item.medicine_name,
        strength=item.strength,
        dosage_form=item.dosage_form,
        pack_size=item.pack_size,
        differences=_differences(line, item),
        quotation_count=item.quotation_count,
        authorized_supplier_count=item.authorized_supplier_count,
        available_quantity_packs=item.available_quantity_packs,
        currencies=item.currencies,
        destinations=item.destinations,
        cold_chain_available=item.cold_chain_available,
        minimum_lead_time_days=item.minimum_lead_time_days,
        unit_price_from=item.unit_price_from,
        unit_price_to=item.unit_price_to,
    )


def catalogue_options_for(line: IntakeLine, limit: int = 3) -> list[IntakeCatalogueOption]:
    """Find repository variants for the entered or buyer-confirmed medicine name."""
    query = line.medicine_name or line.brand_name or ""
    if line.suggestion and line.suggestion.status in {"pending", "accepted"}:
        query = line.suggestion.suggested_value
    if not query:
        return []
    return [option_from_item(line, item) for item in list_medicine_catalog(query, limit)]


def attach_catalogue_options(lines: list[IntakeLine]) -> list[IntakeLine]:
    """Attach options only to correctable known variants, caching repeated medicines."""
    known_names = {variant[0] for variant in catalogue_variants()}
    cache: dict[str, list[MedicineCatalogItem]] = {}
    result: list[IntakeLine] = []
    for line in lines:
        query = canonicalize_medicine_name(line.medicine_name or line.brand_name)
        needs_help = any(finding.code in CATALOGUE_HELP_CODES for finding in line.findings)
        if not query or query not in known_names or not needs_help or line.suggestion and line.suggestion.status == "pending":
            result.append(line.model_copy(update={"catalogue_options": []}))
            continue
        items = cache.setdefault(query, list_medicine_catalog(query, 3))
        result.append(line.model_copy(update={
            "catalogue_options": [option_from_item(line, item) for item in items],
        }))
    return result
