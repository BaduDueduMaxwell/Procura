import pytest
from app.agent.providers import DeterministicLLMProvider
from app.observability.adapters import sanitize


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
