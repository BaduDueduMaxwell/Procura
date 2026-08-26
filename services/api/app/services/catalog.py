import json
from collections import defaultdict
from datetime import UTC, datetime

from app.domain.models import MedicineCatalogItem
from app.models.database import QuoteRow, SessionLocal, SupplierRow
from sqlalchemy import select


def list_medicine_catalog() -> list[MedicineCatalogItem]:
    """Build the buyer catalogue from approved supplier and quotation records."""
    with SessionLocal() as db:
        quotes = list(db.scalars(select(QuoteRow)).all())
        suppliers = {row.id: row for row in db.scalars(select(SupplierRow)).all()}

    grouped: dict[tuple[str, str, str, int], list[QuoteRow]] = defaultdict(list)
    for quote in quotes:
        grouped[(quote.medicine_name, quote.strength, quote.dosage_form, quote.pack_size)].append(quote)

    today = datetime.now(UTC).date()
    items: list[MedicineCatalogItem] = []
    for (medicine, strength, dosage_form, pack_size), variants in grouped.items():
        linked_suppliers = [suppliers[quote.supplier_id] for quote in variants if quote.supplier_id in suppliers]
        authorized = [supplier for supplier in linked_suppliers if supplier.authorization_status == "authorized" and supplier.authorization_expiry and supplier.authorization_expiry >= today]
        destinations = sorted({destination for supplier in authorized for destination in json.loads(supplier.destinations_json)})
        prices = [quote.unit_price for quote in variants]
        items.append(MedicineCatalogItem(
            medicine_name=medicine,
            strength=strength,
            dosage_form=dosage_form,
            pack_size=pack_size,
            quotation_count=len(variants),
            authorized_supplier_count=len({supplier.id for supplier in authorized}),
            available_quantity_packs=max(quote.quantity_packs for quote in variants),
            currencies=sorted({quote.currency for quote in variants}),
            destinations=destinations,
            cold_chain_available=any(supplier.cold_chain for supplier in authorized),
            minimum_lead_time_days=min(quote.lead_time_days for quote in variants),
            unit_price_from=min(prices),
            unit_price_to=max(prices),
            request_starter=f"We need {medicine} {strength} {dosage_form}s, pack size {pack_size}.",
        ))
    return sorted(items, key=lambda item: (item.medicine_name, item.strength, item.pack_size))
