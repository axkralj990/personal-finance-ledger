import argparse
import hashlib
import shutil
import sqlite3
import tempfile
from pathlib import Path

from backend.app.config import Settings
from backend.app.database.session import Database
from backend.app.tagging.training import (
    DEFAULT_CATEGORY_THRESHOLD,
    DEFAULT_SUBCATEGORY_THRESHOLD,
    TrainingError,
    train_model,
)
from backend.app.test_data import seed_test_data
from backend.app.test_data.seed import SeedTestDataRefusedError


def main() -> None:
    parser = argparse.ArgumentParser(prog="personal-finance")
    subparsers = parser.add_subparsers(dest="command", required=True)

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

    seed = subparsers.add_parser("seed-test-data")
    seed.add_argument("--reset", action="store_true", required=True)

    args = parser.parse_args()
    settings = Settings()
    if args.command == "backup":
        backup_database(settings, args.output)
        return
    database = Database(settings.resolved_database_url)
    try:
        database.migrate()
        if args.command == "seed-test-data":
            try:
                summary = seed_test_data(database, settings, reset=args.reset)
            except SeedTestDataRefusedError as exc:
                raise SystemExit(f"seed_test_data_refused: {exc}") from exc
            print(
                "Synthetic test data seeded: "
                f"accounts={summary.accounts}, transactions={summary.transactions}, "
                f"imports={summary.import_batches}, assets={summary.assets}, "
                f"income_minor={summary.income_minor}, spending_minor={summary.spending_minor}, "
                f"net_minor={summary.net_minor}"
            )
            return
        train_tagging_model(
            database,
            settings,
            category_threshold=args.category_threshold,
            subcategory_threshold=args.subcategory_threshold,
        )
    finally:
        database.dispose()


def backup_database(settings: Settings, output: Path) -> None:
    prefix = "sqlite:///"
    url = settings.resolved_database_url
    if not url.startswith(prefix):
        raise SystemExit("Online backup supports SQLite database URLs only")
    source = Path(url.removeprefix(prefix))
    if not source.is_file():
        raise SystemExit(f"Database does not exist: {source}")
    if output.exists():
        raise SystemExit(f"Backup destination already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    reserved_output = False
    try:
        with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as source_connection:
            source_counts = _verify_database(source_connection, "source")
            try:
                output.open("xb").close()
            except FileExistsError as exc:
                raise SystemExit(f"Backup destination already exists: {output}") from exc
            reserved_output = True
            with sqlite3.connect(output) as destination:
                source_connection.backup(destination)
        with sqlite3.connect(f"file:{output}?mode=ro", uri=True) as destination:
            destination_counts = _verify_database(destination, "destination")
        _require_counts(source_counts, destination_counts, "destination")
        checksum = _sha256(output)
        with tempfile.TemporaryDirectory(dir=output.parent) as restore_directory:
            restored = Path(restore_directory) / output.name
            shutil.copyfile(output, restored)
            _require_checksum(checksum, restored)
            with sqlite3.connect(f"file:{restored}?mode=ro", uri=True) as restored_connection:
                restored_counts = _verify_database(restored_connection, "temporary restore")
            _require_counts(source_counts, restored_counts, "temporary restore")
    except Exception as exc:
        if reserved_output:
            output.unlink(missing_ok=True)
        raise SystemExit(f"Backup failed verification: {exc}") from exc
    print(f"Backup written to {output} sha256={checksum} counts={source_counts}")


def _verify_database(connection: sqlite3.Connection, label: str) -> dict[str, int]:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()
    if integrity != ("ok",):
        raise RuntimeError(f"{label} integrity check failed: {integrity!r}")
    foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_keys:
        raise RuntimeError(f"{label} foreign key check failed: {foreign_keys!r}")
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    counts = {}
    for table in sorted(tables):
        quoted_table = table.replace('"', '""')
        counts[table] = int(
            connection.execute(
                f'SELECT count(*) FROM "{quoted_table}"'  # noqa: S608 - quoted schema name.
            ).fetchone()[0]
        )
    return counts


def _require_counts(expected: dict[str, int], actual: dict[str, int], label: str) -> None:
    if actual != expected:
        raise RuntimeError(f"{label} core row counts differ: expected={expected}, actual={actual}")


def _require_checksum(expected: str, restored: Path) -> None:
    if _sha256(restored) != expected:
        raise RuntimeError("Temporary restore checksum differs from backup")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as backup_file:
        while chunk := backup_file.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


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


if __name__ == "__main__":
    main()
