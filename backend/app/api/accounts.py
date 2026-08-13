from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.app.api.dependencies import SessionDependency
from backend.app.currencies import normalize_currency_code
from backend.app.database.models import Account, utc_now
from backend.app.problems import Problem

router = APIRouter(prefix="/accounts", tags=["accounts"])


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    default_currency: str = Field(min_length=3, max_length=3)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        if not (name := value.strip()):
            raise ValueError("name must not be blank")
        return name

    @field_validator("default_currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        return normalize_currency_code(value)


class AccountPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    default_currency: str | None = Field(default=None, min_length=3, max_length=3)
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("name must not be null")
        if not (name := value.strip()):
            raise ValueError("name must not be blank")
        return name

    @field_validator("default_currency")
    @classmethod
    def validate_currency(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("default_currency must not be null")
        return normalize_currency_code(value)


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    default_currency: str
    is_active: bool


@router.get("", response_model=list[AccountRead])
def list_accounts(session: SessionDependency) -> list[Account]:
    return list(session.scalars(select(Account).order_by(Account.name)))


@router.post("", response_model=AccountRead, status_code=201)
def create_account(payload: AccountCreate, session: SessionDependency) -> Account:
    account = Account(**payload.model_dump())
    session.add(account)
    _commit_account(session)
    return account


@router.patch("/{account_id}", response_model=AccountRead)
def update_account(account_id: str, payload: AccountPatch, session: SessionDependency) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise Problem(404, "account_not_found", "Account was not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(account, field, value)
    account.updated_at = utc_now()
    _commit_account(session)
    return account


@router.post("/{account_id}/deactivate", response_model=AccountRead)
def deactivate_account(account_id: str, session: SessionDependency) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise Problem(404, "account_not_found", "Account was not found")
    account.is_active = False
    account.updated_at = utc_now()
    session.commit()
    return account


def _commit_account(session: SessionDependency) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise Problem(409, "account_exists", "An account with this name exists") from exc
