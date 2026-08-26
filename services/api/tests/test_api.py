from uuid import UUID

from app.agent.providers import (
    REQUIRED_TOOL_PLAN,
    DeterministicLLMProvider,
    GeminiProvider,
    ProviderInterpretation,
)
from app.domain.models import ProcurementRequest
from app.main import service
from app.models.database import ResourceOwnerRow, SessionLocal
from sqlalchemy import select


def authenticate(client):
    if client.get("/api/auth/me").status_code == 200: return
    response = client.post("/api/auth/signup", json={"email":"buyer@example.com","display_name":"Procurement Buyer","organization":"Test Procurement","password":"A-secure-password-2026!"})
    assert response.status_code == 201


def login_reviewer(client):
    client.post("/api/auth/logout")
    response = client.post("/api/auth/login", json={"email":"reviewer@procura.example","password":"Procura-Reviewer-2026!"})
    assert response.status_code == 200


def login_admin(client):
    client.post("/api/auth/logout")
    response = client.post("/api/auth/login", json={"email":"operations@procura.example","password":"Procura-Admin-2026!"})
    assert response.status_code == 200


def login_seeded_buyer(client):
    client.post("/api/auth/logout")
    response = client.post("/api/auth/login", json={"email":"buyer@procura.example","password":"Procura-Buyer-2026!"})
    assert response.status_code == 200


def login_supplier(client):
    client.post("/api/auth/logout")
    response = client.post("/api/auth/login", json={"email":"supplier@procura.example","password":"Procura-Supplier-2026!"})
    assert response.status_code == 200


def new_conversation(client):
    authenticate(client)
    return client.post("/api/conversations").json()["id"]


def test_health_and_happy_path(client):
    assert client.get("/health").json()["provider"] == "local"
    cid = new_conversation(client)
    payload = {"content":"2,000 packs of amoxicillin 500 mg capsules, pack size 100, to Accra within 21 days in USD", "idempotency_key":"happy-001"}
    response = client.post(f"/api/conversations/{cid}/messages", json=payload)
    assert response.status_code == 200
    body = response.json(); assert body["decision"]["status"] == "recommended" and body["decision"]["recommendation_supplier_id"] == "northstar"
    assert body["decision"]["no_transaction_completed"]


def test_custom_quantity_uses_availability_and_requested_total(client):
    cid = new_conversation(client)
    payload = {"content":"1,500 packs of paracetamol 500 mg tablets, pack size 20, to Accra within 18 days in USD", "idempotency_key":"capacity-001"}
    body = client.post(f"/api/conversations/{cid}/messages", json=payload).json()
    assert body["decision"]["status"] == "recommended"
    assert body["decision"]["recommendation_supplier_id"] == "northstar"
    northstar = next(quote for quote in body["quotes"] if quote["supplier_id"] == "northstar")
    assert northstar["total_price"] == 690.0
    assert northstar["supplier_display_name"] == "Northstar Health Supply"
    assert northstar["requested_quantity_packs"] == 1500
    assert northstar["available_quantity_packs"] == 5000


def test_agent_service_uses_provider_single_call_interpretation(client):
    class SingleCallProvider(DeterministicLLMProvider):
        calls = 0

        async def interpret(self, text, previous=None):
            self.calls += 1
            return ProviderInterpretation(
                request=ProcurementRequest.model_validate(
                    {
                        "medicine": {
                            "medicine_name": "omeprazole",
                            "strength": "20 mg",
                            "dosage_form": "capsule",
                            "quantity": 600,
                            "pack_size": 28,
                            "unit": "pack",
                        },
                        "destination": "Accra",
                        "max_lead_time_days": 18,
                        "currency": "USD",
                    }
                ),
                tool_plan=REQUIRED_TOOL_PLAN.copy(),
            )

        async def extract(self, text, previous=None):
            raise AssertionError("AgentService must not make a separate extraction call")

        async def select_tools(self, request):
            raise AssertionError("AgentService must not make a separate tool-selection call")

    original_provider = service.provider
    single_call_provider = SingleCallProvider()
    service.provider = single_call_provider
    try:
        conversation_id = new_conversation(client)
        response = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "complete request", "idempotency_key": "single-provider-call-01"},
        )
    finally:
        service.provider = original_provider

    assert response.status_code == 200
    body = response.json()
    assert single_call_provider.calls == 1
    assert body["decision"]["status"] == "recommended"
    assert body["request"]["medicine"]["unit"] == "packs"


