import json
import re
from abc import ABC, abstractmethod
from typing import Any

from app.domain.errors import InvalidModelOutputError, ProviderUnavailableError
from app.domain.models import ProcurementRequest
from app.services.catalog_terms import CATALOG_MEDICINES
from openai import AsyncOpenAI


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def extract(self, text: str, previous: ProcurementRequest | None = None) -> ProcurementRequest: ...

    @abstractmethod
    async def select_tools(self, request: ProcurementRequest) -> list[str]: ...


REQUIRED_TOOL_PLAN = [
    "search_synthetic_suppliers",
    "compare_quote_prices",
    "validate_supplier_authorization",
    "validate_destination_support",
    "validate_cold_chain_capability",
    "validate_quote_units",
    "validate_delivery_deadline",
    "rank_eligible_quotes",
]


def _merge(previous: ProcurementRequest | None, values: dict[str, Any]) -> ProcurementRequest:
    base = previous.model_dump() if previous else {"medicine": {}}
    med = base.setdefault("medicine", {})
    for key in ("medicine_name", "strength", "dosage_form", "quantity", "pack_size", "unit", "cold_chain_required"):
        if values.get(key) is not None:
            med[key] = values[key]
    for key in ("destination", "max_lead_time_days", "currency", "buyer_notes"):
        if values.get(key) is not None:
            base[key] = values[key]
    base.pop("id", None)
    return ProcurementRequest.model_validate(base)


class DeterministicLLMProvider(LLMProvider):
    name = "local"

    async def extract(self, text: str, previous: ProcurementRequest | None = None) -> ProcurementRequest:
        lower = text.lower().strip()
        if "provider failure" in lower:
            raise ProviderUnavailableError("Simulated local provider failure")
        values: dict[str, Any] = {"buyer_notes": text[:500]}
        values["medicine_name"] = next((medicine for medicine in CATALOG_MEDICINES if medicine in lower), None)
        strength = re.search(r"\b(\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?)\s*(mg|g|iu/ml|units/ml)\b", lower)
        values["strength"] = f"{strength.group(1)} {strength.group(2)}" if strength else None
        form_match = re.search(r"\b(tablets?|capsules?|vials?|bottles?|sachets?|ampoules?)\b", lower)
        values["dosage_form"] = form_match.group(1).rstrip("s") if form_match else None
        qty = re.search(r"\b(\d[\d,]*)\s*(?:packs?|units?)\b", lower)
        values["quantity"] = int(qty.group(1).replace(",", "")) if qty else None
        pack = re.search(r"(?:pack(?:ed| size)?(?: of|\s|=)|×|x)\s*(\d+)\b", lower)
        values["pack_size"] = int(pack.group(1)) if pack else None
        days = re.search(r"(?:within|max(?:imum)?(?: lead time)?\s*)\s*(\d+)\s*days?", lower)
        values["max_lead_time_days"] = int(days.group(1)) if days else None
        countries = {"accra": "Ghana", "ghana": "Ghana", "nairobi": "Kenya", "kenya": "Kenya", "kampala": "Uganda", "uganda": "Uganda", "lagos": "Nigeria", "nigeria": "Nigeria"}
        values["destination"] = next((v for k, v in countries.items() if k in lower), None)
        currency = re.search(r"\b(usd|eur|gbp|ghs|kes)\b", lower)
        values["currency"] = currency.group(1).upper() if currency else None
        if any(term in lower for term in ("cold chain", "refrigerated", "2-8")):
            values["cold_chain_required"] = True
        if previous and not values["dosage_form"] and lower in {"tablet", "tablets", "capsule", "capsules", "vial", "vials"}:
            values["dosage_form"] = lower.rstrip("s")
        return _merge(previous, values)

    async def select_tools(self, request: ProcurementRequest) -> list[str]:
        return REQUIRED_TOOL_PLAN.copy()


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str, policy: str):
        self.client, self.model, self.policy = AsyncOpenAI(api_key=api_key), model, policy

    async def extract(self, text: str, previous: ProcurementRequest | None = None) -> ProcurementRequest:
        schema = ProcurementRequest.model_json_schema()
        prompt = f"{self.policy}\nExtract only stated procurement facts. Previous draft: {previous.model_dump_json() if previous else 'none'}"
        for attempt in range(2):
            try:
                result = await self.client.responses.create(model=self.model, instructions=prompt, input=text, text={"format": {"type": "json_schema", "name": "procurement_request", "schema": schema, "strict": True}})
                return ProcurementRequest.model_validate(json.loads(result.output_text))
            except Exception as exc:
                if attempt == 1:
                    raise InvalidModelOutputError("Provider returned invalid structured output") from exc
        raise InvalidModelOutputError("Unreachable")

    async def select_tools(self, request: ProcurementRequest) -> list[str]:
        tools = [{"type": "function", "name": name, "description": f"Required deterministic procurement step: {name}", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}, "strict": True} for name in REQUIRED_TOOL_PLAN]
        result = await self.client.responses.create(model=self.model, input=f"Select every deterministic tool required to evaluate this complete request: {request.model_dump_json()}", tools=tools, tool_choice="required", parallel_tool_calls=False)
        selected = [item.name for item in result.output if getattr(item, "type", None) == "function_call"]
        if selected != REQUIRED_TOOL_PLAN:
            raise InvalidModelOutputError("Hosted provider did not return the required safe tool sequence")
        return selected
