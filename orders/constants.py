from decimal import Decimal

ORDER_CSV_COLUMNS = {"id", "merchant_reference", "amount", "created_at"}

# Commission tiers: (amount from which it applies, percentage). The first one that matches is used.
COMMISSION_TIERS = (
    (Decimal("300"), Decimal("0.0085")),
    (Decimal("50"), Decimal("0.0095")),
    (Decimal("0"), Decimal("0.01")),
)

# Rows per batch when importing the orders CSV (the challenge one has ~1.3M).
ORDER_IMPORT_BATCH_SIZE = 5000
