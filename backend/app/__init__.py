from typing import Any


def create_app(*args: Any, **kwargs: Any) -> Any:
    from backend.app.main import create_app as factory  # noqa: PLC0415 - avoids package cycle.

    return factory(*args, **kwargs)


__all__ = ["create_app"]
