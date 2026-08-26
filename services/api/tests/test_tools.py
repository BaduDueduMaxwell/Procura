from datetime import date

from app.domain.models import MedicineRequirement, ProcurementRequest
from app.services.catalog_terms import CATALOG_MEDICINES
from app.services.seed import synthetic_suppliers
from app.services.tools import (
    compare_quote_prices,
    evaluate_quote,
    normalize_procurement_request,
    rank_eligible_quotes,
    search_synthetic_suppliers,
    validate_cold_chain_capability,
    validate_delivery_deadline,
    validate_destination_support,
    validate_quote_units,
    validate_supplier_authorization,
)


def request(**changes):
    data = {"medicine": MedicineRequirement(medicine_name=" Amoxicillin ", strength="500 MG", dosage_form="Capsule", quantity=2000, pack_size=100), "destination": "ghana", "max_lead_time_days": 21, "currency": "usd"}
    data.update(changes); return normalize_procurement_request(ProcurementRequest(**data))


def test_normalization_and_missing_fields():
    normalized = request(); assert normalized.medicine.medicine_name == "amoxicillin" and normalized.currency == "USD" and not normalized.missing_fields()
    assert "pack size" in ProcurementRequest(medicine=MedicineRequirement()).missing_fields()


def test_normalization_maps_supported_destination_cities_to_countries():
    assert request(destination="Accra").destination == "Ghana"
    assert request(destination="nairobi").destination == "Kenya"


def test_normalization_singularizes_supported_dosage_forms():
    plural = request(
        medicine=MedicineRequirement(
            medicine_name="omeprazole",
            strength="20 mg",
            dosage_form="capsules",
            quantity=600,
            pack_size=28,
        )
    )

    assert plural.medicine.dosage_form == "capsule"


def test_normalization_canonicalizes_singular_pack_unit_from_model_output():
    singular = request(
        medicine=MedicineRequirement(
            medicine_name="omeprazole",
            strength="20 mg",
            dosage_form="capsule",
            quantity=600,
            pack_size=28,
            unit="pack",
        )
    )

    assert singular.medicine.unit == "packs"


def test_authorization_expiry_and_missing():
    suppliers = synthetic_suppliers(); assert validate_supplier_authorization(suppliers[0], date(2026, 1, 1)).passed
    assert not validate_supplier_authorization(suppliers[2]).passed and "missing" in validate_supplier_authorization(suppliers[2]).detail.lower()
    assert not validate_supplier_authorization(suppliers[3]).passed


def test_destination_cold_chain_units_and_deadline():
    req = request(); northstar, kora = synthetic_suppliers()[:2]
    assert validate_destination_support(req, northstar).passed
    assert not validate_destination_support(request(destination="Nigeria"), northstar).passed
    cold = request(medicine=req.medicine.model_copy(update={"cold_chain_required": True}))
    assert not validate_cold_chain_capability(cold, kora).passed
    assert validate_quote_units(req, northstar.quotes[0]).passed
    smaller = request(medicine=req.medicine.model_copy(update={"quantity": 1500}))
    assert validate_quote_units(smaller, northstar.quotes[0]).passed
    too_many = request(medicine=req.medicine.model_copy(update={"quantity": 2500}))
    assert "Availability shortfall" in validate_quote_units(too_many, northstar.quotes[0]).detail
    assert not validate_quote_units(request(medicine=req.medicine.model_copy(update={"pack_size": 50})), northstar.quotes[0]).passed
    assert validate_delivery_deadline(req, northstar.quotes[0]).passed and not validate_delivery_deadline(req, kora.quotes[0]).passed


def test_price_comparison_and_ranking():
    req = request(); matches = search_synthetic_suppliers(req, synthetic_suppliers()); prices = compare_quote_prices(req, matches)
    evaluated = [(s, q, evaluate_quote(req, s, q, prices[q.id])) for s, q in matches]
    ranked = rank_eligible_quotes(req, evaluated)
    assert ranked[0].supplier_id == "northstar" and ranked[0].eligible
    assert ranked[1].supplier_id == "kora" and not ranked[1].eligible


def test_seeded_catalog_supports_multiple_medicines():
    req = request(medicine=MedicineRequirement(medicine_name="paracetamol", strength="500 mg", dosage_form="tablet", quantity=1500, pack_size=20), max_lead_time_days=18)
    matches = search_synthetic_suppliers(req, synthetic_suppliers())
    assert {quote.line.medicine_name for _, quote in matches} == {"paracetamol"}
    prices = compare_quote_prices(req, matches)
    ranked = rank_eligible_quotes(req, [(supplier, quote, evaluate_quote(req, supplier, quote, prices[quote.id])) for supplier, quote in matches])
    assert ranked[0].eligible and ranked[0].supplier_id == "northstar"
    assert ranked[0].total_price == 690.0
    assert ranked[0].requested_quantity_packs == 1500
    assert ranked[0].available_quantity_packs == 5000


def test_seeded_catalog_contains_exactly_twenty_searchable_medicines():
    medicines = {quote.line.medicine_name for supplier in synthetic_suppliers() for quote in supplier.quotes}
    assert medicines == set(CATALOG_MEDICINES)


def test_currency_mismatch_is_not_converted():
    req = request(currency="EUR"); matches = search_synthetic_suppliers(req, synthetic_suppliers())
    assert all(not item.passed and "without a verified rate" in item.detail for item in compare_quote_prices(req, matches).values())


def test_price_outlier_uses_documented_threshold():
    req = request(medicine=MedicineRequirement(medicine_name="amoxicillin", strength="500 mg", dosage_form="tablet", quantity=2000, pack_size=50))
    matches = search_synthetic_suppliers(req, synthetic_suppliers())
    results = compare_quote_prices(req, matches)
    assert not results["q-lumina"].passed and "2.5× median" in results["q-lumina"].detail
