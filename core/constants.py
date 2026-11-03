from decimal import Decimal

# Montos: hasta 12 dígitos enteros y 2 decimales.
MONEY = {"max_digits": 14, "decimal_places": 2}

# CSV de importación.
CSV_DELIMITER = ";"

# Los montos se redondean a centavos (ROUND_HALF_UP).
CENTS = Decimal("0.01")
ZERO_AMOUNT = Decimal("0.00")
