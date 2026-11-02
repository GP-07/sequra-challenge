from decimal import Decimal

ORDER_CSV_COLUMNS = {"id", "merchant_reference", "amount", "created_at"}

# Tramos de comisión: (monto desde el que aplica, porcentaje). Se usa el primero que cumple.
COMMISSION_TIERS = (
    (Decimal("300"), Decimal("0.0085")),
    (Decimal("50"), Decimal("0.0095")),
    (Decimal("0"), Decimal("0.01")),
)

# Filas por lote al importar el CSV de orders (el del challenge tiene ~1,3M).
ORDER_IMPORT_BATCH_SIZE = 5000
