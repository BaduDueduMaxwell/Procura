import re
from uuid import uuid4

from app.domain.models import HumanReviewCase, ReviewBrief, SupplierQuoteDraft

QUOTE_FIELDS = (
    "medicine_name",
    "strength",
    "dosage_form",
    "pack_size",
    "available_quantity_packs",
    "unit_price",
    "currency",
    "lead_time_days",
)


def draft_supplier_quote(content: str, provider: str) -> SupplierQuoteDraft:
    text = " ".join(content.split())
    lower = text.lower()
    strength_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(mg|g|mcg|iu/ml|units/ml)\b", lower)
    form_match = re.search(r"\b(tablets?|capsules?|vials?|bottles?|sachets?|ampoules?)\b", lower)
    quantity_match = re.search(r"\b([\d,]+)\s*(?:packs?|cases?)\b", lower)
    pack_match = re.search(r"(?:pack(?:\s+size)?(?:\s+of|\s*[:=])?|packed\s+in)\s*(\d+)\b", lower)
    price_match = re.search(r"\b(?:usd|eur|gbp|ghs|kes)\s*([\d,]+(?:\.\d+)?)|(?:at|for)\s*([\d,]+(?:\.\d+)?)\s*(?:usd|eur|gbp|ghs|kes)\b", lower)
    currency_match = re.search(r"\b(usd|eur|gbp|ghs|kes)\b", lower)
    lead_match = re.search(r"(?:within|lead(?:\s+time)?(?:\s+of|\s*[:=])?)\s*(\d+)\s*days?", lower)
    medicine_match = re.search(r"(?:packs?|cases?)\s+of\s+([a-z][a-z-]*(?:\s+[a-z][a-z-]*)?)(?=\s+\d|\s+(?:tablets?|capsules?|vials?|bottles?|sachets?|ampoules?)\b)", lower)
    if not medicine_match:
        medicine_match = re.search(r"^(?:offer(?:ing)?|quote(?:\s+for)?|supply(?:ing)?)?\s*([a-z][a-z-]+)(?=\s+\d|\s+(?:tablets?|capsules?|vials?))", lower)

    values = {
        "medicine_name": medicine_match.group(1).strip() if medicine_match else None,
        "strength": f"{strength_match.group(1)} {strength_match.group(2)}" if strength_match else None,
        "dosage_form": form_match.group(1).rstrip("s") if form_match else None,
        "pack_size": int(pack_match.group(1)) if pack_match else None,
        "available_quantity_packs": int(quantity_match.group(1).replace(",", "")) if quantity_match else None,
        "unit_price": float((price_match.group(1) or price_match.group(2)).replace(",", "")) if price_match else None,
        "currency": currency_match.group(1).upper() if currency_match else None,
        "lead_time_days": int(lead_match.group(1)) if lead_match else None,
    }
    missing = [field for field in QUOTE_FIELDS if values[field] is None]
    return SupplierQuoteDraft(
        **values,
        missing_fields=missing,
        ready_to_submit=not missing,
        summary="Quote draft is complete and ready for your confirmation." if not missing else f"Add {', '.join(field.replace('_', ' ') for field in missing)} before submitting.",
        provider=provider,
        trace_id=str(uuid4()),
    )


def create_review_brief(case: HumanReviewCase, provider: str) -> ReviewBrief:
    medicine = case.request.medicine
    evidence = [f"Escalation: {reason}" for reason in case.reasons]
    evidence.append(f"Request: {medicine.quantity or 'unknown'} packs of {medicine.medicine_name or 'unspecified medicine'} {medicine.strength or ''}".strip())
    evidence.append(f"Supplier quotations checked: {len(case.quotes)}; eligible: {sum(quote.eligible for quote in case.quotes)}")
    if case.recommendation_supplier_id:
        evidence.append(f"Current recommendation: {case.recommendation_supplier_id}")

    clarification_markers = ("missing information", "ambiguous", "pack size mismatch", "currency mismatch", "conflicting")
    normalized_reasons = [reason.replace("_", " ").lower() for reason in case.reasons]
    suggested_action = "request_clarification" if any(marker in reason for marker in clarification_markers for reason in normalized_reasons) else "reject"
    if case.recommendation_supplier_id and not case.reasons:
        suggested_action = "approve"
    reason = "Resolve missing or conflicting request evidence before a decision." if suggested_action == "request_clarification" else "The current evidence does not support an autonomous approval."
    return ReviewBrief(
        review_id=case.id,
        trace_id=case.trace_id,
        summary=f"Review {medicine.medicine_name or 'the request'} against {len(case.quotes)} supplier quotation(s). The policy raised {len(case.reasons)} exception(s).",
        evidence_points=evidence,
        suggested_action=suggested_action,
        suggestion_reason=reason,
        policy_version=case.policy_version,
        provider=provider,
    )
