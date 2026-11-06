"""Synthetic example of the calculation boundary for the scaffold."""

from dataclasses import dataclass
from decimal import Context, Decimal


@dataclass(frozen=True)
class DecimalInput:
    left: Decimal
    right: Decimal


@dataclass(frozen=True)
class DecimalOutput:
    total: Decimal


def add_decimals(values: DecimalInput) -> DecimalOutput:
    return DecimalOutput(Context(prec=28).add(values.left, values.right))
