"""Merchants with random data, for testing the daily flow. Used by generate_testing_orders."""

import uuid
from datetime import date

from merchants.constants import GENERATED_MERCHANT_MINIMUM_MONTHLY_FEE
from merchants.models import Merchant


def create_random_merchant(live_on: date) -> Merchant:
    """Creates a DAILY merchant with a random reference, live since `live_on`."""
    reference = f"testing_{uuid.uuid4().hex[:8]}"
    return Merchant.objects.create(
        external_id=uuid.uuid4(),
        reference=reference,
        email=f"info@{reference}.com",
        live_on=live_on,
        disbursement_frequency=Merchant.Frequency.DAILY,
        minimum_monthly_fee=GENERATED_MERCHANT_MINIMUM_MONTHLY_FEE,
    )
