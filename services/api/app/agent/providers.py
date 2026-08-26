import json
import re
from abc import ABC, abstractmethod
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.domain.errors import InvalidModelOutputError, ProviderUnavailableError
from app.domain.models import ProcurementRequest
from app.services.catalog_terms import CATALOG_MEDICINES
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError


@dataclass(frozen=True)
class ProviderUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class ProviderInterpretation:
    request: ProcurementRequest
    tool_plan: list[str]


class ProcurementExtraction(BaseModel):
    """Facts interpreted from one user turn. Missing values remain null."""

    medicine_name: str | None = None
    strength: str | None = None
    dosage_form: str | None = None
    quantity: int | None = None
    pack_size: int | None = None
    unit: str | None = None
    cold_chain_required: bool | None = None
    destination: str | None = None
    required_delivery_date: date | None = None
    max_lead_time_days: int | None = None
    currency: str | None = None


class LLMProvider(ABC):
    name: str

    def __init__(self) -> None:
        self._usage: ContextVar[ProviderUsage | None] = ContextVar(f"{self.name}_provider_usage", default=None)

    def begin_execution(self) -> None:
        self._usage.set(ProviderUsage())

    def record_usage(self, input_tokens: int | None, output_tokens: int | None) -> None:
        current = self._usage.get() or ProviderUsage()
        self._usage.set(
            ProviderUsage(
                input_tokens=current.input_tokens + max(input_tokens or 0, 0),
                output_tokens=current.output_tokens + max(output_tokens or 0, 0),
            )
        )

    @property
    def usage(self) -> ProviderUsage:
        return self._usage.get() or ProviderUsage()

    async def close(self) -> None:
        return None

    async def interpret(self, text: str, previous: ProcurementRequest | None = None) -> ProviderInterpretation:
        """Interpret intent and select tools, allowing providers to combine both operations."""
        request = await self.extract(text, previous)
        tool_plan = [] if request.missing_fields() else await self.select_tools(request)
        return ProviderInterpretation(request=request, tool_plan=tool_plan)

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
    for key in ("destination", "required_delivery_date", "max_lead_time_days", "currency", "buyer_notes"):
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
        super().__init__()
        self.client, self.model, self.policy = AsyncOpenAI(api_key=api_key), model, policy

    async def extract(self, text: str, previous: ProcurementRequest | None = None) -> ProcurementRequest:
        schema = ProcurementRequest.model_json_schema()
        prompt = f"{self.policy}\nExtract only stated procurement facts. Previous draft: {previous.model_dump_json() if previous else 'none'}"
        for attempt in range(2):
            try:
                result = await self.client.responses.create(model=self.model, instructions=prompt, input=text, text={"format": {"type": "json_schema", "name": "procurement_request", "schema": schema, "strict": True}})
                self.record_usage(getattr(result.usage, "input_tokens", None), getattr(result.usage, "output_tokens", None))
                return ProcurementRequest.model_validate(json.loads(result.output_text))
            except Exception as exc:
                if attempt == 1:
                    raise InvalidModelOutputError("Provider returned invalid structured output") from exc
        raise InvalidModelOutputError("Unreachable")

    async def select_tools(self, request: ProcurementRequest) -> list[str]:
        tools = [{"type": "function", "name": name, "description": f"Required deterministic procurement step: {name}", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}, "strict": True} for name in REQUIRED_TOOL_PLAN]
        result = await self.client.responses.create(model=self.model, input=f"Select every deterministic tool required to evaluate this complete request: {request.model_dump_json()}", tools=tools, tool_choice="required", parallel_tool_calls=False)
        self.record_usage(getattr(result.usage, "input_tokens", None), getattr(result.usage, "output_tokens", None))
        selected = [item.name for item in result.output if getattr(item, "type", None) == "function_call"]
        if selected != REQUIRED_TOOL_PLAN:
            raise InvalidModelOutputError("Hosted provider did not return the required safe tool sequence")
        return selected

    async def close(self) -> None:
        await self.client.close()


