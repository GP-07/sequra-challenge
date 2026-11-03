# Filas por UPDATE al guardar resultados de disbursements con bulk_update.
DISBURSEMENT_UPDATE_BATCH_SIZE = 1000

# Reintentos de la task diaria de creación si falla (por ejemplo, la DB no responde). Es idempotente.
CREATION_TASK_RETRIES = 2
CREATION_TASK_RETRY_DELAY_SECONDS = 10 * 60