def test_clarification_is_business_response(client):
    cid = new_conversation(client)
    body = client.post(f"/api/conversations/{cid}/messages", json={"content":"We need amoxicillin", "idempotency_key":"clarify-01"}).json()
    assert body["decision"]["status"] == "clarification" and body["message"]["content"].startswith("What")


def test_partial_catalog_request_keeps_extracted_fields_and_asks_for_quantity(client):
    cid = new_conversation(client)
    body = client.post(
        f"/api/conversations/{cid}/messages",
        json={"content": "We need amlodipine 5 mg tablets, pack size 30 and price in USD", "idempotency_key": "partial-amlodipine-01"},
    ).json()
    assert body["decision"]["status"] == "clarification"
    assert body["decision"]["human_review_required"] is False
    assert body["message"]["content"] == "What quantity should I use?"
    assert body["request"]["medicine"]["medicine_name"] == "amlodipine"
    assert body["request"]["medicine"]["strength"] == "5 mg"
    assert body["request"]["medicine"]["dosage_form"] == "tablet"
    assert body["request"]["medicine"]["pack_size"] == 30
    assert body["request"]["currency"] == "USD"


def test_customer_dashboard_ignores_empty_shells_and_counts_latest_request_state(client):
    login_seeded_buyer(client)
    cid = client.post("/api/conversations").json()["id"]
    empty = client.get("/api/dashboard/summary").json()
    assert empty["conversation_count"] == 0
    assert empty["execution_count"] == 0

    client.post(f"/api/conversations/{cid}/messages", json={"content": "We need amoxicillin", "idempotency_key": "dashboard-clarify-01"})
    clarification = client.get("/api/dashboard/summary").json()
    assert clarification["conversation_count"] == 1
    assert clarification["execution_count"] == 0
    assert len(clarification["recent_decisions"]) == 1

    client.post(f"/api/conversations/{cid}/messages", json={"content": "2,000 packs, 500 mg capsules, pack size 100, to Ghana within 21 days in USD", "idempotency_key": "dashboard-complete-01"})
    completed = client.get("/api/dashboard/summary").json()
    assert completed["conversation_count"] == 1
    assert completed["execution_count"] == 1
    assert completed["recommendation_count"] == 1
    assert len(completed["recent_decisions"]) == 1


def test_review_creation_and_idempotent_execution(client):
    cid = new_conversation(client); data={"content":"2,000 packs of amoxicillin 500 mg capsules, pack size 50, to Ghana within 21 days in USD", "idempotency_key":"review-001"}
    first=client.post(f"/api/conversations/{cid}/messages",json=data).json(); second=client.post(f"/api/conversations/{cid}/messages",json=data).json()
    assert first==second and first["decision"]["human_review_required"]
    login_reviewer(client); reviews=client.get("/api/reviews").json(); assert len(reviews)==1


def test_idempotent_reviewer_action(client):
    cid=new_conversation(client); client.post(f"/api/conversations/{cid}/messages",json={"content":"2,000 packs of amoxicillin 500 mg capsules, pack size 50, to Ghana within 21 days in USD", "idempotency_key":"review-002"})
    login_reviewer(client); rid=client.get("/api/reviews").json()[0]["id"]; action={"action":"reject","note":"Units cannot be reconciled","idempotency_key":"decision-01"}
    assert client.post(f"/api/reviews/{rid}/decision",json=action).json()["status"]=="rejected"
    assert client.post(f"/api/reviews/{rid}/decision",json=action).status_code==200


def test_timeout_fails_safe_with_trace(client):
    login_admin(client)
    body=client.post("/api/dev/simulate-tool-timeout").json(); assert body["decision"]["status"]=="failed_safe"
    assert body["decision"]["escalation_reasons"] == ["Supplier verification timed out before all eligibility checks completed."]
    assert "ToolTimeoutError" not in body["decision"]["summary"]
    assert client.get(f"/api/traces/{body['decision']['trace_id']}").status_code==200


