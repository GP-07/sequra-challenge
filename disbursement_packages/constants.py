from django.db import OperationalError

# Errores en los que reintentar puede servir (infraestructura). Cualquier otro error no es retryable.
RETRYABLE_ERRORS = (OperationalError, TimeoutError)
