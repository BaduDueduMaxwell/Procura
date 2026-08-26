from types import SimpleNamespace

import pytest
from app.agent.providers import (
    REQUIRED_TOOL_PLAN,
    DeterministicLLMProvider,
    GeminiProvider,
    ProcurementExtraction,
)
from app.config import Settings
from app.domain.errors import InvalidModelOutputError, ProviderUnavailableError
from app.domain.models import ProcurementRequest
from app.observability.adapters import sanitize
from app.services.agent_service import build_provider


class FakeGeminiChat:
    def __init__(self, responses):
        self.responses = responses

    async def send_message(self, message):
        return self.responses.pop(0)


class FakeGeminiChats:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeGeminiChat(self.responses)


class FakeGeminiClient:
    def __init__(self, responses):
        self.chats = FakeGeminiChats(responses)


def gemini_response(*, parsed=None, text=None, calls=None, input_tokens=0, output_tokens=0):
    return SimpleNamespace(
        parsed=parsed,
        text=text,
        function_calls=calls or [],
        usage_metadata=SimpleNamespace(
            prompt_token_count=input_tokens,
            candidates_token_count=output_tokens,
        ),
    )


@pytest.mark.asyncio
async def test_demo_provider_is_predictable():
    provider = DeterministicLLMProvider()
    req = await provider.extract("2,000 packs of amoxicillin 500 mg capsules, pack size 100, to Accra within 21 days in USD")
    assert req.medicine.quantity == 2000 and req.medicine.pack_size == 100 and req.destination == "Ghana"
    assert (await provider.select_tools(req))[0] == "search_synthetic_suppliers"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "medicine", "strength", "form"),
    [
        ("5,000 packs of paracetamol 500 mg tablets, pack size 100, to Accra within 18 days in USD", "paracetamol", "500 mg", "tablet"),
        ("300 packs of insulin 100 units/ml vials, pack size 10, cold chain, to Ghana within 21 days in USD", "insulin", "100 units/ml", "vial"),
        ("500 packs of ceftriaxone 1 g vials, pack size 10, to Nairobi within 25 days in USD", "ceftriaxone", "1 g", "vial"),
        ("800 packs of artemether-lumefantrine 20/120 mg tablets, pack size 24, to Accra within 18 days in USD", "artemether-lumefantrine", "20/120 mg", "tablet"),
        ("1,000 packs of oral rehydration salts 20.5 g sachets, pack size 20, to Ghana within 14 days in USD", "oral rehydration salts", "20.5 g", "sachet"),
    ],
)
async def test_local_provider_extracts_multiple_medicines(text, medicine, strength, form):
    request = await DeterministicLLMProvider().extract(text)
    assert (request.medicine.medicine_name, request.medicine.strength, request.medicine.dosage_form) == (medicine, strength, form)


@pytest.mark.asyncio
async def test_gemini_provider_extracts_structured_facts_and_records_usage():
    response = gemini_response(
        parsed=ProcurementExtraction(
            medicine_name="omeprazole",
            strength="20 mg",
            dosage_form="capsule",
            quantity=600,
            pack_size=28,
            destination="Ghana",
            max_lead_time_days=18,
            currency="USD",
        ),
        input_tokens=240,
        output_tokens=80,
    )
    client = FakeGeminiClient([response])
    provider = GeminiProvider("unused", "gemini-test", "policy", client=client)
    provider.begin_execution()

    request = await provider.extract("600 packs of omeprazole 20 mg capsules, pack size 28, to Ghana within 18 days in USD")

    assert request.medicine.medicine_name == "omeprazole"
    assert request.medicine.quantity == 600
    assert request.destination == "Ghana"
    assert provider.usage.input_tokens == 240
    assert provider.usage.output_tokens == 80
    config = client.chats.calls[0]["config"]
    assert config.response_schema is ProcurementExtraction
    assert config.temperature == 0


@pytest.mark.asyncio
async def test_gemini_interprets_complete_request_and_authorizes_tools_in_one_call():
    call = SimpleNamespace(
        name="interpret_procurement_request",
        args={
            "medicine_name": "omeprazole",
            "strength": "20 mg",
            "dosage_form": "capsule",
            "quantity": 600,
            "pack_size": 28,
            "destination": "Accra",
            "max_lead_time_days": 18,
            "currency": "USD",
        },
    )
    client = FakeGeminiClient([gemini_response(calls=[call], input_tokens=510, output_tokens=74)])
    provider = GeminiProvider("unused", "gemini-test", "policy", client=client)
    provider.begin_execution()

    result = await provider.interpret(
        "600 packs of omeprazole 20 mg capsules, pack size 28, to Accra within 18 days in USD"
    )

    assert len(client.chats.calls) == 1
    assert result.request.medicine.medicine_name == "omeprazole"
    assert result.request.medicine.quantity == 600
    assert result.request.destination == "Accra"
    assert result.tool_plan == REQUIRED_TOOL_PLAN
    assert provider.usage == provider.usage.__class__(input_tokens=510, output_tokens=74)
    config = client.chats.calls[0]["config"]
    assert config.response_schema is None
    assert config.tools[0].function_declarations[0].name == "interpret_procurement_request"


