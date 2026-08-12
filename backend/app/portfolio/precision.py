import re
from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal, DecimalException, InvalidOperation

from backend.app.problems import Problem

DECIMAL_PATTERN = re.compile(r"^(?:0|[1-9]\d{0,14})(?:\.\d{0,17}[1-9])?$")
MINOR_UNITS = Decimal(100)
JS_SAFE_INTEGER = 9_007_199_254_740_991
SUPPORTED_PORTFOLIO_CURRENCIES = frozenset({"CHF", "EUR", "GBP", "USD"})


def parse_decimal(value: str, field: str, *, positive: bool = False) -> Decimal:
    if not DECIMAL_PATTERN.fullmatch(value):
        raise Problem(
            422,
            "invalid_decimal",
            f"{field} must be a canonical non-negative decimal string",
            field=field,
            recoverable=True,
        )
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise Problem(
            422,
            "invalid_decimal",
            f"{field} must be a canonical decimal string",
            field=field,
            recoverable=True,
        ) from exc
    if positive and parsed <= 0:
        raise Problem(
            422,
            "invalid_decimal",
            f"{field} must be greater than zero",
            field=field,
            recoverable=True,
        )
    return parsed


def canonical_decimal(value: Decimal) -> str:
    if not value.is_finite() or value < 0:
        raise ValueError("canonical decimals must be finite and non-negative")
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def convert_minor_to_eur(native_value_minor: int, rate_to_eur: Decimal) -> int:
    _validate_minor(native_value_minor)
    try:
        converted = int(
            (Decimal(native_value_minor) * rate_to_eur).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        )
    except (DecimalException, OverflowError) as exc:
        raise _arithmetic_problem() from exc
    _validate_minor(converted)
    return converted


def position_value_minor(quantity: Decimal, unit_price: Decimal) -> int:
    try:
        value = int(
            (quantity * unit_price * MINOR_UNITS).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        )
    except (DecimalException, OverflowError) as exc:
        raise _arithmetic_problem() from exc
    _validate_minor(value)
    return value


def percentage(numerator: int, denominator: int) -> str | None:
    if denominator <= 0:
        return None
    value = (Decimal(numerator) * Decimal(100) / Decimal(denominator)).quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_UP
    )
    if value < 0:
        return f"-{canonical_decimal(abs(value))}"
    return canonical_decimal(value)


def checked_minor_sum(values: Iterable[int]) -> int:
    total = sum(values)
    if abs(total) > JS_SAFE_INTEGER:
        raise _arithmetic_problem()
    return total


def _validate_minor(value: int) -> None:
    if value < 0 or value > JS_SAFE_INTEGER:
        raise _arithmetic_problem()


def _arithmetic_problem() -> Problem:
    return Problem(
        422,
        "portfolio_arithmetic_overflow",
        "Portfolio value exceeds supported precision",
        recoverable=True,
    )
