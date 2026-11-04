from django.db import OperationalError

# Errors where retrying may help (infrastructure). Any other error is not retryable.
RETRYABLE_ERRORS = (OperationalError, TimeoutError)

# Error left on the disbursements of a package released because it was stuck in PROCESSING.
STUCK_PACKAGE_ERROR = "Processing interrupted: the package was stuck in PROCESSING and was released."