def test_operations_are_measured(client):
    login_admin(client)
    assert client.get("/api/operations/summary").json()["request_count"]==0
    test_health_and_happy_path(client)
    data=client.get("/api/operations/summary").json(); assert data["request_count"]==1 and data["p50_latency_ms"] is None


def test_operations_aggregate_measured_provider_tokens(client):
    class MeasuredProvider(DeterministicLLMProvider):
        async def extract(self, text, previous=None):
            request = await super().extract(text, previous)
            self.record_usage(320, 90)
            return request

    original_provider = service.provider
    service.provider = MeasuredProvider()
    try:
        test_health_and_happy_path(client)
    finally:
        service.provider = original_provider

    login_admin(client)
    summary = client.get("/api/operations/summary").json()
    assert summary["token_usage"] == 410
    assert summary["estimated_cost_usd"] is None


def test_unavailable_gemini_fails_safe_and_creates_review(client):
    original_provider = service.provider
    service.provider = GeminiProvider("", "gemini-test", "policy")
    try:
        conversation_id = new_conversation(client)
        response = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "We need omeprazole", "idempotency_key": "gemini-unavailable-01"},
        )
    finally:
        service.provider = original_provider

    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["status"] == "failed_safe"
    assert body["decision"]["human_review_required"] is True
    assert body["decision"]["escalation_reasons"] == [
        "The request could not be interpreted reliably because the language provider was unavailable."
    ]
    login_reviewer(client)
    assert len(client.get("/api/reviews").json()) == 1


def test_signup_session_logout_and_role_boundary(client):
    assert client.get("/api/auth/me").status_code == 401
    authenticate(client)
    assert client.get("/api/auth/me").json()["role"] == "buyer"
    assert client.get("/api/reviews").status_code == 403
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_seeded_reviewer_and_admin_have_distinct_permissions(client):
    conversation_id = new_conversation(client)
    login_reviewer(client)
    assert client.get("/api/auth/me").json()["role"] == "reviewer"
    assert client.get("/api/reviews").status_code == 200
    assert client.get("/api/supplier-submissions").status_code == 200
    assert client.get("/api/operations/summary").status_code == 403
    assert client.post("/api/conversations").status_code == 403
    assert client.get(f"/api/conversations/{conversation_id}").status_code == 404

    login_admin(client)
    assert client.get("/api/auth/me").json()["role"] == "admin"
    assert client.get("/api/reviews").status_code == 200
    assert client.get("/api/supplier-submissions").status_code == 200
    assert client.get("/api/operations/summary").status_code == 200
    assert client.post("/api/conversations").status_code == 201
    assert client.get(f"/api/conversations/{conversation_id}").status_code == 200
    assert client.get("/api/supplier/dashboard").status_code == 403


def test_seeded_buyer_has_customer_only_permissions(client):
    login_seeded_buyer(client)
    assert client.get("/api/auth/me").json()["role"] == "buyer"
    assert client.get("/api/dashboard/summary").status_code == 200
    assert client.post("/api/conversations").status_code == 201
    assert client.get("/api/reviews").status_code == 403
    assert client.get("/api/operations/summary").status_code == 403
    assert client.get("/api/supplier/dashboard").status_code == 403


def test_buyer_catalog_is_built_from_current_quote_records(client):
    login_seeded_buyer(client)
    response = client.get("/api/catalog/medicines?q=paracetamol&limit=12")
    assert response.status_code == 200
    catalog = response.json()
    paracetamol = next(item for item in catalog if item["medicine_name"] == "paracetamol" and item["pack_size"] == 20)
    assert paracetamol["quotation_count"] == 2
    assert paracetamol["authorized_supplier_count"] == 1
    assert paracetamol["destinations"] == ["Ghana", "Kenya"]
    assert paracetamol["unit_price_from"] == 0.41
    assert paracetamol["request_starter"] == "We need paracetamol 500 mg tablets, pack size 20."


def test_buyer_catalog_search_is_server_side_and_bounded(client):
    login_seeded_buyer(client)
    assert len(client.get("/api/catalog/medicines").json()) == 6
    response = client.get("/api/catalog/medicines?q=para&limit=1")
    assert response.status_code == 200
    catalog = response.json()
    assert len(catalog) == 1
    assert catalog[0]["medicine_name"] == "paracetamol"
    assert client.get("/api/catalog/medicines?limit=1000").status_code == 422
    assert len(client.get("/api/catalog/medicines?limit=20").json()) == 20


