import hashlib
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select

from backend.app.config import Settings
from backend.app.database.models import (
    Account,
    BatchStatus,
    Category,
    ImportBatch,
    ModelVersion,
    StagedDisposition,
    StagedTransaction,
    Subcategory,
    Transaction,
    TransactionKind,
)
from backend.app.database.session import Database
from backend.app.imports.service import ImportService
from backend.app.sources.normalization import normalize_description
from backend.app.tagging.model import (
    JoblibInferenceModel,
    _load_verified_model,
    load_inference_model,
)
from backend.app.tagging.training import TrainingError, train_model


def test_training_is_deterministic_and_replaces_active_model(
    database: Database, settings: Settings, account: Account
) -> None:
    with database.session() as session:
        labels = _seed_training_transactions(session, session.merge(account))
        first = train_model(session, settings.data_dir)
        first_metadata = session.get(ModelVersion, first.model_version_id)
        first_model = load_inference_model(first_metadata, settings.data_dir)
        first_prediction = first_model.predict(
            "SYNTHETIC ORCHARD   MARKET produce fresh", -9191, TransactionKind.EXPENSE
        )

        second = train_model(session, settings.data_dir)
        second_metadata = session.get(ModelVersion, second.model_version_id)
        second_model = load_inference_model(second_metadata, settings.data_dir)
        second_prediction = second_model.predict(
            "synthetic orchard market produce fresh", -9191, TransactionKind.EXPENSE
        )

        assert first.model_version_id != second.model_version_id
        assert first_prediction.category_id == second_prediction.category_id == labels["food"]
        assert (
            first_prediction.subcategory_id
            == second_prediction.subcategory_id
            == labels["groceries"]
        )
        assert first_prediction.confidence == pytest.approx(second_prediction.confidence, abs=1e-12)
        assert session.scalar(select(func.count(ModelVersion.id))) == 2
        active = list(session.scalars(select(ModelVersion).where(ModelVersion.is_active.is_(True))))
        assert [model.id for model in active] == [second.model_version_id]


