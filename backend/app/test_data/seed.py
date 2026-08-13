from __future__ import annotations

import hashlib
import io
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.database.models import (
    Account,
    Asset,
    AssetEvent,
    AssetType,
    AssetValuation,
    BatchStatus,
    Category,
    DuplicateStatus,
    ImportBatch,
    ImportBatchExecutionPlan,
    ImportMappingSuggestionAttempt,
    ImportMappingSuggestionOutcome,
    ImportMappingTemplate,
    ImportMappingTemplateVersion,
    ModelVersion,
    StagedDisposition,
    StagedTransaction,
    Subcategory,
    TagRule,
    Transaction,
    TransactionDeletion,
    TransactionEvent,
    TransactionKind,
    ValuationSource,
)
from backend.app.database.session import Database
from backend.app.sources.seed import UNKNOWN_ACCOUNT_ID, UNKNOWN_ACCOUNT_NAME
from backend.app.taxonomy.seed import resolve_taxonomy, seed_taxonomy

SYNTHETIC_NAMESPACE = uuid.UUID("f4c3887a-a277-45eb-aaf7-d1589c91732d")
FIXED_AT = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def synthetic_id(name: str) -> str:
    return str(uuid.uuid5(SYNTHETIC_NAMESPACE, name))


DEMO_CHECKING_ID = synthetic_id("account:demo-checking")
DEMO_CREDIT_CARD_ID = synthetic_id("account:demo-credit-card")
CHECKING_BATCH_ID = synthetic_id("batch:checking-csv")
CREDIT_BATCH_ID = synthetic_id("batch:credit-xlsx")
DUPLICATE_BATCH_ID = synthetic_id("batch:duplicate-review")
IGNORED_TRANSACTION_ID = synthetic_id("transaction:ignored")
IGNORED_STAGED_ID = synthetic_id("staged:ignored")
IGNORED_REASON = "Synthetic transfer excluded from reporting"

TRANSACTIONS = (
    ("salary", DEMO_CHECKING_ID, date(2026, 1, 31), "Demo salary", 300_000, "income", "misc"),
    (
        "freelance",
        DEMO_CHECKING_ID,
        date(2026, 2, 5),
        "Demo freelance income",
        50_000,
        "income",
        "misc",
    ),
    ("rent", DEMO_CHECKING_ID, date(2026, 2, 1), "Demo rent", -100_000, "apartment", "expenses"),
    (
        "groceries",
        DEMO_CHECKING_ID,
        date(2026, 2, 7),
        "Demo groceries",
        -12_345,
        "food",
        "groceries",
    ),
    (
        "transit",
        DEMO_CHECKING_ID,
        date(2026, 2, 10),
        "Demo transit pass",
        -5_000,
        "transport",
        "public",
    ),
    (
        "flight",
        DEMO_CREDIT_CARD_ID,
        date(2026, 2, 14),
        "Demo flight",
        -45_600,
        "travel",
        "plane",
    ),
)


@dataclass(frozen=True, slots=True)
class SeedSummary:
    accounts: int
    transactions: int
    import_batches: int
    assets: int
    income_minor: int
    spending_minor: int
    net_minor: int


class SeedTestDataRefusedError(RuntimeError):
    pass


def seed_test_data(database: Database, settings: Settings, *, reset: bool) -> SeedSummary:
    if not reset:
        raise SeedTestDataRefusedError("seed-test-data requires --reset")
    fixture_dir = settings.data_dir / "test-data"
    csv_bytes = _csv_fixture_bytes()
    xlsx_bytes = _xlsx_fixture_bytes()

    with database.session() as session, session.begin():
        _clear_business_data(session)
        seed_taxonomy(session)
        session.execute(update(Category).values(created_at=FIXED_AT, updated_at=FIXED_AT))
        session.execute(update(Subcategory).values(created_at=FIXED_AT, updated_at=FIXED_AT))
        _seed_accounts(session)
        _seed_imports_and_transactions(session, fixture_dir, csv_bytes, xlsx_bytes)
        _seed_portfolio(session)

    fixture_dir.mkdir(parents=True, exist_ok=True)
    (fixture_dir / "synthetic-transactions.csv").write_bytes(csv_bytes)
    (fixture_dir / "synthetic-credit-card.xlsx").write_bytes(xlsx_bytes)

    income = sum(amount for *_, amount, _category, _subcategory in TRANSACTIONS if amount > 0)
    spending = -sum(amount for *_, amount, _category, _subcategory in TRANSACTIONS if amount < 0)
    return SeedSummary(
        accounts=3,
        transactions=len(TRANSACTIONS) + 1,
        import_batches=3,
        assets=2,
        income_minor=income,
        spending_minor=spending,
        net_minor=income - spending,
    )