def test_all_twenty_seeded_medicines_are_searchable(client):
    from app.services.catalog_terms import CATALOG_MEDICINES

    login_seeded_buyer(client)
    for medicine in CATALOG_MEDICINES:
        response = client.get("/api/catalog/medicines", params={"q": medicine, "limit": 6})
        assert response.status_code == 200
        assert medicine in {item["medicine_name"] for item in response.json()}


def test_catalog_role_boundary_blocks_supplier_and_reviewer(client):
    login_supplier(client)
    assert client.get("/api/catalog/medicines").status_code == 403
    login_reviewer(client)
    assert client.get("/api/catalog/medicines").status_code == 403
    login_admin(client)
    assert client.get("/api/catalog/medicines").status_code == 200


def test_public_signup_cannot_assign_staff_roles(client):
    payload = {"email":"self-admin@example.com","display_name":"Self Admin","organization":"Test","password":"A-secure-password-2026!","account_type":"admin"}
    assert client.post("/api/auth/signup", json=payload).status_code == 422


def test_auth_rejects_weak_password_duplicate_and_bad_login(client):
    weak = client.post("/api/auth/signup", json={"email":"weak@example.com","display_name":"Weak User","organization":"Test","password":"passwordpassword"})
    assert weak.status_code == 422
    authenticate(client)
    duplicate = client.post("/api/auth/signup", json={"email":"BUYER@example.com","display_name":"Other User","organization":"Test","password":"A-secure-password-2026!"})
    assert duplicate.status_code == 409
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"email":"buyer@example.com","password":"wrong"}).json()["detail"] == "Invalid email or password"


def test_origin_and_cross_account_access_are_blocked(client):
    authenticate(client)
    conversation_id = client.post("/api/conversations").json()["id"]
    assert client.post("/api/conversations", headers={"Origin":"https://evil.example"}).status_code == 403
    client.post("/api/auth/logout")
    second = client.post("/api/auth/signup", json={"email":"second@example.com","display_name":"Second Buyer","organization":"Another Org","password":"A-second-password-2026!"})
    assert second.status_code == 201
    assert client.get(f"/api/conversations/{conversation_id}").status_code == 404


def test_xss_like_text_is_stored_as_plain_content(client):
    conversation_id = new_conversation(client)
    payload = '<img src=x onerror=alert(1)> amoxicillin'
    body = client.post(f"/api/conversations/{conversation_id}/messages", json={"content":payload,"idempotency_key":"xss-text-01"}).json()
    stored = client.get(f"/api/conversations/{conversation_id}").json()
    assert stored["messages"][0]["content"] == payload
    assert body["decision"]["status"] == "clarification"


def test_customer_and_supplier_dashboards_are_role_isolated(client):
    conversation_id = new_conversation(client)
    client.post(f"/api/conversations/{conversation_id}/messages", json={"content":"2,000 packs of amoxicillin 500 mg capsules, pack size 100, to Accra within 21 days in USD", "idempotency_key":"dashboard-01"})
    customer = client.get("/api/dashboard/summary")
    assert customer.status_code == 200 and customer.json()["execution_count"] == 1
    assert client.get("/api/supplier/dashboard").status_code == 403
    client.post("/api/auth/logout")
    login = client.post("/api/auth/login", json={"email":"supplier@procura.example","password":"Procura-Supplier-2026!"})
    assert login.status_code == 200 and login.json()["role"] == "supplier"
    supplier = client.get("/api/supplier/dashboard")
    assert supplier.status_code == 200 and supplier.json()["supplier"]["id"] == "northstar"
    with SessionLocal() as db:
        link = db.scalar(select(ResourceOwnerRow).where(ResourceOwnerRow.resource_type == "supplier_profile", ResourceOwnerRow.resource_id == "northstar"))
        assert link is not None and str(UUID(link.id)) == link.id
    assert client.get("/api/dashboard/summary").status_code == 403
    assert client.post("/api/conversations").status_code == 403


