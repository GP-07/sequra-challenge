from decimal import Decimal

# Amounts: up to 12 integer digits and 2 decimals.
MONEY = {"max_digits": 14, "decimal_places": 2}

# CSV separator: for the imported files and for the one yearly_report prints.
CSV_DELIMITER = ";"

# Amounts are rounded to cents (ROUND_HALF_UP).
CENTS = Decimal("0.01")
ZERO_AMOUNT = Decimal("0.00")
