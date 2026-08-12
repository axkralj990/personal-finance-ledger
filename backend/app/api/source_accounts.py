from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from backend.app.api.dependencies import SessionDependency
from backend.app.database.models import Provider, SourceAccount
from backend.app.problems import Problem

router = APIRouter(prefix="/source-accounts", tags=["source accounts"])


class SourceAccountCreate(BaseModel):
    provider: Provider
    display_name: str = Field(min_length=1, max_length=120)
    default_currency: str = Field(min_length=3, max_length=3)

    @field_validator("default_currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()


class SourceAccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: Provider
    display_name: str
    default_currency: str
    is_active: bool


@router.get("", response_model=list[SourceAccountRead])
def list_source_accounts(session: SessionDependency) -> list[SourceAccount]:
    return list(session.scalars(select(SourceAccount).order_by(SourceAccount.display_name)))


@router.post("", response_model=SourceAccountRead, status_code=201)
def create_source_account(
    payload: SourceAccountCreate, session: SessionDependency
) -> SourceAccount:
    existing = session.scalar(
        select(SourceAccount).where(SourceAccount.display_name == payload.display_name)
    )
    if existing:
        raise Problem(409, "source_account_exists", "A source account with this name exists")
    account = SourceAccount(**payload.model_dump())
    session.add(account)
    session.commit()
    return account
