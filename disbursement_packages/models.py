from django.db import models


class DisbursementPackage(models.Model):
    """Logical group of disbursements to process them together.

    The result (COMPLETED/FAILED, error, whether it can be retried) belongs to each disbursement; the
    package status sums it up: COMPLETED if all its disbursements are, FAILED if any is not.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING"
        PROCESSING = "PROCESSING"
        COMPLETED = "COMPLETED"
        FAILED = "FAILED"

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    order_count = models.PositiveIntegerField(default=0)
    # Each time it is taken for processing (1 + retries): limits how many times it is reprocessed.
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
