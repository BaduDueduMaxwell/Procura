import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.domain.errors import InvalidModelOutputError, ProviderUnavailableError
from app.domain.models import IntakeLine
from app.services.catalog_terms import CATALOG_MEDICINES
from app.services.scope import is_procurement_message


class IntakeExtraction(BaseModel):
    medicine_name: str | None = None
    brand_name: str | None = None
    strength: str | None = None
    dosage_form: str | None = None
    quantity: int | None = None
    unit: str | None = None
    pack_size: int | None = None
    destination: str | None = None
    max_lead_time_days: int | None = None
    currency: str | None = None
    cold_chain_required: bool = False


def _require_procurement_scope(text: str) -> None:
    if not is_procurement_message(text):
        raise ValueError("Describe a medicine procurement requirement or upload a procurement list")


def _destination(text: str) -> str | None:
    locations = {
        "accra": "Ghana", "ghana": "Ghana", "nairobi": "Kenya", "kenya": "Kenya",
        "kampala": "Uganda", "uganda": "Uganda", "lagos": "Nigeria", "nigeria": "Nigeria",
    }
    lowered = text.lower()
    return next((country for place, country in locations.items() if place in lowered), None)


class DeterministicIntakeInterpreter:
    name = "local"

    def interpret(self, text: str) -> IntakeLine:
        _require_procurement_scope(text)
        lowered = " ".join(text.lower().split())
        known = next((medicine for medicine in CATALOG_MEDICINES if medicine in lowered), None)
        medicine_match = re.search(
            r"(?:of|need|require|request)\s+(?:\d[\d,]*\s+(?:packs?|units?)\s+of\s+)?([a-z][a-z-]*(?:\s+[a-z][a-z-]*){0,2})\s+\d",
            lowered,
        )
        medicine = known or (medicine_match.group(1).strip() if medicine_match else None)
        strength_match = re.search(r"\b(\d+(?:\.\d+)?(?:\s*(?:mg|mcg|g|iu|units)(?:\s*/\s*(?:ml|5\s*ml|dose))?))\b", lowered)
        form_match = re.search(r"\b(tablets?|capsules?|vials?|ampoules?|bottles?|sachets?|syrups?|solutions?|suspensions?|injections?)\b", lowered)
        quantity_match = re.search(r"\b(\d[\d,]*)\s*(packs?|units?)\b", lowered)
        pack_match = re.search(r"\bpack(?:\s+size|ed)?(?:\s+of|\s*[:=])?\s*(\d+)\b", lowered)
        lead_match = re.search(r"\bwithin\s+(\d+)\s*(?:business\s+)?days?\b", lowered)
        currency_match = re.search(r"\b(usd|eur|gbp|ghs|kes)\b", lowered)
        unit = quantity_match.group(2) if quantity_match else None
        values: dict[str, Any] = {
            "source_row": 1,
            "medicine_name": medicine,
            "strength": strength_match.group(1) if strength_match else None,
            "dosage_form": form_match.group(1).rstrip("s") if form_match else None,
            "quantity": int(quantity_match.group(1).replace(",", "")) if quantity_match else None,
            "unit": "packs" if unit and unit.startswith("pack") else "units" if unit else None,
            "pack_size": int(pack_match.group(1)) if pack_match else None,
            "destination": _destination(text),
            "max_lead_time_days": int(lead_match.group(1)) if lead_match else None,
            "currency": currency_match.group(1).upper() if currency_match else None,
            "cold_chain_required": any(value in lowered for value in ("cold chain", "refrigerated", "2-8")),
            "original_values": {"request": text[:500]},
        }
        return IntakeLine.model_validate(values)


class LangChainGeminiInterpreter:
    name = "gemini"

    def __init__(self, settings: Settings, policy: str):
        if not settings.llm_api_key:
            raise ProviderUnavailableError("Gemini is selected but its API key is not configured")
        model = ChatGoogleGenerativeAI(
            model=settings.llm_model,
            google_api_key=settings.llm_api_key,
            temperature=0,
            timeout=settings.llm_timeout_seconds,
            max_retries=1,
        )
        self.structured_model = model.with_structured_output(IntakeExtraction)
        self.policy = policy

    def interpret(self, text: str) -> IntakeLine:
        _require_procurement_scope(text)
        instruction = (
            f"{self.policy}\n\nExtract only facts stated by the buyer. Return null for missing values. "
            "Do not invent a medicine, supplier, price, inventory, authorization, or compliance fact. "
            "Do not correct medicine names silently. Preserve the buyer's spelling."
        )
        for attempt in range(2):
            try:
                result = self.structured_model.invoke([SystemMessage(content=instruction), HumanMessage(content=text)])
                extraction = result if isinstance(result, IntakeExtraction) else IntakeExtraction.model_validate(result)
                return IntakeLine(source_row=1, original_values={"request": text[:500]}, **extraction.model_dump())
            except ValidationError as exc:
                if attempt == 1:
                    raise InvalidModelOutputError("Gemini returned invalid intake data after one retry") from exc
            except Exception as exc:
                raise ProviderUnavailableError("The request interpreter is temporarily unavailable") from exc
        raise InvalidModelOutputError("Gemini returned invalid intake data")


def build_intake_interpreter(settings: Settings, policy: str):
    if settings.llm_provider.strip().lower() in {"local", "demo"}:
        return DeterministicIntakeInterpreter()
    if settings.llm_provider.strip().lower() == "gemini":
        return LangChainGeminiInterpreter(settings, policy)
    return DeterministicIntakeInterpreter()
