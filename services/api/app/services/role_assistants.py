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

LEAD_TIME_REASON = re.compile(r"^(\d+) day lead time misses requirement$", re.IGNORECASE)
CURRENCY_REASON = re.compile(
    r"^Currency ([A-Z]{3}) cannot be compared with ([A-Z]{3}) without a verified rate$",
    re.IGNORECASE,
)


def _human_join(values: list[str]) -> str:
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"


def summarize_review_reasons(case: HumanReviewCase) -> list[str]:
    """Group repeated quote failures into concise, evidence-backed review reasons."""
    raw_reasons = [reason.removeprefix("Escalation: ").strip() for reason in case.reasons]
    summaries: list[str] = []
    consumed: set[int] = set()

    lead_times: list[int] = []
    for index, reason in enumerate(raw_reasons):
        match = LEAD_TIME_REASON.fullmatch(reason)
        if match:
            lead_times.append(int(match.group(1)))
            consumed.add(index)
    if lead_times:
        days = _human_join([str(value) for value in sorted(lead_times)])
        requirement = case.request.max_lead_time_days
        scope = "all " if len(lead_times) == len(case.quotes) and case.quotes else ""
        threshold = f"the {requirement}-day requirement" if requirement else "the required lead time"
        verb = "exceeds" if len(lead_times) == 1 else "exceed"
        summaries.append(
            f"Delivery: {scope}{len(lead_times)} quotation{'s' if len(lead_times) != 1 else ''} "
            f"{verb} {threshold} ({days} day{'s' if len(lead_times) != 1 else ''})."
        )

    expired = [index for index, reason in enumerate(raw_reasons) if reason.lower() == "authorization expired"]
    consumed.update(expired)
    if expired:
        actor = "one supplier has" if len(expired) == 1 else f"{len(expired)} suppliers have"
        summaries.append(f"Authorization: {actor} expired authorization.")

    currency_pairs: list[tuple[str, str]] = []
    for index, reason in enumerate(raw_reasons):
        match = CURRENCY_REASON.fullmatch(reason)
        if match:
            currency_pairs.append((match.group(1).upper(), match.group(2).upper()))
            consumed.add(index)
    for offered, requested in dict.fromkeys(currency_pairs):
        summaries.append(
            f"Currency: the {offered} quote cannot be compared with the requested {requested} "
            "without a verified rate."
        )

    no_eligible = [
        index
        for index, reason in enumerate(raw_reasons)
        if reason.lower()
        in {
            "no eligible quotation",
            "no eligible quotation is available after deterministic supplier checks",
        }
    ]
    consumed.update(no_eligible)

    for index, reason in enumerate(raw_reasons):
        if index in consumed:
            continue
        readable = reason.replace("_", " ").replace("  ", " ")
        summaries.append(f"{readable[:1].upper()}{readable[1:]}")

    if no_eligible:
        summaries.append("Outcome: no eligible quotation remains after deterministic supplier checks.")
    return summaries


def draft_supplier_quote(content: str, provider: str) -> SupplierQuoteDraft:
    text = " ".join(content.split())
    lower = text.lower()
    strength_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(mg|g|mcg|iu/ml|units/ml)\b", lower)
    form_match = re.search(r"\b(tablets?|capsules?|vials?|bottles?|sachets?|ampoules?)\b", lower)
    quantity_match = re.search(r"\b(\d[\d,]*)\s*(?:packs?|cases?)\b", lower)
    pack_match = re.search(r"(?:pack(?:\s+size)?(?:\s+of|\s*[:=])?|packed\s+in)\s*(\d+)\b", lower)
    price_match = re.search(r"\b(?:usd|eur|gbp|ghs|kes)\s*(\d[\d,]*(?:\.\d+)?)|(?:at|for)\s*(\d[\d,]*(?:\.\d+)?)\s*(?:usd|eur|gbp|ghs|kes)\b", lower)
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
    reason_summary = summarize_review_reasons(case)
    evidence = [*reason_summary]
    evidence.append(f"Request: {medicine.quantity or 'unknown'} packs of {medicine.medicine_name or 'unspecified medicine'} {medicine.strength or ''}".strip())
    eligible_count = sum(quote.eligible for quote in case.quotes)
    evidence.append(f"Supplier quotations checked: {len(case.quotes)}; eligible: {eligible_count}")
    if case.recommendation_supplier_id:
        evidence.append(f"Current recommendation: {case.recommendation_supplier_id}")

    clarification_markers = ("missing information", "ambiguous", "pack size mismatch", "currency mismatch", "conflicting")
    normalized_reasons = [reason.replace("_", " ").lower() for reason in case.reasons]
    suggested_action = "request_clarification" if any(marker in reason for marker in clarification_markers for reason in normalized_reasons) else "reject"
    recommended_quotes = [quote for quote in case.quotes if quote.supplier_id == case.recommendation_supplier_id]
    if recommended_quotes and all(quote.eligible for quote in recommended_quotes):
        suggested_action = "approve"
    if suggested_action == "approve":
        reason = "The recommended supplier passed the deterministic checks; organizational approval is still required."
    elif suggested_action == "request_clarification":
        reason = "Resolve missing or conflicting request evidence before a decision."
    else:
        reason = "The current evidence does not support an approval."
    return ReviewBrief(
        review_id=case.id,
        trace_id=case.trace_id,
        summary=(
            f"{eligible_count} of {len(case.quotes)} supplier quotations passed the required checks "
            f"for {medicine.medicine_name or 'this request'}."
        ),
        evidence_points=evidence,
        suggested_action=suggested_action,
        suggestion_reason=reason,
        policy_version=case.policy_version,
        provider=provider,
    )
