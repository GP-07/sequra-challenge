from django.db import OperationalError

# Errores en los que reintentar puede servir (infraestructura). Cualquier otro error no es retryable.
RETRYABLE_ERRORS = (OperationalError, TimeoutError)

# Error que queda en los disbursements de un paquete liberado por estar trabado en PROCESSING.
STUCK_PACKAGE_ERROR = "Processing interrupted: the package was stuck in PROCESSING and was released."
