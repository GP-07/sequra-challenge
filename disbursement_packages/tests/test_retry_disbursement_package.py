"""retry_disbursement_package: reprocesa a mano un paquete entero."""

from datetime import date

import pytest
from django.core.management import CommandError

from core.tests.helpers import run_command
from disbursement_packages.models import DisbursementPackage
from disbursement_packages.tests.factories import DisbursementPackageFactory
from disbursements.models import Disbursement
from disbursements.tests.factories import DisbursementFactory
from merchants.tests.factories import MerchantFactory
from orders.tests.factories import OrderFactory

pytestmark = pytest.mark.django_db


def test_retry_reprocesses_a_non_retryable_package_after_fixing_the_data():
    # Así queda un paquete tras una falla de datos: FAILED no retryable, porque reintentar
    # automáticamente no sirve. Alguien ya corrigió el dato (order_count vuelve a coincidir) y lo
    # reprocesa a mano: el retry manual no mira is_retryable.
    merchant = MerchantFactory(reference="padberg_group")
    order = OrderFactory(merchant=merchant, order_creation_date=date(2023, 2, 7))
    disbursement = DisbursementFactory(
        merchant=merchant,
        payment_date=date(2023, 2, 8),
        orders=[order],
        status=Disbursement.Status.FAILED,
        error="Expected 2 orders but found 1.",
        is_retryable=False,
    )
    package = DisbursementPackageFactory(disbursements=[disbursement], status=DisbursementPackage.Status.FAILED, attempts=1)

    run_command("retry_disbursement_package", str(package.id))

    package.refresh_from_db()
    assert package.status == DisbursementPackage.Status.COMPLETED
    disbursement.refresh_from_db()
    assert disbursement.status == Disbursement.Status.COMPLETED
    assert disbursement.error == ""
    assert disbursement.is_retryable is None


def test_retry_unknown_package():
    with pytest.raises(CommandError):
        run_command("retry_disbursement_package", "999999")


def test_retry_completed_package_is_skipped_and_reported():
    merchant = MerchantFactory(reference="padberg_group")
    order = OrderFactory(merchant=merchant, order_creation_date=date(2023, 2, 7))
    disbursement = DisbursementFactory(
        merchant=merchant, payment_date=date(2023, 2, 8), orders=[order], status=Disbursement.Status.COMPLETED
    )
    package = DisbursementPackageFactory(
        disbursements=[disbursement], status=DisbursementPackage.Status.COMPLETED, attempts=1
    )

    output = run_command("retry_disbursement_package", str(package.id))

    assert "already completed" in output.lower()
    package.refresh_from_db()
    assert package.status == DisbursementPackage.Status.COMPLETED
    assert package.attempts == 1
