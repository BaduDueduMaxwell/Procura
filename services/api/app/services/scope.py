import re

from app.domain.models import ProcurementRequest
from app.services.catalog_terms import CATALOG_MEDICINES

SCOPE_REJECTION_TOOL = "reject_out_of_scope_message"

_PROCUREMENT_TERMS = {
    "authorization",
    "cold chain",
    "compare",
    "cost",
    "deliver",
    "delivery",
    "destination",
    "dosage",
    "drug",
    "inventory",
    "medicine",
    "order",
    "pack",
    "price",
    "procure",
    "quotation",
    "quote",
    "strength",
    "supplier",
}

_STRUCTURED_PROCUREMENT_VALUE = re.compile(
    r"\b(?:\d[\d,]*(?:\.\d+)?\s*(?:mg|g|iu/ml|units/ml|packs?|units?|days?)|"
    r"usd|eur|gbp|ghs|kes|tablets?|capsules?|vials?|bottles?|sachets?|ampoules?)\b",
    re.IGNORECASE,
)

_DOSAGE_FORM = re.compile(r"\b(?:tablet|capsule|vial|bottle|sachet|ampoule|syrup|solution|suspension|injection)s?\b", re.IGNORECASE)
_STRENGTH = re.compile(r"\b\d+(?:\.\d+)?\s*(?:mcg|mg|g|iu|units)(?:/\s*(?:ml|dose))?\b", re.IGNORECASE)
_POSITIVE_INTEGER = re.compile(r"^\s*\d[\d,]*\s*(?:packs?|units?)?\s*[.!]?\s*$", re.IGNORECASE)
_DELIVERY = re.compile(r"\b(?:within\s+)?\d+\s*(?:business\s+)?days?\b|\b\d{4}-\d{2}-\d{2}\b", re.IGNORECASE)
_CURRENCY = re.compile(r"^\s*(?:USD|EUR|GBP|GHS|KES|US dollars?|euros?|pounds?|cedis?|shillings?)\s*[.!]?\s*$", re.IGNORECASE)
_PLACE = re.compile(r"^[A-Z][A-Za-z'-]+(?:[ ,]+[A-Z][A-Za-z'-]+){0,3}$")
_REQUEST_INTENT = re.compile(r"\b(?:need|require|request|source|buy|procure|compare|quote|quotation|supplier|deliver)\b", re.IGNORECASE)
_KNOWN_DESTINATIONS = {
    "accra",
    "ghana",
    "kumasi",
    "kenya",
    "kampala",
    "lagos",
    "nairobi",
    "nigeria",
    "uganda",
}


def _is_expected_clarification(content: str, previous: ProcurementRequest) -> bool:
    """Validate terse follow-ups against the exact field Procura requested."""

    missing = previous.missing_fields()
    if not missing:
        return False
    expected = missing[0]
    if expected in {"quantity", "pack size"}:
        return bool(_POSITIVE_INTEGER.fullmatch(content))
    if expected == "strength":
        return bool(_STRENGTH.search(content))
    if expected == "dosage form":
        return bool(_DOSAGE_FORM.fullmatch(content.strip(" .")))
    if expected == "delivery requirement":
        return bool(_DELIVERY.search(content))
    if expected == "currency":
        return bool(_CURRENCY.fullmatch(content))
    if expected == "destination":
        cleaned = content.strip(" .")
        parts = {part.strip().lower() for part in cleaned.split(",")}
        return parts.issubset(_KNOWN_DESTINATIONS) or bool(_PLACE.fullmatch(cleaned))
    if expected == "medicine name":
        # Catalog names are accepted above. An unlisted medicine must include
        # a strength or dosage form so arbitrary nouns cannot enter the agent.
        return False
    return False


def is_procurement_message(content: str, previous: ProcurementRequest | None = None) -> bool:
    """Route only procurement turns to the language provider."""

    normalized = " ".join(content.split()).strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    if any(medicine in lowered for medicine in CATALOG_MEDICINES):
        return True
    if _STRUCTURED_PROCUREMENT_VALUE.search(lowered) or _DOSAGE_FORM.search(lowered) or _STRENGTH.search(lowered):
        return True
    if previous and _is_expected_clarification(normalized, previous):
        return True
    matched_terms = sum(term in lowered for term in _PROCUREMENT_TERMS)
    return bool(_REQUEST_INTENT.search(lowered) and matched_terms >= 2)


def scope_redirect(request: ProcurementRequest) -> str:
    missing = request.missing_fields()
    if missing:
        return f"Procura handles medicine procurement only. To continue this request, what {missing[0]} should I use?"
    return "Procura handles medicine procurement only. Ask about this supplier comparison or start a new medicine request."
