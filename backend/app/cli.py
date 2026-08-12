import argparse
import hashlib
import shutil
import sqlite3
import uuid
from pathlib import Path

from sqlalchemy import func, select

from backend.app.config import Settings
from backend.app.database.models import (
    DuplicateStatus,
    ImportBatch,
    SourceAccount,
    StagedDisposition,
    StagedTransaction,
    Transaction,
)
from backend.app.database.session import Database
from backend.app.imports.service import ImportService
from backend.app.problems import Problem
from backend.app.sources.seed import LEGACY_ACCOUNT_ID
from backend.app.tagging.training import (
    DEFAULT_CATEGORY_THRESHOLD,
    DEFAULT_SUBCATEGORY_THRESHOLD,
    TrainingError,
    train_model,
)


def main() -> None:
    parser = argparse.ArgumentParser(prog="personal-finance")
    subparsers = parser.add_subparsers(dest="command", required=True)

    history = subparsers.add_parser("migrate-history")
    history.add_argument("--file", type=Path, required=True)
    history.add_argument("--commit-clean", action="store_true")

    backup = subparsers.add_parser("backup")
    backup.add_argument("--output", type=Path, required=True)

    train = subparsers.add_parser("train-model")
    train.add_argument(
        "--category-threshold", type=_confidence_threshold, default=DEFAULT_CATEGORY_THRESHOLD
    )
    train.add_argument(
        "--subcategory-threshold",
        type=_confidence_threshold,
        default=DEFAULT_SUBCATEGORY_THRESHOLD,
    )

    args = parser.parse_args()
    settings = Settings()
    database = Database(settings.resolved_database_url)
    database.migrate()
    try:
        if args.command == "migrate-history":
            migrate_history(database, settings, args.file, commit_clean=args.commit_clean)
        elif args.command == "backup":
            backup_database(settings, args.output)
        else:
            train_tagging_model(
                database,
                settings,
                category_threshold=args.category_threshold,
                subcategory_threshold=args.subcategory_threshold,
            )
    finally:
        database.dispose()


def migrate_history(
    database: Database,
    settings: Settings,
    source_file: Path,
    *,
    commit_clean: bool,
) -> None:
    if not source_file.is_file():
        raise SystemExit(f"Historical file does not exist: {source_file}")
    digest = _file_hash(source_file)
    with database.session() as session:
        account = session.get(SourceAccount, LEGACY_ACCOUNT_ID)
        if account is None:
            raise SystemExit("Legacy historical source account is not seeded")
        existing = session.scalar(
            select(ImportBatch).where(
                ImportBatch.source_account_id == account.id,
                ImportBatch.file_sha256 == digest,
            )
        )
        if existing:
            if commit_clean:
                try:
                    ImportService(settings.max_file_rows, settings.data_dir).commit(
                        session, existing, clean_only=True
                    )
                except Problem as exc:
                    raise SystemExit(f"{exc.body.code}: {exc.body.message}") from exc
            _print_history_summary(session, existing)
            return
        uploads = settings.data_dir / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        retained = uploads / f"legacy-{uuid.uuid4()}{source_file.suffix.casefold()}"
        shutil.copyfile(source_file, retained)
        service = ImportService(settings.max_file_rows, settings.data_dir)
        try:
            batch = service.stage_file(session, account, retained, source_file.name, digest)
            if commit_clean:
                service.commit(session, batch, clean_only=True)
        except Problem as exc:
            raise SystemExit(f"{exc.body.code}: {exc.body.message}") from exc
        _print_history_summary(session, batch)


def backup_database(settings: Settings, output: Path) -> None:
    prefix = "sqlite:///"
    url = settings.resolved_database_url
    if not url.startswith(prefix):
        raise SystemExit("Online backup supports SQLite database URLs only")
    source = Path(url.removeprefix(prefix))
    if not source.is_file():
        raise SystemExit(f"Database does not exist: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as source_connection, sqlite3.connect(output) as destination:
        source_connection.backup(destination)
    print(f"Backup written to {output}")


def train_tagging_model(
    database: Database,
    settings: Settings,
    *,
    category_threshold: float,
    subcategory_threshold: float,
) -> None:
    try:
        with database.session() as session:
            result = train_model(
                session,
                settings.data_dir,
                category_threshold=category_threshold,
                subcategory_threshold=subcategory_threshold,
            )
    except TrainingError as exc:
        raise SystemExit(f"training_failed: {exc}") from exc
    print(
        f"Model trained: version={result.model_name}, training_rows={result.training_row_count}, "
        f"categories={result.category_count}, "
        f"subcategory_models={result.subcategory_model_count}, "
        f"subcategory_constants={result.subcategory_constant_count}, "
        f"scikit_learn={result.sklearn_version}, taxonomy={result.taxonomy_version}"
    )


def _confidence_threshold(value: str) -> float:
    threshold = float(value)
    if not 0.0 < threshold <= 1.0:
        raise argparse.ArgumentTypeError("threshold must be greater than 0 and at most 1")
    return threshold


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _print_history_summary(session, batch: ImportBatch) -> None:
    rows = list(
        session.scalars(select(StagedTransaction).where(StagedTransaction.batch_id == batch.id))
    )
    status_counts = {
        status.value: sum(row.disposition == status for row in rows) for status in StagedDisposition
    }
    issue_codes = [
        issue.get("code") for row in rows for issue in row.validation_issues if issue.get("code")
    ]
    committed = int(
        session.scalar(
            select(func.count(Transaction.id)).where(Transaction.import_batch_id == batch.id)
        )
        or 0
    )
    exact = sum(row.duplicate_status == DuplicateStatus.EXACT for row in rows)
    likely = sum(row.duplicate_status == DuplicateStatus.LIKELY for row in rows)
    invalid = sum(bool(row.validation_issues) for row in rows)
    statuses = ", ".join(f"{name}={count}" for name, count in status_counts.items() if count)
    print(
        f"Historical migration: staged={len(rows)}, committed={committed}, "
        f"exact_blocked={exact}, likely_review={likely}, "
        f"invalid_or_taxonomy_review={invalid}, parse_errors={issue_codes.count('parse_error')}, "
        f"taxonomy_conflicts={issue_codes.count('taxonomy_conflict')}, "
        f"batch_status={batch.status.value}"
    )
    print(f"Row statuses: {statuses or 'none'}")


if __name__ == "__main__":
    main()
