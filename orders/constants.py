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

# generate_testing_orders (test data): one range per commission tier, used in turns so every tier is covered.
GENERATED_ORDER_AMOUNT_RANGES = (
    (Decimal("1.00"), Decimal("49.99")),
    (Decimal("50.00"), Decimal("299.99")),
    (Decimal("300.00"), Decimal("1000.00")),
)
GENERATED_ORDERS_MIN_COUNT = 2
GENERATED_ORDERS_MAX_COUNT = 50
GENERATED_ORDERS_DEFAULT_COUNT = 50
# Each run creates this many new merchants, so the queries that group by merchant are exercised.
GENERATED_MERCHANTS_COUNT = 2
