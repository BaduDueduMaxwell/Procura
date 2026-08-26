import json
from collections import defaultdict
from datetime import UTC, datetime

from app.domain.models import MedicineCatalogItem
from app.models.database import QuoteRow, SessionLocal, SupplierRow
from sqlalchemy import and_, func, or_, select


def list_medicine_catalog(query: str = "", limit: int = 6) -> list[MedicineCatalogItem]:
    """Search a bounded set of medicine variants from approved quotation records."""
    normalized_query = " ".join(query.lower().split())
    with SessionLocal() as db:
        variant_query = select(
            QuoteRow.medicine_name,
            QuoteRow.strength,
            QuoteRow.dosage_form,
            QuoteRow.pack_size,
        ).distinct()
        if normalized_query:
            variant_query = variant_query.where(or_(
                func.lower(QuoteRow.medicine_name).contains(normalized_query, autoescape=True),
                func.lower(QuoteRow.strength).contains(normalized_query, autoescape=True),
                func.lower(QuoteRow.dosage_form).contains(normalized_query, autoescape=True),
            ))
        keys = list(db.execute(variant_query.order_by(
            QuoteRow.medicine_name,
            QuoteRow.strength,
            QuoteRow.dosage_form,
            QuoteRow.pack_size,
        ).limit(limit)).all())
        if not keys:
            return []
        quotes = list(db.scalars(select(QuoteRow).where(or_(*[
            and_(
                QuoteRow.medicine_name == key.medicine_name,
                QuoteRow.strength == key.strength,
                QuoteRow.dosage_form == key.dosage_form,
                QuoteRow.pack_size == key.pack_size,
            )
            for key in keys
        ]))).all())
        supplier_ids = {quote.supplier_id for quote in quotes}
        suppliers = {row.id: row for row in db.scalars(select(SupplierRow).where(SupplierRow.id.in_(supplier_ids))).all()}

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