def _clear_business_data(session: Session) -> None:
    session.execute(delete(AssetEvent))
    session.execute(delete(AssetValuation))
    session.execute(delete(Asset))
    session.execute(delete(TransactionEvent))
    session.execute(delete(TransactionDeletion))
    session.execute(delete(TagRule))
    session.execute(
        update(StagedTransaction).values(
            duplicate_candidate_id=None,
            duplicate_status=DuplicateStatus.NONE,
            duplicate_explanation=None,
        )
    )
    session.execute(delete(Transaction))
    session.execute(delete(StagedTransaction))
    session.execute(delete(ImportMappingSuggestionAttempt))

    sqlite = session.bind is not None and session.bind.dialect.name == "sqlite"
    if sqlite:
        _drop_immutable_import_delete_triggers(session)
    session.execute(delete(ImportBatchExecutionPlan))
    session.execute(delete(ImportBatch))
    session.execute(delete(ImportMappingTemplateVersion))
    session.execute(delete(ImportMappingTemplate))
    if sqlite:
        _restore_immutable_import_delete_triggers(session)

    session.execute(delete(ModelVersion))
    session.execute(delete(Subcategory))
    session.execute(delete(Category))
    session.execute(delete(Account))


def _drop_immutable_import_delete_triggers(session: Session) -> None:
    session.connection().exec_driver_sql(
        "DROP TRIGGER IF EXISTS prevent_import_batch_execution_plan_delete"
    )
    session.connection().exec_driver_sql(
        "DROP TRIGGER IF EXISTS prevent_import_mapping_template_version_delete"
    )


def _restore_immutable_import_delete_triggers(session: Session) -> None:
    session.connection().exec_driver_sql(
        "CREATE TRIGGER prevent_import_mapping_template_version_delete "
        "BEFORE DELETE ON import_mapping_template_versions "
        "BEGIN SELECT RAISE(ABORT, 'import mapping template versions are retained'); END"
    )
    session.connection().exec_driver_sql(
        "CREATE TRIGGER prevent_import_batch_execution_plan_delete "
        "BEFORE DELETE ON import_batch_execution_plans "
        "BEGIN SELECT RAISE(ABORT, 'import batch execution plans are retained'); END"
    )


def _seed_accounts(session: Session) -> None:
    unknown = session.get(Account, UNKNOWN_ACCOUNT_ID)
    if unknown is None:
        unknown = Account(id=UNKNOWN_ACCOUNT_ID, name=UNKNOWN_ACCOUNT_NAME, default_currency="EUR")
        session.add(unknown)
    unknown.name = UNKNOWN_ACCOUNT_NAME
    unknown.default_currency = "EUR"
    unknown.is_active = True
    unknown.created_at = FIXED_AT
    unknown.updated_at = FIXED_AT
    session.add_all(
        [
            Account(
                id=DEMO_CHECKING_ID,
                name="Demo Checking",
                default_currency="EUR",
                created_at=FIXED_AT,
                updated_at=FIXED_AT,
            ),
            Account(
                id=DEMO_CREDIT_CARD_ID,
                name="Demo Credit Card",
                default_currency="EUR",
                created_at=FIXED_AT,
                updated_at=FIXED_AT,
            ),
        ]
    )
    session.flush()


