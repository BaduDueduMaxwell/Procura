import json
from datetime import date

from app.domain.models import QuoteLine, Supplier, SupplierAuthorization, SupplierCapability, SupplierQuote
from app.models.database import AppStateRow, QuoteRow, SessionLocal, SupplierRow
from sqlalchemy import select

SEED_SUPPLIERS = [
    {"id":"northstar","name":"Northstar Health Supply","status":"authorized","expiry":"2028-12-31","destinations":["Ghana","Kenya"],"cold":True,"reliability":.94,"price":5.20,"lead":14,"currency":"USD","pack":100,"form":"capsule"},
    {"id":"kora","name":"Kora Medical Logistics","status":"authorized","expiry":"2027-06-30","destinations":["Ghana","Uganda"],"cold":False,"reliability":.89,"price":4.85,"lead":30,"currency":"USD","pack":100,"form":"capsule"},
    {"id":"baobab","name":"Baobab Pharma Collective","status":"missing","expiry":None,"destinations":["Ghana","Kenya"],"cold":True,"reliability":.91,"price":4.60,"lead":18,"currency":"USD","pack":100,"form":"tablet"},
    {"id":"lumina","name":"Lumina Essential Medicines","status":"expired","expiry":"2023-09-01","destinations":["Ghana"],"cold":True,"reliability":.86,"price":13.80,"lead":17,"currency":"USD","pack":50,"form":"tablet"},
    {"id":"cedar","name":"Cedar Bridge Therapeutics","status":"expired","expiry":"2025-04-01","destinations":["Ghana","Kenya"],"cold":True,"reliability":.84,"price":4.80,"lead":16,"currency":"USD","pack":100,"form":"tablet"},
]

SEED_QUOTES = [
    # Amoxicillin 500 mg capsules, 2,000 packs of 100
    {"id":"q-northstar","supplier":"northstar","medicine":"amoxicillin","strength":"500 mg","form":"capsule","pack":100,"quantity":2000,"price":5.20,"lead":14,"currency":"USD"},
    {"id":"q-kora","supplier":"kora","medicine":"amoxicillin","strength":"500 mg","form":"capsule","pack":100,"quantity":2000,"price":4.85,"lead":30,"currency":"USD"},
    {"id":"q-baobab","supplier":"baobab","medicine":"amoxicillin","strength":"500 mg","form":"tablet","pack":100,"quantity":2000,"price":4.60,"lead":18,"currency":"USD"},
    {"id":"q-lumina","supplier":"lumina","medicine":"amoxicillin","strength":"500 mg","form":"tablet","pack":50,"quantity":2000,"price":13.80,"lead":17,"currency":"USD"},
    {"id":"q-baobab-amox-50","supplier":"baobab","medicine":"amoxicillin","strength":"500 mg","form":"tablet","pack":50,"quantity":3000,"price":4.60,"lead":18,"currency":"USD"},
    {"id":"q-cedar","supplier":"cedar","medicine":"amoxicillin","strength":"500 mg","form":"tablet","pack":50,"quantity":3000,"price":4.80,"lead":16,"currency":"USD"},
    # Paracetamol 500 mg tablets. Quantity is available capacity, not an order quantity.
    {"id":"q-northstar-paracetamol","supplier":"northstar","medicine":"paracetamol","strength":"500 mg","form":"tablet","pack":20,"quantity":5000,"price":0.46,"lead":12,"currency":"USD"},
    {"id":"q-kora-paracetamol","supplier":"kora","medicine":"paracetamol","strength":"500 mg","form":"tablet","pack":100,"quantity":5000,"price":2.18,"lead":16,"currency":"USD"},
    {"id":"q-baobab-paracetamol","supplier":"baobab","medicine":"paracetamol","strength":"500 mg","form":"tablet","pack":20,"quantity":5000,"price":0.41,"lead":14,"currency":"USD"},
    # Ceftriaxone 1 g vials, 500 packs of 10
    {"id":"q-northstar-ceftriaxone","supplier":"northstar","medicine":"ceftriaxone","strength":"1 g","form":"vial","pack":10,"quantity":500,"price":18.40,"lead":18,"currency":"USD"},
    {"id":"q-kora-ceftriaxone","supplier":"kora","medicine":"ceftriaxone","strength":"1 g","form":"vial","pack":10,"quantity":500,"price":17.90,"lead":24,"currency":"USD"},
    {"id":"q-lumina-ceftriaxone","supplier":"lumina","medicine":"ceftriaxone","strength":"1 g","form":"vial","pack":10,"quantity":500,"price":16.80,"lead":17,"currency":"EUR"},
    # Insulin 100 units/ml vials, 300 packs of 10 (cold chain)
    {"id":"q-northstar-insulin","supplier":"northstar","medicine":"insulin","strength":"100 units/ml","form":"vial","pack":10,"quantity":300,"price":42.00,"lead":15,"currency":"USD"},
    {"id":"q-kora-insulin","supplier":"kora","medicine":"insulin","strength":"100 units/ml","form":"vial","pack":10,"quantity":300,"price":39.50,"lead":14,"currency":"USD"},
    {"id":"q-cedar-insulin","supplier":"cedar","medicine":"insulin","strength":"100 units/ml","form":"vial","pack":10,"quantity":300,"price":41.25,"lead":16,"currency":"USD"},
]
CATALOG_VERSION = "procura-catalog-v2-capacity"


