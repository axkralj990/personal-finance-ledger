from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session


def get_session(request: Request):
    yield from request.app.state.database.dependency()


SessionDependency = Annotated[Session, Depends(get_session)]