def _seed_imports_and_transactions(
    session: Session, fixture_dir: Path, csv_bytes: bytes, xlsx_bytes: bytes
) -> None:
    batches = {
        CHECKING_BATCH_ID: ImportBatch(
            id=CHECKING_BATCH_ID,
            account_id=DEMO_CHECKING_ID,
            original_filename="synthetic-transactions.csv",
            retained_path=str(fixture_dir / "synthetic-transactions.csv"),
            file_sha256=hashlib.sha256(csv_bytes).hexdigest(),
            parser_version="synthetic-v1",
            status=BatchStatus.COMMITTED,
            total_rows=6,
            included_rows=5,
            ignored_rows=1,
            inspection_json={"sheet_names": [], "headers": ["date", "description", "amount"]},
            inspection_version="synthetic-v1",
            structural_signature="1" * 64,
            created_at=FIXED_AT,
            updated_at=FIXED_AT,
            committed_at=FIXED_AT,
        ),
        CREDIT_BATCH_ID: ImportBatch(
            id=CREDIT_BATCH_ID,
            account_id=DEMO_CREDIT_CARD_ID,
            original_filename="synthetic-credit-card.xlsx",
            retained_path=str(fixture_dir / "synthetic-credit-card.xlsx"),
            file_sha256=hashlib.sha256(xlsx_bytes).hexdigest(),
            parser_version="synthetic-v1",
            status=BatchStatus.COMMITTED,
            total_rows=1,
            included_rows=1,
            ignored_rows=0,
            inspection_json={"sheet_names": ["Transactions"], "selected_sheet": "Transactions"},
            inspection_version="synthetic-v1",
            structural_signature="2" * 64,
            created_at=FIXED_AT,
            updated_at=FIXED_AT,
            committed_at=FIXED_AT,
        ),
        DUPLICATE_BATCH_ID: ImportBatch(
            id=DUPLICATE_BATCH_ID,
            account_id=DEMO_CHECKING_ID,
            original_filename="synthetic-duplicate-review.csv",
            retained_path=None,
            file_sha256="3" * 64,
            parser_version="synthetic-v1",
            status=BatchStatus.NEEDS_REVIEW,
            total_rows=1,
            included_rows=0,
            ignored_rows=0,
            inspection_json={"audit_scenario": "strong_duplicate_identity"},
            inspection_version="synthetic-v1",
            structural_signature="3" * 64,
            created_at=FIXED_AT,
            updated_at=FIXED_AT,
        ),
    }
    session.add_all(batches.values())
    session.flush()

    for row_number, row in enumerate(TRANSACTIONS, 1):
        name, account_id, transaction_date, description, amount, category, subcategory = row
        batch_id = CREDIT_BATCH_ID if name == "flight" else CHECKING_BATCH_ID
        category_id, subcategory_id = resolve_taxonomy(session, category, subcategory)
        fingerprint = hashlib.sha256(f"synthetic:{name}".encode()).hexdigest()
        staged_id = synthetic_id(f"staged:{name}")
        native_id = f"demo-{name}"
        staged = StagedTransaction(
            id=staged_id,
            batch_id=batch_id,
            account_id=account_id,
            row_number=1 if name == "flight" else row_number,
            raw_json={
                "date": transaction_date.isoformat(),
                "description": description,
                "amount": amount,
            },
            transaction_date=transaction_date,
            description=description,
            normalized_description=description.casefold(),
            amount_minor=amount,
            currency="EUR",
            kind=TransactionKind.INCOME if amount > 0 else TransactionKind.EXPENSE,
            source_native_id=native_id,
            row_fingerprint=fingerprint,
            category_id=category_id,
            subcategory_id=subcategory_id,
            disposition=StagedDisposition.COMMITTED,
            created_at=FIXED_AT,
            updated_at=FIXED_AT,
        )
        session.add(staged)
        session.flush()
        transaction = Transaction(
            id=synthetic_id(f"transaction:{name}"),
            account_id=account_id,
            transaction_date=transaction_date,
            description=description,
            normalized_description=description.casefold(),
            amount_minor=amount,
            currency="EUR",
            kind=TransactionKind.INCOME if amount > 0 else TransactionKind.EXPENSE,
            category_id=category_id,
            subcategory_id=subcategory_id,
            source_native_id=native_id,
            row_fingerprint=fingerprint,
            import_batch_id=batch_id,
            staged_transaction_id=staged_id,
            created_at=FIXED_AT,
            updated_at=FIXED_AT,
        )
        session.add(transaction)

    session.add(
        StagedTransaction(
            id=IGNORED_STAGED_ID,
            batch_id=CHECKING_BATCH_ID,
            account_id=DEMO_CHECKING_ID,
            row_number=6,
            raw_json={"description": "Demo internal transfer", "amount": -25_000},
            transaction_date=date(2026, 2, 12),
            description="Demo internal transfer",
            normalized_description="demo internal transfer",
            amount_minor=-25_000,
            currency="EUR",
            kind=TransactionKind.EXPENSE,
            source_native_id="demo-ignored",
            row_fingerprint=hashlib.sha256(b"synthetic:ignored").hexdigest(),
            disposition=StagedDisposition.IGNORE,
            ignore_reason=IGNORED_REASON,
            created_at=FIXED_AT,
            updated_at=FIXED_AT,
        )
    )
    session.flush()
    session.add(
        Transaction(
            id=IGNORED_TRANSACTION_ID,
            account_id=DEMO_CHECKING_ID,
            transaction_date=date(2026, 2, 12),
            description="Demo internal transfer",
            normalized_description="demo internal transfer",
            amount_minor=-25_000,
            currency="EUR",
            kind=TransactionKind.EXPENSE,
            source_native_id="demo-ignored",
            row_fingerprint=hashlib.sha256(b"synthetic:ignored").hexdigest(),
            import_batch_id=CHECKING_BATCH_ID,
            staged_transaction_id=IGNORED_STAGED_ID,
            is_excluded=True,
            exclusion_reason=IGNORED_REASON,
            excluded_at=FIXED_AT,
            created_at=FIXED_AT,
            updated_at=FIXED_AT,
        )
    )
    session.flush()

    groceries_transaction_id = synthetic_id("transaction:groceries")
    groceries_category_id, groceries_subcategory_id = resolve_taxonomy(session, "food", "groceries")
    session.add_all(
        [
            StagedTransaction(
                id=synthetic_id("staged:duplicate-groceries"),
                batch_id=DUPLICATE_BATCH_ID,
                account_id=DEMO_CHECKING_ID,
                row_number=1,
                raw_json={"native_id": "demo-groceries", "description": "Demo groceries"},
                transaction_date=date(2026, 2, 7),
                description="Demo groceries",
                normalized_description="demo groceries",
                amount_minor=-12_345,
                currency="EUR",
                kind=TransactionKind.EXPENSE,
                source_native_id="demo-groceries",
                row_fingerprint=hashlib.sha256(b"synthetic:duplicate-groceries").hexdigest(),
                category_id=groceries_category_id,
                subcategory_id=groceries_subcategory_id,
                duplicate_status=DuplicateStatus.EXACT,
                duplicate_candidate_id=groceries_transaction_id,
                duplicate_explanation="Same account and source-native identity",
                disposition=StagedDisposition.BLOCKED,
                created_at=FIXED_AT,
                updated_at=FIXED_AT,
            ),
            ImportMappingSuggestionAttempt(
                id=synthetic_id("mapping-suggestion:duplicate-review"),
                batch_id=DUPLICATE_BATCH_ID,
                batch_revision=1,
                attempt_number=1,
                model_name="synthetic-local-fixture",
                provider_request_id=None,
                prompt_version="synthetic-v1",
                schema_version="1",
                payload_sha256=hashlib.sha256(b"synthetic mapping payload").hexdigest(),
                consented_at=FIXED_AT,
                started_at=FIXED_AT,
                completed_at=FIXED_AT,
                duration_ms=0,
                outcome=ImportMappingSuggestionOutcome.SUCCEEDED,
                execution_plan_json={"source": "synthetic", "network_used": False},
                created_at=FIXED_AT,
            ),
            TransactionEvent(
                id=synthetic_id("transaction-event:groceries-categorized"),
                transaction_id=groceries_transaction_id,
                event_type="CATEGORIZED",
                previous_values={"category_id": None, "subcategory_id": None},
                new_values={
                    "category_id": groceries_category_id,
                    "subcategory_id": groceries_subcategory_id,
                },
                created_at=FIXED_AT,
            ),
        ]
    )


