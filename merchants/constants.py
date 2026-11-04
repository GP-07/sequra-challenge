from decimal import Decimal

MERCHANT_CSV_COLUMNS = {"id", "reference", "email", "live_on", "disbursement_frequency", "minimum_monthly_fee"}

# Merchants created by generate_testing_orders (test data): DAILY, so the next daily run pays them.
GENERATED_MERCHANT_MINIMUM_MONTHLY_FEE = Decimal("29.00")
