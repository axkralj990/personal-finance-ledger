from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.database.models import (
    Account,
    ImportBatch,
    ImportBatchExecutionPlan,
    ImportExecutionPlanKind,
    ImportMappingSuggestionAttempt,
    ImportMappingTemplate,
    ImportMappingTemplateOrigin,
    ImportMappingTemplateVersion,
)
from backend.app.imports.lifecycle import UniversalImportService
from backend.app.imports.models import UniversalMappingSpec
from backend.app.imports.openai_mapping import (
    MappingAuditMetadata,
    MappingFallbackCode,
    MappingFallbackError,
    MappingSuggestionFallback,
    MappingSuggestionSuccess,
)


def _account(app) -> Account:
    with app.state.database.session() as session:
        account = session.scalar(select(Account).where(Account.is_active.is_(True)))
        session.expunge(account)
        return account


def _upload(client: TestClient, account_id: str, content: str, filename: str = "source.csv"):
    return client.post(
        "/api/v1/imports",
        data={"account_id": account_id},
        files={"file": (filename, content.encode())},
    )


def _inspect(client: TestClient, batch_id: str) -> dict:
    response = client.get(f"/api/v1/imports/{batch_id}/inspection")
    assert response.status_code == 200
    return response.json()


def test_universal_upload_preview_template_confirm_and_stage(app, client: TestClient) -> None:
    account = _account(app)
    content = (
        "Date,Description,Amount,Currency\n"
        "2026-08-01,Coffee,-4.50,EUR\n"
        "2026-08-02,Salary,100.00,EUR\n"
    )
    created = _upload(client, account.id, content)
    assert created.status_code == 201
    batch = created.json()
    assert batch["account_id"] == account.id

    duplicate = _upload(client, account.id, content, "renamed.csv")
    assert duplicate.status_code == 200
    assert duplicate.headers["x-existing-import-draft"] == "true"

    inspected = _inspect(client, batch["id"])
    assert set(inspected["proposals"]) == {"templates", "universal"}
    plan = inspected["proposals"]["universal"]
    assert plan["plan_type"] == "universal"
    assert plan["schema_version"] == "universal-v1"
    assert plan["transaction_date"]["format"] == "%Y-%m-%d"
    assert plan["amount"]["expense_sign_convention"] == "EXPENSES_NEGATIVE"

    preview = client.post(
        f"/api/v1/imports/{batch['id']}/mapping-preview",
        json={"execution_plan": plan, "offset": 0, "limit": 10},
    )
    assert preview.status_code == 200
    assert [row["amount_minor"] for row in preview.json()["rows"]] == [-450, 10000]

    saved = client.post(
        "/api/v1/import-mappings",
        json={
            "name": "Universal bank",
            "structural_signature": batch["structural_signature"],
            "account_id": account.id,
            "execution_plan": plan,
        },
    )
    assert saved.status_code == 201
    assert saved.json()["current_version"]["execution_plan"] == plan

    confirmed = client.put(
        f"/api/v1/imports/{batch['id']}/mapping",
        json={
            "expected_revision": batch["revision"],
            "execution_plan": plan,
            "source_template_id": saved.json()["id"],
            "source_template_version_id": saved.json()["current_version"]["id"],
        },
    )
    assert confirmed.status_code == 200
    staged = client.post(
        f"/api/v1/imports/{batch['id']}/stage",
        json={
            "expected_revision": confirmed.json()["revision"],
            "expected_mapping_revision": confirmed.json()["mapping_revision"],
        },
    )
    assert staged.status_code == 200
    assert staged.json()["current_execution_plan"] == plan
    assert client.get(f"/api/v1/imports/{batch['id']}/rows").json()["total"] == 2


def test_expenses_positive_inverts_source_signs_during_preview(app, client: TestClient) -> None:
    account = _account(app)
    batch = _upload(
        client,
        account.id,
        "Date,Description,Amount,Currency\n"
        "2026-08-01,Expense,4.50,EUR\n"
        "2026-08-02,Income,-10.00,EUR\n",
    ).json()
    plan = _inspect(client, batch["id"])["proposals"]["universal"]
    plan["amount"]["expense_sign_convention"] = "EXPENSES_POSITIVE"

    preview = client.post(
        f"/api/v1/imports/{batch['id']}/mapping-preview",
        json={"execution_plan": plan},
    )

    assert preview.status_code == 200
    assert [row["amount_minor"] for row in preview.json()["rows"]] == [-450, 1000]