def _seed_portfolio(session: Session) -> None:
    cash_id = synthetic_id("asset:cash")
    etf_id = synthetic_id("asset:etf")
    session.add_all(
        [
            Asset(
                id=cash_id,
                name="Demo Emergency Fund",
                asset_type=AssetType.BANK_CASH,
                currency="EUR",
                acquisition_date=date(2025, 1, 1),
                created_at=FIXED_AT,
                updated_at=FIXED_AT,
            ),
            Asset(
                id=etf_id,
                name="Demo Global ETF",
                asset_type=AssetType.ETF,
                currency="EUR",
                acquisition_date=date(2025, 1, 15),
                quantity="10",
                cost_basis_native_minor=100_000,
                cost_basis_eur_minor=100_000,
                cost_basis_fx_source="IDENTITY",
                cost_basis_fx_rate_to_eur="1",
                cost_basis_fx_rate_date=date(2025, 1, 15),
                quote_symbol="DEMO",
                quote_exchange="SYNTHETIC",
                created_at=FIXED_AT,
                updated_at=FIXED_AT,
            ),
        ]
    )
    session.flush()
    session.add_all(
        [
            AssetValuation(
                id=synthetic_id("valuation:cash:2026-02-28"),
                asset_id=cash_id,
                valued_at=date(2026, 2, 28),
                native_value_minor=250_000,
                eur_value_minor=250_000,
                source=ValuationSource.MANUAL,
                fx_source="IDENTITY",
                fx_rate_to_eur="1",
                fx_rate_date=date(2026, 2, 28),
                created_at=FIXED_AT,
            ),
            AssetValuation(
                id=synthetic_id("valuation:etf:2026-01-31"),
                asset_id=etf_id,
                valued_at=date(2026, 1, 31),
                native_value_minor=120_000,
                eur_value_minor=120_000,
                quantity="10",
                unit_price="120",
                cost_basis_native_minor=100_000,
                cost_basis_eur_minor=100_000,
                cost_basis_fx_source="IDENTITY",
                cost_basis_fx_rate_to_eur="1",
                cost_basis_fx_rate_date=date(2025, 1, 15),
                source=ValuationSource.MANUAL,
                fx_source="IDENTITY",
                fx_rate_to_eur="1",
                fx_rate_date=date(2026, 1, 31),
                created_at=FIXED_AT,
            ),
            AssetValuation(
                id=synthetic_id("valuation:etf:2026-02-28"),
                asset_id=etf_id,
                valued_at=date(2026, 2, 28),
                native_value_minor=125_000,
                eur_value_minor=125_000,
                quantity="10",
                unit_price="125",
                cost_basis_native_minor=100_000,
                cost_basis_eur_minor=100_000,
                cost_basis_fx_source="IDENTITY",
                cost_basis_fx_rate_to_eur="1",
                cost_basis_fx_rate_date=date(2025, 1, 15),
                source=ValuationSource.MANUAL,
                fx_source="IDENTITY",
                fx_rate_to_eur="1",
                fx_rate_date=date(2026, 2, 28),
                created_at=FIXED_AT,
            ),
        ]
    )