class GeminiProvider(LLMProvider):
    """Gemini interprets intent and authorizes, but never executes, business tools."""

    name = "gemini"
    _evaluation_function = "authorize_procurement_evaluation"
    _interpretation_function = "interpret_procurement_request"

    def __init__(self, api_key: str, model: str, policy: str, client: Any | None = None, timeout_seconds: int = 30):
        super().__init__()
        self.model = model
        self.policy = policy
        self.client = client if client is not None else (
            genai.Client(
                api_key=api_key,
                http_options=genai_types.HttpOptions(timeout=max(timeout_seconds, 1) * 1000),
            ).aio
            if api_key
            else None
        )

    def _require_client(self) -> Any:
        if self.client is None:
            raise ProviderUnavailableError("Gemini is selected but its API key is not configured")
        return self.client

    def _record_response_usage(self, response: Any) -> None:
        usage = getattr(response, "usage_metadata", None)
        self.record_usage(
            getattr(usage, "prompt_token_count", None),
            getattr(usage, "candidates_token_count", None),
        )

    async def _generate(self, contents: str, config: genai_types.GenerateContentConfig) -> Any:
        chat = self._require_client().chats.create(model=self.model, config=config)
        return await chat.send_message(contents)

    async def interpret(self, text: str, previous: ProcurementRequest | None = None) -> ProviderInterpretation:
        """Extract buyer intent and authorize the fixed evaluation in one Gemini round trip."""
        self._require_client()
        previous_context = previous.model_dump_json() if previous else "none"
        declaration = genai_types.FunctionDeclaration(
            name=self._interpretation_function,
            description=(
                "Extract only procurement facts explicitly stated in the buyer's current message. Calling this "
                "function authorizes Procura to apply its fixed deterministic supplier checks when the resulting "
                "request is complete. It does not calculate prices, establish supplier facts, or place an order."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "medicine_name": {"type": "string"},
                    "strength": {"type": "string"},
                    "dosage_form": {"type": "string"},
                    "quantity": {"type": "integer"},
                    "pack_size": {"type": "integer"},
                    "unit": {"type": "string"},
                    "cold_chain_required": {"type": "boolean"},
                    "destination": {"type": "string"},
                    "required_delivery_date": {"type": "string", "description": "ISO 8601 date"},
                    "max_lead_time_days": {"type": "integer"},
                    "currency": {"type": "string"},
                },
                "additionalProperties": False,
            },
        )
        instruction = (
            f"{self.policy}\n\n"
            "Interpret buyer intent only. Omit every field not explicitly stated in the current message. "
            "Do not infer supplier, price, inventory, authorization, compliance, or missing procurement facts. "
            "The application merges these facts with the previous draft and checks completeness deterministically. "
            f"Previous draft for conversational context only: {previous_context}"
        )
        tool = genai_types.Tool(function_declarations=[declaration])
        for attempt in range(2):
            try:
                response = await self._generate(
                    text,
                    genai_types.GenerateContentConfig(
                        system_instruction=instruction,
                        temperature=0,
                        tools=[tool],
                        tool_config=genai_types.ToolConfig(
                            function_calling_config=genai_types.FunctionCallingConfig(mode="ANY")
                        ),
                    ),
                )
                self._record_response_usage(response)
            except genai_errors.APIError as exc:
                raise ProviderUnavailableError("Gemini request failed") from exc
            except Exception as exc:
                raise ProviderUnavailableError("Gemini request failed") from exc
            try:
                calls = response.function_calls or []
                if len(calls) != 1 or calls[0].name != self._interpretation_function:
                    raise ValueError("Unexpected Gemini function call")
                extraction = ProcurementExtraction.model_validate(dict(calls[0].args or {}))
                values = extraction.model_dump()
                values["buyer_notes"] = text[:500]
                request = _merge(previous, values)
                return ProviderInterpretation(request=request, tool_plan=REQUIRED_TOOL_PLAN.copy())
            except (ValidationError, TypeError, ValueError, AttributeError) as exc:
                if attempt == 1:
                    raise InvalidModelOutputError(
                        "Gemini returned an invalid procurement function call after one retry"
                    ) from exc
        raise InvalidModelOutputError("Unreachable")

    async def extract(self, text: str, previous: ProcurementRequest | None = None) -> ProcurementRequest:
        self._require_client()
        previous_context = previous.model_dump_json() if previous else "none"
        instruction = (
            f"{self.policy}\n\n"
            "You interpret buyer intent only. Extract facts explicitly stated in the current message. "
            "Do not infer missing medicine, strength, form, quantity, pack size, destination, delivery, currency, "
            "supplier, price, inventory, authorization, or compliance facts. Return null for facts not stated in "
            "the current message. The application merges this extraction with the previous draft deterministically. "
            f"Previous draft for conversational context only: {previous_context}"
        )
        for attempt in range(2):
            try:
                response = await self._generate(
                    text,
                    genai_types.GenerateContentConfig(
                        system_instruction=instruction,
                        temperature=0,
                        response_mime_type="application/json",
                        response_schema=ProcurementExtraction,
                    ),
                )
                self._record_response_usage(response)
            except genai_errors.APIError as exc:
                raise ProviderUnavailableError("Gemini request failed") from exc
            except Exception as exc:  # transport and SDK failures are availability failures
                raise ProviderUnavailableError("Gemini request failed") from exc
            try:
                parsed = response.parsed
                extraction = parsed if isinstance(parsed, ProcurementExtraction) else ProcurementExtraction.model_validate(parsed or json.loads(response.text))
                values = extraction.model_dump()
                values["buyer_notes"] = text[:500]
                return _merge(previous, values)
            except (ValidationError, json.JSONDecodeError, TypeError, ValueError, AttributeError) as exc:
                if attempt == 1:
                    raise InvalidModelOutputError("Gemini returned invalid structured output after one retry") from exc
        raise InvalidModelOutputError("Unreachable")

    async def select_tools(self, request: ProcurementRequest) -> list[str]:
        self._require_client()
        declaration = genai_types.FunctionDeclaration(
            name=self._evaluation_function,
            description=(
                "Authorize Procura to run its fixed deterministic supplier search, price comparison, authorization, "
                "destination, cold-chain, unit, deadline, and ranking checks. This function does not place an order."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {"request_id": {"type": "string", "description": "The supplied procurement request ID"}},
                "required": ["request_id"],
                "additionalProperties": False,
            },
        )
        tool = genai_types.Tool(function_declarations=[declaration])
        for attempt in range(2):
            try:
                response = await self._generate(
                    (
                        "Authorize the fixed deterministic evaluation for this complete procurement request. "
                        "Do not calculate prices or make supplier claims. "
                        f"Request ID: {request.id}"
                    ),
                    genai_types.GenerateContentConfig(
                        system_instruction=self.policy,
                        temperature=0,
                        tools=[tool],
                        tool_config=genai_types.ToolConfig(
                            function_calling_config=genai_types.FunctionCallingConfig(mode="ANY")
                        ),
                    ),
                )
                self._record_response_usage(response)
            except genai_errors.APIError as exc:
                raise ProviderUnavailableError("Gemini tool-selection request failed") from exc
            except Exception as exc:
                raise ProviderUnavailableError("Gemini tool-selection request failed") from exc
            calls = response.function_calls or []
            valid = (
                len(calls) == 1
                and calls[0].name == self._evaluation_function
                and dict(calls[0].args or {}).get("request_id") == request.id
            )
            if valid:
                return REQUIRED_TOOL_PLAN.copy()
            if attempt == 1:
                raise InvalidModelOutputError("Gemini did not authorize the required safe tool sequence after one retry")
        raise InvalidModelOutputError("Unreachable")

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()
