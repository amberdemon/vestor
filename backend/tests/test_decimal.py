from decimal import Decimal

from vestor_domain.decimal_example import DecimalInput, DecimalOutput, add_decimals


def test_synthetic_decimal_arithmetic_is_exact():
    result = add_decimals(DecimalInput(Decimal("0.10"), Decimal("0.20")))

    assert isinstance(result, DecimalOutput)
    assert isinstance(result.total, Decimal)
    assert result.total == Decimal("0.30")
    assert str(result.total) == "0.30"