def _csv_fixture_bytes() -> bytes:
    rows = ["date,description,amount,currency,native_id"]
    for (
        name,
        _account,
        transaction_date,
        description,
        amount,
        _category,
        _subcategory,
    ) in TRANSACTIONS:
        if name == "flight":
            continue
        rows.append(
            f'{transaction_date.isoformat()},"{description}",{amount / 100:.2f},EUR,demo-{name}'
        )
    rows.append('2026-02-12,"Demo internal transfer",-250.00,EUR,demo-ignored')
    return ("\n".join(rows) + "\n").encode()


def _xlsx_fixture_bytes() -> bytes:
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
            'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>'
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Transactions" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'
        ),
        "xl/worksheets/sheet1.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>date</t></is></c>'
            '<c r="B1" t="inlineStr"><is><t>description</t></is></c>'
            '<c r="C1" t="inlineStr"><is><t>amount</t></is></c>'
            '<c r="D1" t="inlineStr"><is><t>currency</t></is></c>'
            '<c r="E1" t="inlineStr"><is><t>native_id</t></is></c></row>'
            '<row r="2"><c r="A2" t="inlineStr"><is><t>2026-02-14</t></is></c>'
            '<c r="B2" t="inlineStr"><is><t>Demo flight</t></is></c>'
            '<c r="C2"><v>-456</v></c><c r="D2" t="inlineStr"><is><t>EUR</t></is></c>'
            '<c r="E2" t="inlineStr"><is><t>demo-flight</t></is></c></row>'
            "</sheetData></worksheet>"
        ),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as workbook:
        for name, content in files.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            workbook.writestr(info, content.encode())
    return output.getvalue()