def test_supplier_quote_assistant_prepares_draft_without_submitting(client):
    login_supplier(client)
    before = client.get("/api/supplier/dashboard").json()["submissions"]
    response = client.post("/api/supplier/quote-drafts", json={"content":"Offer 4,000 packs of paracetamol 500 mg tablets, pack size 20, at USD 0.44 per pack, within 13 days."})
    assert response.status_code == 200
    draft = response.json()
    assert draft["ready_to_submit"] is True
    assert draft["medicine_name"] == "paracetamol"
    assert draft["available_quantity_packs"] == 4000
    assert draft["unit_price"] == 0.44
    assert draft["no_submission_created"] is True
    assert client.get("/api/supplier/dashboard").json()["submissions"] == before


def test_supplier_quote_assistant_lists_missing_fields_and_enforces_role(client):
    login_supplier(client)
    draft = client.post("/api/supplier/quote-drafts", json={"content":"Paracetamol 500 mg tablets"}).json()
    assert draft["ready_to_submit"] is False
    assert "unit_price" in draft["missing_fields"]
    login_seeded_buyer(client)
    assert client.post("/api/supplier/quote-drafts", json={"content":"Paracetamol 500 mg tablets"}).status_code == 403


def test_review_brief_is_grounded_and_does_not_decide_case(client):
    cid = new_conversation(client)
    client.post(f"/api/conversations/{cid}/messages", json={"content":"2,000 packs of amoxicillin 500 mg capsules, pack size 50, to Ghana within 21 days in USD", "idempotency_key":"brief-001"})
    login_reviewer(client)
    case = client.get("/api/reviews").json()[0]
    brief = client.get(f"/api/reviews/{case['id']}/brief")
    assert brief.status_code == 200
    body = brief.json()
    assert body["review_id"] == case["id"]
    assert body["human_decision_required"] is True
    assert body["suggested_action"] == "request_clarification"
    assert any("Escalation:" in point for point in body["evidence_points"])
    assert client.get(f"/api/reviews/{case['id']}").json()["status"] == "open"
    login_seeded_buyer(client)
    assert client.get(f"/api/reviews/{case['id']}/brief").status_code == 403


def test_supplier_onboarding_submission_and_staff_approval(client):
    signup = client.post("/api/auth/signup", json={"email":"new-supplier@example.com","display_name":"Supply Lead","organization":"Aster Medical Supply","password":"A-supplier-password-2026!","account_type":"supplier"})
    assert signup.status_code == 201 and signup.json()["role"] == "supplier"
    dashboard = client.get("/api/supplier/dashboard").json()
    assert dashboard["compliance_state"] == "missing" and dashboard["quote_count"] == 0

    profile = client.post("/api/supplier/submissions/profile", json={"display_name":"Aster Medical Supply","destinations":["ghana","kenya"],"cold_chain":True,"authorization_expiry":"2028-12-31","idempotency_key":"supplier-profile-01"})
    assert profile.status_code == 201 and profile.json()["status"] == "pending"
    quote = client.post("/api/supplier/submissions/quotes", json={"medicine_name":"Paracetamol","strength":"500 mg","dosage_form":"tablet","pack_size":20,"available_quantity_packs":4000,"unit_price":0.44,"currency":"usd","lead_time_days":13,"idempotency_key":"supplier-quote-01"})
    assert quote.status_code == 201 and quote.json()["status"] == "pending"
    assert client.post("/api/supplier/submissions/quotes", json={"medicine_name":"Paracetamol","strength":"500 mg","dosage_form":"tablet","pack_size":20,"available_quantity_packs":4000,"unit_price":0.44,"currency":"usd","lead_time_days":13,"idempotency_key":"supplier-quote-01"}).json()["id"] == quote.json()["id"]

    client.post("/api/auth/logout"); login_reviewer(client)
    submissions = client.get("/api/supplier-submissions").json()
    assert len(submissions) == 2
    for submission in submissions:
        decision = client.post(f"/api/supplier-submissions/{submission['id']}/decision", json={"action":"approve","note":"Evidence reviewed","idempotency_key":f"approve-{submission['id']}"})
        assert decision.status_code == 200 and decision.json()["status"] == "approved"

    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"email":"new-supplier@example.com","password":"A-supplier-password-2026!"}).status_code == 200
    dashboard = client.get("/api/supplier/dashboard").json()
    assert dashboard["compliance_state"] == "authorized"
    assert dashboard["quote_count"] == 1
    assert {item["status"] for item in dashboard["submissions"]} == {"approved"}
