from io import BytesIO

from app.models.database import ProcurementIntakeRow, ReviewRow, SessionLocal
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import func, select


def login_buyer(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": "buyer@procura.example", "password": "Procura-Buyer-2026!"},
    )
    assert response.status_code == 200


def text_intake(client: TestClient, content: str, key: str = "intake-text-001"):
    login_buyer(client)
    return client.post("/api/intakes/text", json={"content": content, "idempotency_key": key})


def workbook_bytes(*sheets: tuple[str, list[list[object]]]) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, rows in sheets:
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_complete_text_intake_runs_langgraph_and_is_ready(client):
    response = text_intake(
        client,
        "We need 600 packs of omeprazole 20 mg capsules, pack size 28, delivered to Accra within 18 days, priced in USD.",
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "ready"
    assert body["lines"][0]["medicine_name"] == "omeprazole"
    assert body["lines"][0]["destination"] == "Ghana"
    assert body["graph_path"] == [
        "ingest_input", "normalize_products", "match_catalogue", "validate_rows",
        "classify_findings", "ready_for_submission",
    ]


def test_misspelling_is_buyer_suggestion_not_staff_review(client):
    response = text_intake(
        client,
        "We need 600 packs of ameprazole 20 mg capsules, pack size 28, delivered to Accra within 18 days, priced in USD.",
        "intake-misspelling-001",
    )
    assert response.status_code == 201, response.text
    body = response.json()
    line = body["lines"][0]
    assert body["status"] == "suggestion_available"
    assert line["medicine_name"] == "ameprazole"
    assert line["suggestion"]["suggested_value"] == "omeprazole"
    assert line["suggestion"]["confirmation_required"] is True
    with SessionLocal() as db:
        assert (db.scalar(select(func.count()).select_from(ReviewRow)) or 0) == 0

    accepted = client.post(
        f"/api/intakes/{body['id']}/lines/{line['id']}/suggestion",
        json={"action": "accept", "version": body["version"], "idempotency_key": "accept-spelling-001"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "ready"
    assert accepted.json()["lines"][0]["suggestion"]["status"] == "accepted"


def test_missing_fields_return_buyer_checklist_and_changed_row_revalidates(client):
    response = text_intake(client, "We need omeprazole 20 mg capsules, pack size 28.", "intake-missing-001")
    body = response.json()
    assert body["status"] == "needs_correction"
    codes = {item["code"] for item in body["lines"][0]["findings"]}
    assert {"missing_quantity", "missing_unit", "missing_destination", "missing_max_lead_time_days", "missing_currency"} <= codes
    patched = client.patch(
        f"/api/intakes/{body['id']}/lines/{body['lines'][0]['id']}",
        json={
            "quantity": 600, "unit": "packs", "destination": "Ghana",
            "max_lead_time_days": 18, "currency": "USD", "version": body["version"],
            "idempotency_key": "correct-row-001",
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["status"] == "ready"
    assert "buyer_correction_resume" in patched.json()["graph_path"]
    assert set(patched.json()["lines"][0]["buyer_corrected_fields"]) == {
        "currency", "destination", "max_lead_time_days", "quantity", "unit",
    }


def test_csv_aliases_semicolon_empty_rows_and_duplicates(client):
    login_buyer(client)
    csv_data = (
        b"drug;concentration;formulation;requested quantity;units;pack;market;lead time;currency\n"
        b"omeprazole;20 mg;capsule;600;packs;28;Ghana;18;USD\n"
        b";;;;;;;;\n"
        b"omeprazole;20 mg;capsule;600;packs;28;Ghana;18;USD\n"
    )
    response = client.post(
        "/api/intakes/files",
        files={"file": ("requirements.csv", csv_data, "text/csv")},
        data={"idempotency_key": "csv-alias-001"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert len(body["lines"]) == 2
    assert all(any(item["code"] == "possible_duplicate" for item in line["findings"]) for line in body["lines"])


def test_xlsx_multiple_worksheets_are_parsed(client):
    login_buyer(client)
    header = ["medicine", "strength", "dosage form", "quantity", "units", "pack size", "destination", "lead time", "currency"]
    content = workbook_bytes(
        ("Essential", [header, ["omeprazole", "20 mg", "capsule", 600, "packs", 28, "Ghana", 18, "USD"]]),
        ("Other", [header, ["paracetamol", "500 mg", "tablet", 1500, "packs", 20, "Ghana", 18, "USD"]]),
    )
    response = client.post(
        "/api/intakes/files",
        files={"file": ("requirements.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"idempotency_key": "xlsx-sheets-001"},
    )
    assert response.status_code == 201, response.text
    assert {line["sheet_name"] for line in response.json()["lines"]} == {"Essential", "Other"}


def test_untrusted_files_fail_with_specific_messages(client):
    login_buyer(client)
    bad_type = client.post(
        "/api/intakes/files",
        files={"file": ("requirements.xlsx", b"not-an-xlsx", "text/csv")},
        data={"idempotency_key": "wrong-mime-001"},
    )
    assert bad_type.status_code == 422
    assert "content type" in bad_type.json()["detail"].lower()
    formula = client.post(
        "/api/intakes/files",
        files={"file": ("requirements.csv", b"medicine,quantity\n=HYPERLINK(\"x\"),1\n", "text/csv")},
        data={"idempotency_key": "formula-001"},
    )
    assert formula.status_code == 422
    assert "formula" in formula.json()["detail"].lower()


def test_tenant_isolation_version_conflict_and_idempotent_submission(client):
    first = text_intake(
        client,
        "We need 600 packs of omeprazole 20 mg capsules, pack size 28, delivered to Accra within 18 days in USD.",
        "tenant-intake-001",
    ).json()
    submitted = client.post(
        f"/api/intakes/{first['id']}/submit",
        json={"version": first["version"], "idempotency_key": "submit-intake-001"},
    )
    assert submitted.status_code == 200
    repeat = client.post(
        f"/api/intakes/{first['id']}/submit",
        json={"version": first["version"], "idempotency_key": "submit-intake-001"},
    )
    assert repeat.status_code == 200
    assert repeat.json()["version"] == submitted.json()["version"]
    stale = client.patch(
        f"/api/intakes/{first['id']}/lines/{first['lines'][0]['id']}",
        json={"quantity": 700, "version": first["version"], "idempotency_key": "stale-edit-001"},
    )
    assert stale.status_code == 409

    client.post("/api/auth/logout")
    signup = client.post("/api/auth/signup", json={
        "email": "other-buyer@example.com", "display_name": "Other Buyer", "organization": "Other Org",
        "password": "Safe-password-2026!", "account_type": "buyer",
    })
    assert signup.status_code == 201
    assert client.get(f"/api/intakes/{first['id']}").status_code == 404


def test_submission_creates_review_only_when_no_supplier_is_eligible(client):
    intake = text_intake(
        client,
        "We need 600 packs of omeprazole 20 mg capsules, pack size 28, delivered to Nigeria within 18 days in USD.",
        "critical-intake-001",
    ).json()
    assert intake["status"] == "ready"

    response = client.post(
        f"/api/intakes/{intake['id']}/submit",
        json={"version": intake["version"], "idempotency_key": "critical-submit-001"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "critical_review_required"
    assert body["lines"][0]["status"] == "critical_review_required"
    assert body["lines"][0]["findings"][-1]["code"] == "no_eligible_quotation"
    assert "Destination not supported" in body["lines"][0]["findings"][-1]["message"]
    repeated = client.post(
        f"/api/intakes/{intake['id']}/submit",
        json={"version": intake["version"], "idempotency_key": "critical-submit-001"},
    )
    assert repeated.status_code == 200
    assert repeated.json()["version"] == body["version"]
    with SessionLocal() as db:
        assert db.get(ReviewRow, f"intake-review-{body['id']}-{body['lines'][0]['id']}") is not None


def test_irrelevant_input_does_not_create_intake_or_review(client):
    response = text_intake(client, "How are you doing today?", "irrelevant-intake-001")
    assert response.status_code == 422
    with SessionLocal() as db:
        assert (db.scalar(select(func.count()).select_from(ProcurementIntakeRow)) or 0) == 0
        assert (db.scalar(select(func.count()).select_from(ReviewRow)) or 0) == 0