def test_legacy_adapter_and_guided_payloads_are_rejected(app, client: TestClient) -> None:
    account = _account(app)
    batch = _upload(
        client,
        account.id,
        "Date,Description,Amount,Currency\n2026-08-01,Coffee,-4.50,EUR\n",
    ).json()

    for plan in (
        {
            "plan_type": "adapter",
            "schema_version": "adapter-v1",
            "profile_id": "revolut",
            "profile_version": "1",
            "configuration": {},
        },
        {
            "plan_type": "guided",
            "schema_version": "guided-v1",
            "transaction_date": {"source_column": "c000", "format": "%Y-%m-%d"},
            "description": {"source_column": "c001"},
            "amount": {"kind": "signed", "source_column": "c002"},
            "currency": {"kind": "source", "source_column": "c003"},
        },
    ):
        response = client.post(
            f"/api/v1/imports/{batch['id']}/mapping-preview",
            json={"execution_plan": plan},
        )
        assert response.status_code == 422

    universal = _inspect(client, batch["id"])["proposals"]["universal"]
    universal["description"]["source_column"] = "c999"
    response = client.post(
        f"/api/v1/imports/{batch['id']}/mapping-preview",
        json={"execution_plan": universal},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_mapping"


def test_historical_adapter_templates_are_not_proposed_or_executed(app, client: TestClient) -> None:
    account = _account(app)
    batch = _upload(
        client,
        account.id,
        "Date,Description,Amount,Currency\n2026-08-01,Coffee,-4.50,EUR\n",
    ).json()
    adapter_plan = {
        "plan_type": "adapter",
        "schema_version": "adapter-v1",
        "profile_id": "revolut",
        "profile_version": "1",
        "configuration": {},
    }
    with app.state.database.session() as session:
        template = ImportMappingTemplate(
            name="Historical adapter",
            structural_signature=batch["structural_signature"],
            account_id=account.id,
            origin=ImportMappingTemplateOrigin.MANUAL,
            is_active=True,
        )
        session.add(template)
        session.flush()
        session.add(
            ImportMappingTemplateVersion(
                template_id=template.id,
                version=1,
                execution_plan_kind=ImportExecutionPlanKind.ADAPTER_PROFILE,
                execution_plan_schema_version="adapter-v1",
                execution_plan_json=adapter_plan,
            )
        )
        session.commit()

        persisted = session.get(ImportBatch, batch["id"])
        snapshot = ImportBatchExecutionPlan(
            batch_id=persisted.id,
            mapping_revision=1,
            kind=ImportExecutionPlanKind.ADAPTER_PROFILE,
            schema_version="adapter-v1",
            plan_json=adapter_plan,
            origin=ImportMappingTemplateOrigin.PREDEFINED,
            profile_id="revolut",
            profile_version="1",
            provider="REVOLUT",
            fingerprint_algorithm="adapter-row",
            fingerprint_version="1",
        )
        session.add(snapshot)
        session.flush()
        persisted.mapping_revision = 1
        persisted.current_mapping_origin = ImportMappingTemplateOrigin.PREDEFINED
        persisted.current_profile_id = "revolut"
        persisted.current_profile_version = "1"
        persisted.current_provider = "REVOLUT"
        persisted.current_fingerprint_algorithm = "adapter-row"
        persisted.current_fingerprint_version = "1"
        session.commit()

    proposals = _inspect(client, batch["id"])["proposals"]
    assert proposals["templates"] == []
    assert client.get("/api/v1/import-mappings").json() == []
    assert client.get(f"/api/v1/import-mappings/{template.id}").status_code == 404
    reloaded = client.get(f"/api/v1/imports/{batch['id']}").json()
    assert reloaded["current_execution_plan"] is None

    staged = client.post(
        f"/api/v1/imports/{batch['id']}/stage",
        json={"expected_revision": batch["revision"], "expected_mapping_revision": 1},
    )
    assert staged.status_code == 409
    assert staged.json()["code"] == "historical_mapping_not_executable"
    with app.state.database.session() as session:
        assert session.get(ImportBatchExecutionPlan, snapshot.id).plan_json == adapter_plan


def test_reinspection_clears_current_mapping_but_retains_immutable_history(
    app, client: TestClient
) -> None:
    account = _account(app)
    batch = _upload(
        client,
        account.id,
        "Date,Description,Amount,Currency\n2026-08-01,Coffee,-4.50,EUR\n",
    ).json()
    plan = _inspect(client, batch["id"])["proposals"]["universal"]
    confirmed = client.put(
        f"/api/v1/imports/{batch['id']}/mapping",
        json={"expected_revision": batch["revision"], "execution_plan": plan},
    ).json()

    reinspected = client.patch(
        f"/api/v1/imports/{batch['id']}/inspection",
        json={"expected_revision": confirmed["revision"], "header_row": 1},
    )

    assert reinspected.status_code == 200
    current = client.get(f"/api/v1/imports/{batch['id']}").json()
    assert current["mapping_revision"] == 1
    assert current["current_mapping_origin"] is None
    assert current["current_execution_plan"] is None
    with app.state.database.session() as session:
        plans = list(
            session.scalars(
                select(ImportBatchExecutionPlan).where(
                    ImportBatchExecutionPlan.batch_id == batch["id"]
                )
            )
        )
        assert len(plans) == 1
        assert plans[0].mapping_revision == 1


def test_openai_suggestion_is_locally_previewed_before_it_is_returned(
    app, client: TestClient
) -> None:
    account = _account(app)
    batch = _upload(
        client,
        account.id,
        "Date,Description,Amount,Currency\n2026-08-01,Private Merchant,-4.50,EUR\n",
    ).json()
    plan_data = _inspect(client, batch["id"])["proposals"]["universal"]
    plan_data["transaction_date"] = {"source_column": "c000", "format": "%d.%m.%Y"}
    plan = UniversalMappingSpec.model_validate(plan_data)
    disclosed = client.get(f"/api/v1/imports/{batch['id']}/mapping-suggestion-payload").json()

    class FakeBoundary:
        async def suggest_mapping(self, prepared, *, consented_at):
            now = datetime.now(UTC)
            return MappingSuggestionSuccess(
                plan=plan,
                audit=MappingAuditMetadata(
                    model="fake-model",
                    request_id="req-safe",
                    payload_sha256=prepared.sha256,
                    consented_at=consented_at,
                    requested_at=now,
                    duration_ms=1,
                    outcome="suggested",
                ),
            )

    app.state.openai_mapping_boundary_factory = lambda _settings: FakeBoundary()
    suggested = client.post(
        f"/api/v1/imports/{batch['id']}/mapping-suggestion",
        headers={"Origin": "http://testserver"},
        json={
            "expected_revision": batch["revision"],
            "payload_sha256": disclosed["sha256"],
            "consent": True,
        },
    )

    assert suggested.status_code == 200
    assert suggested.json()["result"]["status"] == "manual_fallback"
    assert suggested.json()["result"]["error"]["code"] == "invalid_response"
    with app.state.database.session() as session:
        attempt = session.scalar(
            select(ImportMappingSuggestionAttempt).where(
                ImportMappingSuggestionAttempt.batch_id == batch["id"]
            )
        )
        assert attempt.execution_plan_json is None


def test_failed_concurrent_attempt_does_not_make_successful_attempt_stale(app) -> None:
    account = _account(app)
    with app.state.database.session() as session:
        batch = ImportBatch(
            account_id=account.id,
            original_filename="suggestion.csv",
            retained_path=None,
            file_sha256="f" * 64,
            parser_version="universal-import-v1",
            status="AWAITING_MAPPING",
        )
        session.add(batch)
        session.commit()
        batch_id = batch.id
        expected_revision = batch.revision

    now = datetime.now(UTC)
    audit = MappingAuditMetadata(
        model="fake-model",
        payload_sha256="a" * 64,
        consented_at=now,
        requested_at=now,
        duration_ms=1,
        outcome="manual_fallback",
        error_code=MappingFallbackCode.CONCURRENCY_LIMIT,
    )
    fallback = MappingSuggestionFallback(
        error=MappingFallbackError(
            code=MappingFallbackCode.CONCURRENCY_LIMIT,
            message="busy",
            retryable=True,
        ),
        audit=audit,
    )
    plan = UniversalMappingSpec.model_validate(
        {
            "transaction_date": {"source_column": "c000", "format": "%Y-%m-%d"},
            "description": {"source_column": "c001"},
            "amount": {"kind": "signed", "source_column": "c002"},
            "currency": {"kind": "constant", "value": "EUR"},
        }
    )
    success = MappingSuggestionSuccess(
        plan=plan,
        audit=audit.model_copy(
            update={"outcome": "suggested", "error_code": None, "request_id": "req-success"}
        ),
    )

    service = UniversalImportService(100, app.state.settings.data_dir)
    with app.state.database.session() as session:
        after_fallback, stale = service.record_suggestion(
            session, batch_id, expected_revision, fallback
        )
        assert stale is False
        assert after_fallback.revision == expected_revision
    with app.state.database.session() as session:
        after_success, stale = service.record_suggestion(
            session, batch_id, expected_revision, success
        )
        assert stale is False
        assert after_success.revision == expected_revision + 1
        attempts = list(
            session.scalars(
                select(ImportMappingSuggestionAttempt)
                .where(ImportMappingSuggestionAttempt.batch_id == batch_id)
                .order_by(ImportMappingSuggestionAttempt.attempt_number)
            )
        )
        assert [attempt.attempt_number for attempt in attempts] == [1, 2]
        assert attempts[1].execution_plan_json == plan.model_dump(mode="json")
