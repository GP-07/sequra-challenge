# Rows per UPDATE when saving disbursement results with bulk_update.
DISBURSEMENT_UPDATE_BATCH_SIZE = 1000

# Retries of the daily creation task if it fails (for example, the DB does not respond). It is idempotent.
CREATION_TASK_RETRIES = 2
CREATION_TASK_RETRY_DELAY_SECONDS = 10 * 60
