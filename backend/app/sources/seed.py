import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.database.models import Provider, SourceAccount

SOURCE_ACCOUNT_NAMESPACE = uuid.UUID("8927873d-f129-49d6-bbd4-e400552a471b")

DEFAULT_SOURCE_ACCOUNTS = (
    (Provider.LEGACY, "Legacy historical ledger", "EUR"),
    (Provider.REVOLUT, "Revolut Personal EUR", "EUR"),
    (Provider.REVOLUT, "Revolut Joint EUR", "EUR"),
    (Provider.DBS, "DBS EUR", "EUR"),
    (Provider.MASTERCARD, "Mastercard EUR", "EUR"),
    (Provider.MANUAL, "Manual EUR", "EUR"),
)

SOURCE_ACCOUNT_IDS = {
    display_name: str(uuid.uuid5(SOURCE_ACCOUNT_NAMESPACE, display_name))
    for _, display_name, _ in DEFAULT_SOURCE_ACCOUNTS
}

LEGACY_SOURCE_ACCOUNT_NAMES = {
    "legacy": "Legacy historical ledger",
    "revolut": "Revolut Personal EUR",
    "joint": "Revolut Joint EUR",
    "dbs": "DBS EUR",
    "mastercard": "Mastercard EUR",
    "manual": "Manual EUR",
}

LEGACY_ACCOUNT_ID = SOURCE_ACCOUNT_IDS[LEGACY_SOURCE_ACCOUNT_NAMES["legacy"]]


def seed_source_accounts(session: Session) -> None:
    existing_names = set(session.scalars(select(SourceAccount.display_name)))
    for provider, display_name, currency in DEFAULT_SOURCE_ACCOUNTS:
        if display_name in existing_names:
            continue
        session.add(
            SourceAccount(
                id=SOURCE_ACCOUNT_IDS[display_name],
                provider=provider,
                display_name=display_name,
                default_currency=currency,
            )
        )
    session.commit()


def legacy_source_account_id(normalized_source: str) -> str:
    return SOURCE_ACCOUNT_IDS[LEGACY_SOURCE_ACCOUNT_NAMES[normalized_source]]