def seed_supplier_database() -> None:
    """Idempotently synchronize the application-owned fictional supplier catalog."""
    with SessionLocal() as db:
        state = db.get(AppStateRow, "supplier_catalog_version")
        if state and state.value == CATALOG_VERSION:
            return
        for item in SEED_SUPPLIERS:
            row = db.get(SupplierRow, item["id"])
            values = {"display_name":item["name"], "authorization_status":item["status"], "authorization_expiry":date.fromisoformat(item["expiry"]) if item["expiry"] else None, "destinations_json":json.dumps(item["destinations"]), "cold_chain":item["cold"], "reliability_score":item["reliability"], "synthetic":True}
            if row:
                for key, value in values.items(): setattr(row, key, value)
            else:
                db.add(SupplierRow(id=item["id"], **values))
        db.flush()
        for quote in SEED_QUOTES:
            row = db.get(QuoteRow, quote["id"])
            values = {"supplier_id":quote["supplier"], "currency":quote["currency"], "lead_time_days":quote["lead"], "medicine_name":quote["medicine"], "strength":quote["strength"], "dosage_form":quote["form"], "pack_size":quote["pack"], "quantity_packs":quote["quantity"], "unit_price":quote["price"]}
            if row:
                for key, value in values.items(): setattr(row, key, value)
            else:
                db.add(QuoteRow(id=quote["id"], **values))
        if state:
            state.value = CATALOG_VERSION
        else:
            db.add(AppStateRow(key="supplier_catalog_version", value=CATALOG_VERSION))
        db.commit()


def synthetic_suppliers() -> list[Supplier]:
    """Load suppliers and quotations from the database, never from request/model text."""
    with SessionLocal() as db:
        suppliers = db.scalars(select(SupplierRow)).all()
        supplier_order = {item["id"]: index for index, item in enumerate(SEED_SUPPLIERS)}
        suppliers.sort(key=lambda row: supplier_order.get(row.id, 999))
        quotes = db.scalars(select(QuoteRow)).all()
        by_supplier: dict[str, list[QuoteRow]] = {}
        for quote in quotes:
            by_supplier.setdefault(quote.supplier_id, []).append(quote)
        return [Supplier(id=row.id, display_name=row.display_name, authorization=SupplierAuthorization(status=row.authorization_status, expiry_date=row.authorization_expiry), capability=SupplierCapability(destinations=json.loads(row.destinations_json), cold_chain=row.cold_chain), reliability_score=row.reliability_score, quotes=[SupplierQuote(id=q.id, supplier_id=q.supplier_id, currency=q.currency, lead_time_days=q.lead_time_days, line=QuoteLine(medicine_name=q.medicine_name, strength=q.strength, dosage_form=q.dosage_form, pack_size=q.pack_size, quantity_packs=q.quantity_packs, unit_price=q.unit_price)) for q in by_supplier.get(row.id, [])]) for row in suppliers]