def test_artifact_metadata_checksum_cache_and_hierarchy(
    database: Database,
    settings: Settings,
    account: Account,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with database.session() as session:
        labels = _seed_training_transactions(session, session.merge(account))
        result = train_model(session, settings.data_dir)
        metadata = session.get(ModelVersion, result.model_version_id)
        artifact_path = settings.data_dir / metadata.artifact_path

        assert artifact_path.parent == settings.data_dir / "models"
        assert not Path(metadata.artifact_path).is_absolute()
        assert hashlib.sha256(artifact_path.read_bytes()).hexdigest() == metadata.checksum
        assert metadata.training_metadata["training_row_count"] == result.training_row_count
        assert metadata.training_metadata["thresholds"] == {
            "category": 0.7,
            "subcategory": 0.8,
        }
        assert metadata.training_metadata["library_versions"]["scikit_learn"]
        assert metadata.training_metadata["taxonomy_checksum"]
        assert metadata.training_metadata["model_configuration"]["random_state"] == 42
        assert (
            labels["lifestyle"] in metadata.training_metadata["subcategory_unresolved_categories"]
        )

        _load_verified_model.cache_clear()
        load_count = 0
        original_load = __import__("joblib").load

        def counted_load(*args, **kwargs):
            nonlocal load_count
            load_count += 1
            return original_load(*args, **kwargs)

        monkeypatch.setattr("backend.app.tagging.model.joblib.load", counted_load)
        model = load_inference_model(metadata, settings.data_dir)
        assert model is load_inference_model(metadata, settings.data_dir)
        assert load_count == 1
        assert isinstance(model, JoblibInferenceModel)
        assert set(model.subcategory_models) == {labels["food"]}
        assert set(model.subcategory_models[labels["food"]].classes_) == {
            labels["groceries"],
            labels["out"],
        }
        assert model.subcategory_constants[labels["transport"]] == labels["public"]
        assert labels["lifestyle"] not in model.subcategory_models
        assert labels["lifestyle"] not in model.subcategory_constants
        unresolved = model.predict("Synthetic Paper Studio book", -5500, TransactionKind.EXPENSE)
        assert unresolved.category_id == labels["lifestyle"]
        assert unresolved.subcategory_id is None
        assert unresolved.auto_accept is False

        metadata.checksum = "0" * 64
        assert load_inference_model(metadata, settings.data_dir) is None
        assert str(artifact_path) not in caplog.text
        assert metadata.checksum not in caplog.text
        batch = ImportService(100, settings.data_dir).stage_manual(
            session,
            session.merge(account),
            [_new_source_row("Synthetic Checksum Failure Merchant")],
        )
        row = batch.staged_rows[0]
        assert row.predicted_category_id is None
        assert row.category_id is None
        assert row.disposition == StagedDisposition.PENDING


def test_low_confidence_prediction_stays_pending_with_proposal(
    database: Database, settings: Settings, account: Account
) -> None:
    with database.session() as session:
        labels = _seed_training_transactions(session, session.merge(account))
        train_model(
            session,
            settings.data_dir,
            category_threshold=1.0,
            subcategory_threshold=1.0,
        )
        batch = ImportService(100, settings.data_dir).stage_manual(
            session,
            session.merge(account),
            [_new_source_row("Synthetic Orchard Market produce fresh")],
        )
        row = batch.staged_rows[0]

        assert row.predicted_category_id == labels["food"]
        assert row.predicted_subcategory_id == labels["groceries"]
        assert row.prediction_confidence is not None
        assert row.category_id is None
        assert row.subcategory_id is None
        assert row.disposition == StagedDisposition.PENDING


def test_stale_or_removed_taxonomy_prevents_auto_acceptance(
    database: Database, settings: Settings, account: Account
) -> None:
    with database.session() as session:
        labels = _seed_training_transactions(session, session.merge(account))
        train_model(session, settings.data_dir)
        removed_subcategory = session.get(Subcategory, labels["groceries"])
        removed_subcategory.is_active = False
        session.commit()

        batch = ImportService(100, settings.data_dir).stage_manual(
            session,
            session.merge(account),
            [_new_source_row("Synthetic Orchard Market produce fresh")],
        )
        row = batch.staged_rows[0]

        assert row.predicted_category_id == labels["food"]
        assert row.predicted_subcategory_id is None
        assert row.category_id is None
        assert row.disposition == StagedDisposition.PENDING


def test_staging_after_training_auto_labels_learned_merchant(
    database: Database, settings: Settings, account: Account
) -> None:
    with database.session() as session:
        labels = _seed_training_transactions(session, session.merge(account))
        train_model(session, settings.data_dir)

        batch = ImportService(100, settings.data_dir).stage_manual(
            session,
            session.merge(account),
            [_new_source_row("  SYNTHETIC Orchard Market   produce fresh  ")],
        )
        row = batch.staged_rows[0]

        assert row.normalized_description == "synthetic orchard market produce fresh"
        assert row.predicted_category_id == row.category_id == labels["food"]
        assert row.predicted_subcategory_id == row.subcategory_id == labels["groceries"]
        assert row.model_version_id is not None
        assert row.disposition == StagedDisposition.INCLUDE
        assert batch.status == BatchStatus.READY


def test_training_requires_two_category_classes(
    database: Database, settings: Settings, account: Account
) -> None:
    with database.session() as session:
        _seed_training_transactions(session, session.merge(account), food_only=True)
        with pytest.raises(TrainingError, match="at least two category classes"):
            train_model(session, settings.data_dir)


def test_failed_artifact_verification_does_not_replace_active_model(
    database: Database,
    settings: Settings,
    account: Account,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with database.session() as session:
        _seed_training_transactions(session, session.merge(account))
        first = train_model(session, settings.data_dir)

        def reject_artifact(*args, **kwargs):
            raise ValueError("synthetic verification failure")

        monkeypatch.setattr("backend.app.tagging.training.verify_model_artifact", reject_artifact)
        with pytest.raises(ValueError, match="synthetic verification failure"):
            train_model(session, settings.data_dir)

        active = list(session.scalars(select(ModelVersion).where(ModelVersion.is_active.is_(True))))
        assert [model.id for model in active] == [first.model_version_id]
        assert session.scalar(select(func.count(ModelVersion.id))) == 1
        assert len(list((settings.data_dir / "models").glob("*.joblib"))) == 1


def _seed_training_transactions(
    session, account: Account, *, food_only: bool = False
) -> dict[str, str]:
    categories = {
        category.slug: category.id
        for category in session.scalars(
            select(Category).where(Category.slug.in_(["food", "transport", "income", "lifestyle"]))
        )
    }
    subcategories = {
        (subcategory.category_id, subcategory.slug): subcategory.id
        for subcategory in session.scalars(select(Subcategory))
    }
    labels = {
        **categories,
        "groceries": subcategories[(categories["food"], "groceries")],
        "out": subcategories[(categories["food"], "out")],
        "public": subcategories[(categories["transport"], "public")],
        "rent": subcategories[(categories["income"], "rent")],
        "books": subcategories[(categories["lifestyle"], "books")],
        "clothes": subcategories[(categories["lifestyle"], "clothes")],
    }
    groups = [
        ("food", "groceries", "Synthetic Orchard Market produce", -1100, 16),
        ("food", "out", "Synthetic Harbor Cafe meal", -2200, 16),
    ]
    if not food_only:
        groups.extend(
            [
                ("transport", "public", "Synthetic Metro Transit ticket", -3300, 20),
                ("income", "rent", "Synthetic Payroll Credit", 4400, 20),
                ("lifestyle", "books", "Synthetic Paper Studio book", -5500, 2),
                ("lifestyle", "clothes", "Synthetic Wardrobe Studio garment", -6600, 1),
            ]
        )

    batch = ImportBatch(
        account_id=account.id,
        original_filename="synthetic-training.csv",
        retained_path=None,
        file_sha256=hashlib.sha256(b"synthetic-training").hexdigest(),
        parser_version="test",
        status=BatchStatus.COMMITTED,
    )
    session.add(batch)
    session.flush()
    index = 0
    for category_slug, subcategory_slug, description_prefix, amount, count in groups:
        for variant in range(count):
            index += 1
            description = f"{description_prefix} {variant}"
            normalized = normalize_description(description)
            fingerprint = hashlib.sha256(f"training-{index}".encode()).hexdigest()
            kind = TransactionKind.INCOME if amount > 0 else TransactionKind.EXPENSE
            staged = StagedTransaction(
                batch_id=batch.id,
                account_id=account.id,
                row_number=index,
                raw_json={"synthetic": index},
                transaction_date=date(2026, 1, index % 28 + 1),
                description=description,
                normalized_description=normalized,
                amount_minor=amount,
                currency="EUR",
                kind=kind,
                row_fingerprint=fingerprint,
                category_id=categories[category_slug],
                subcategory_id=labels[subcategory_slug],
                disposition=StagedDisposition.COMMITTED,
            )
            session.add(staged)
            session.flush()
            session.add(
                Transaction(
                    account_id=account.id,
                    transaction_date=staged.transaction_date,
                    description=description,
                    normalized_description=normalized,
                    amount_minor=amount,
                    currency="EUR",
                    kind=kind,
                    category_id=categories[category_slug],
                    subcategory_id=labels[subcategory_slug],
                    row_fingerprint=fingerprint,
                    import_batch_id=batch.id,
                    staged_transaction_id=staged.id,
                )
            )
    session.commit()
    return labels


def _new_source_row(description: str) -> dict[str, object]:
    return {
        "transaction_date": "2027-06-15",
        "description": description,
        "amount_minor": -9191,
        "currency": "EUR",
        "kind": TransactionKind.EXPENSE,
    }
