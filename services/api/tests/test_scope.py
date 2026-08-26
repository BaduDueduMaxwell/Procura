from app.domain.models import ProcurementRequest
from app.services.scope import is_procurement_message, scope_redirect


def partial_request() -> ProcurementRequest:
    return ProcurementRequest(
        medicine={
            "medicine_name": "amlodipine",
            "strength": "5 mg",
            "dosage_form": "tablet",
            "pack_size": 30,
        },
        currency="USD",
    )


def test_scope_accepts_procurement_requests_and_structured_answers():
    assert is_procurement_message("Compare 600 packs of fluconazole 150 mg capsules")
    assert is_procurement_message("600 packs", partial_request())
    assert is_procurement_message("Please compare supplier quotations")


def test_scope_rejects_small_talk_even_during_clarification():
    request = partial_request()
    assert not is_procurement_message("how are you", request)
    assert not is_procurement_message("tell me a joke", request)
    assert not is_procurement_message("write a poem about logistics", request)
    assert not is_procurement_message("explain quantum computing", request)
    assert not is_procurement_message("what is the weather in Accra", request)
    assert scope_redirect(request) == "Procura handles medicine procurement only. To continue this request, what quantity should I use?"


def test_scope_only_accepts_a_follow_up_that_matches_the_requested_field():
    quantity_request = partial_request()
    assert is_procurement_message("600 packs", quantity_request)
    assert not is_procurement_message("Accra", quantity_request)

    destination_request = quantity_request.model_copy(deep=True)
    destination_request.medicine.quantity = 600
    assert is_procurement_message("Accra, Ghana", destination_request)
    assert not is_procurement_message("compose a short song", destination_request)
