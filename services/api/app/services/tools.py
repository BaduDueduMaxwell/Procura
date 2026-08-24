from datetime import UTC, date, datetime
from statistics import median

from app.domain.models import (
    EligibilityResult,
    HumanReviewCase,
    ProcurementRequest,
    QuoteScore,
    Supplier,
    SupplierQuote,
    ToolResult,
)


def normalize_procurement_request(request: ProcurementRequest) -> ProcurementRequest:
    data = request.model_dump()
    med = data["medicine"]
    for key in ("medicine_name", "strength", "dosage_form"):
        if med.get(key): med[key] = " ".join(med[key].strip().lower().split())
    if data.get("currency"): data["currency"] = data["currency"].upper()
    if data.get("destination"): data["destination"] = data["destination"].strip().title()
    return ProcurementRequest.model_validate(data)


def search_synthetic_suppliers(request: ProcurementRequest, suppliers: list[Supplier]) -> list[tuple[Supplier, SupplierQuote]]:
    return [(s, q) for s in suppliers for q in s.quotes if q.line.medicine_name == request.medicine.medicine_name and q.line.strength == request.medicine.strength and q.line.dosage_form == request.medicine.dosage_form]


def validate_supplier_authorization(supplier: Supplier, today: date | None = None) -> ToolResult:
    today = today or datetime.now(UTC).date()
    auth = supplier.authorization
    passed = auth.status == "authorized" and bool(auth.expiry_date and auth.expiry_date >= today)
    detail = "Authorization verified" if passed else ("Authorization missing" if auth.status == "missing" else "Authorization expired")
    return ToolResult(tool="validate_supplier_authorization", passed=passed, detail=detail)


def validate_destination_support(request: ProcurementRequest, supplier: Supplier) -> ToolResult:
    passed = bool(request.destination in supplier.capability.destinations)
    return ToolResult(tool="validate_destination_support", passed=passed, detail="Destination supported" if passed else "Destination not supported")


def validate_cold_chain_capability(request: ProcurementRequest, supplier: Supplier) -> ToolResult:
    passed = not request.medicine.cold_chain_required or supplier.capability.cold_chain
    return ToolResult(tool="validate_cold_chain_capability", passed=passed, detail="Cold-chain compatible" if passed else "Cold-chain capability unavailable")


def validate_quote_units(request: ProcurementRequest, quote: SupplierQuote) -> ToolResult:
    passed = request.medicine.pack_size == quote.line.pack_size and request.medicine.quantity == quote.line.quantity_packs and request.medicine.unit == "packs"
    return ToolResult(tool="validate_quote_units", passed=passed, detail="Pack size and units match" if passed else f"Requested {request.medicine.quantity} packs × {request.medicine.pack_size}; quote is {quote.line.quantity_packs} packs × {quote.line.pack_size}")


def validate_delivery_deadline(request: ProcurementRequest, quote: SupplierQuote) -> ToolResult:
    passed = request.max_lead_time_days is not None and quote.lead_time_days <= request.max_lead_time_days
    return ToolResult(tool="validate_delivery_deadline", passed=passed, detail=f"{quote.lead_time_days} day lead time {'meets' if passed else 'misses'} requirement")


def compare_quote_prices(request: ProcurementRequest, matches: list[tuple[Supplier, SupplierQuote]]) -> dict[str, ToolResult]:
    same_currency = [q.total_price for _, q in matches if q.currency == request.currency]
    med = median(same_currency) if same_currency else None
    results = {}
    for _, q in matches:
        if q.currency != request.currency:
            results[q.id] = ToolResult(tool="compare_quote_prices", passed=False, detail=f"Currency {q.currency} cannot be compared with {request.currency} without a verified rate")
        elif med and q.total_price > 2.5 * med:
            results[q.id] = ToolResult(tool="compare_quote_prices", passed=False, detail="Price exceeds 2.5× median anomaly threshold")
        else:
            results[q.id] = ToolResult(tool="compare_quote_prices", passed=True, detail="Currency matches and price is within deterministic threshold")
    return results


def evaluate_quote(request: ProcurementRequest, supplier: Supplier, quote: SupplierQuote, price: ToolResult) -> EligibilityResult:
    checks = [validate_supplier_authorization(supplier), validate_destination_support(request, supplier), validate_cold_chain_capability(request, supplier), validate_quote_units(request, quote), validate_delivery_deadline(request, quote), price]
    return EligibilityResult(supplier_id=supplier.id, quote_id=quote.id, eligible=all(c.passed for c in checks), reasons=[c.detail for c in checks if not c.passed], tool_results=checks)


def rank_eligible_quotes(items: list[tuple[Supplier, SupplierQuote, EligibilityResult]]) -> list[QuoteScore]:
    eligible = [(s, q, e) for s, q, e in items if e.eligible]
    min_price = min((q.total_price for _, q, _ in eligible), default=1)
    min_delivery = min((q.lead_time_days for _, q, _ in eligible), default=1)
    scores = []
    for s, q, e in items:
        score = None if not e.eligible else round(.5 * min_price / q.total_price + .25 * min_delivery / q.lead_time_days + .25 * s.reliability_score, 4)
        scores.append(QuoteScore(supplier_id=s.id, quote_id=q.id, total_price=q.total_price, currency=q.currency, lead_time_days=q.lead_time_days, reliability=s.reliability_score, score=score, eligible=e.eligible, reasons=e.reasons))
    return sorted(scores, key=lambda x: (not x.eligible, -(x.score or 0)))


def create_human_review_case(case: HumanReviewCase) -> HumanReviewCase:
    return case
