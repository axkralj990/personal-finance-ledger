import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.database.models import Account

ACCOUNT_NAMESPACE = uuid.UUID("8927873d-f129-49d6-bbd4-e400552a471b")
UNKNOWN_ACCOUNT_NAME = "Unknown"
UNKNOWN_ACCOUNT_ID = str(uuid.uuid5(ACCOUNT_NAMESPACE, UNKNOWN_ACCOUNT_NAME))


def seed_accounts(session: Session) -> None:
    if session.scalar(select(Account).where(Account.name == UNKNOWN_ACCOUNT_NAME)) is None:
        session.add(
            Account(id=UNKNOWN_ACCOUNT_ID, name=UNKNOWN_ACCOUNT_NAME, default_currency="EUR")
        )
    session.commit()