@pytest.mark.asyncio
async def test_gemini_single_call_retries_invalid_function_output_once():
    wrong = SimpleNamespace(name="place_order", args={})
    valid = SimpleNamespace(name="interpret_procurement_request", args={"medicine_name": "omeprazole"})
    client = FakeGeminiClient([gemini_response(calls=[wrong]), gemini_response(calls=[valid])])
    provider = GeminiProvider("unused", "gemini-test", "policy", client=client)

    result = await provider.interpret("omeprazole")

    assert len(client.chats.calls) == 2
    assert result.request.medicine.medicine_name == "omeprazole"


def test_gemini_extraction_schema_uses_only_supported_integer_keywords():
    schema = ProcurementExtraction.model_json_schema()

    for field in ("quantity", "pack_size", "max_lead_time_days"):
        variants = schema["properties"][field]["anyOf"]
        integer_schema = next(variant for variant in variants if variant.get("type") == "integer")
        assert "exclusiveMinimum" not in integer_schema


@pytest.mark.asyncio
async def test_gemini_provider_merges_one_field_follow_up_without_inventing_others():
    previous = ProcurementRequest.model_validate(
        {
            "medicine": {"medicine_name": "omeprazole", "strength": "20 mg"},
            "destination": "Ghana",
        }
    )
    provider = GeminiProvider(
        "unused",
        "gemini-test",
        "policy",
        client=FakeGeminiClient([gemini_response(parsed=ProcurementExtraction(quantity=600))]),
    )

    request = await provider.extract("600 packs", previous)

    assert request.medicine.medicine_name == "omeprazole"
    assert request.medicine.strength == "20 mg"
    assert request.medicine.quantity == 600
    assert request.destination == "Ghana"


@pytest.mark.asyncio
async def test_gemini_invalid_structured_output_retries_once_then_fails_safe():
    client = FakeGeminiClient(
        [
            gemini_response(text="not-json", input_tokens=10),
            gemini_response(text="still-not-json", input_tokens=11),
        ]
    )
    provider = GeminiProvider("unused", "gemini-test", "policy", client=client)

    with pytest.raises(InvalidModelOutputError, match="after one retry"):
        await provider.extract("incomplete request")

    assert len(client.chats.calls) == 2
    assert provider.usage.input_tokens == 21


@pytest.mark.asyncio
async def test_gemini_requires_a_key_without_exposing_it():
    provider = GeminiProvider("", "gemini-test", "policy")

    with pytest.raises(ProviderUnavailableError, match="not configured"):
        await provider.extract("request")


@pytest.mark.asyncio
async def test_gemini_function_call_authorizes_only_the_fixed_tool_plan():
    request = ProcurementRequest(medicine={})
    call = SimpleNamespace(name="authorize_procurement_evaluation", args={"request_id": request.id})
    client = FakeGeminiClient([gemini_response(calls=[call], input_tokens=30, output_tokens=8)])
    provider = GeminiProvider("unused", "gemini-test", "policy", client=client)

    selected = await provider.select_tools(request)

    assert selected == REQUIRED_TOOL_PLAN
    assert provider.usage == provider.usage.__class__(input_tokens=30, output_tokens=8)
    config = client.chats.calls[0]["config"]
    assert config.automatic_function_calling is None


@pytest.mark.asyncio
async def test_gemini_rejects_an_unexpected_function_call_after_one_retry():
    wrong = SimpleNamespace(name="place_order", args={})
    client = FakeGeminiClient([gemini_response(calls=[wrong]), gemini_response(calls=[wrong])])
    provider = GeminiProvider("unused", "gemini-test", "policy", client=client)

    with pytest.raises(InvalidModelOutputError, match="safe tool sequence"):
        await provider.select_tools(ProcurementRequest(medicine={}))

    assert len(client.chats.calls) == 2


@pytest.mark.asyncio
async def test_provider_selection_accepts_case_insensitive_gemini_configuration():
    settings = Settings(
        _env_file=None,
        llm_provider="Gemini",
        llm_model="gemini-test",
        llm_api_key="test-key",
    )

    provider = build_provider(settings, "policy")

    assert isinstance(provider, GeminiProvider)
    await provider.client.aclose()


def test_redaction():
    result = sanitize("mail a@b.com bearer abc.xyz API_KEY=secret123 +233 20 123 4567")
    assert "a@b.com" not in result and "abc.xyz" not in result and "secret123" not in result and "233 20" not in result


def test_policy_loaded():
    from app.main import policy
    assert "procura-policy-v1" in policy and "not legal or regulatory advice" in policy


def test_policy_path_falls_back_safely_in_shallow_container_path():
    from pathlib import Path

    from app.config import find_policy_path

    assert find_policy_path(Path("/app/app/config.py")) == Path("/knowledge/PROCUREMENT_POLICY.md")
