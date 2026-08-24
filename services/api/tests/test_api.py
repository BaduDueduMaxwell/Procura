def authenticate(client):
    if client.get("/api/auth/me").status_code == 200: return
    response = client.post("/api/auth/signup", json={"email":"buyer@example.com","display_name":"Procurement Buyer","organization":"Test Procurement","password":"A-secure-password-2026!"})
    assert response.status_code == 201


def login_reviewer(client):
    client.post("/api/auth/logout")
    response = client.post("/api/auth/login", json={"email":"reviewer@procura.example","password":"Procura-Reviewer-2026!"})
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


def test_clarification_is_business_response(client):
    cid = new_conversation(client)
    body = client.post(f"/api/conversations/{cid}/messages", json={"content":"We need amoxicillin", "idempotency_key":"clarify-01"}).json()
    assert body["decision"]["status"] == "clarification" and body["message"]["content"].startswith("What")


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
    login_reviewer(client)
    body=client.post("/api/dev/simulate-tool-timeout").json(); assert body["decision"]["status"]=="failed_safe"
    assert client.get(f"/api/traces/{body['decision']['trace_id']}").status_code==200


def test_operations_are_measured(client):
    login_reviewer(client)
    assert client.get("/api/operations/summary").json()["request_count"]==0
    test_health_and_happy_path(client)
    data=client.get("/api/operations/summary").json(); assert data["request_count"]==1 and data["p50_latency_ms"] is None


def test_signup_session_logout_and_role_boundary(client):
    assert client.get("/api/auth/me").status_code == 401
    authenticate(client)
    assert client.get("/api/auth/me").json()["role"] == "buyer"
    assert client.get("/api/reviews").status_code == 403
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


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
    assert client.get("/api/dashboard/summary").status_code == 403
    assert client.post("/api/conversations").status_code == 403
