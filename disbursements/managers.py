"""Operaciones sobre disbursements que usan otras apps (paquetes), con nombres de negocio.

Las otras apps llaman a estos métodos en lugar de filtrar o actualizar el modelo directamente.
"""

from django.db import models
from django.db.models import Count, Sum
from django.utils import timezone

from core.constants import ZERO_AMOUNT
from disbursements.constants import DISBURSEMENT_UPDATE_BATCH_SIZE
from disbursements.data_classes import DisbursementTotals


class DisbursementQuerySet(models.QuerySet):
    # --- armado de paquetes ---

    def to_package(self, date_from, date_to):
        """PENDING sin paquete con fecha de pago en el rango, en orden determinístico y bloqueados (FOR UPDATE).

        Se usa dentro de una transacción: si dos corridas arman paquetes a la vez, la segunda espera y
        ya no ve los que quedaron con paquete.
        """
        return (
            self.select_for_update(of=("self",))
            .filter(status=self.model.Status.PENDING, package__isnull=True, payment_date__range=(date_from, date_to))
            .order_by("payment_date", "merchant_id")
            .only("id", "reference")
        )

    def order_counts(self, disbursement_ids) -> dict[int, int]:
        """Una sola query: {disbursement_id: cantidad de orders}. Va aparte de to_package porque
        Postgres no permite FOR UPDATE con GROUP BY.
        """
        rows = self.filter(id__in=disbursement_ids).order_by().annotate(orders_found=Count("orders"))
        return dict(rows.values_list("id", "orders_found"))

    def assign_to_package(self, disbursement_ids, package):
        return self.filter(id__in=disbursement_ids).update(package=package, updated_at=timezone.now())

    def mark_as_requires_attention(self, disbursement_ids):
        return self.filter(id__in=disbursement_ids).update(
            status=self.model.Status.REQUIRES_ATTENTION, updated_at=timezone.now()
        )

    # --- procesamiento de paquetes ---

    def unfinished_in_package(self, package_id, disbursement_ids=None):
        """Los que falta procesar de un paquete (PENDING o FAILED); con disbursement_ids, solo esos."""
        queryset = self.filter(package_id=package_id, status__in=[self.model.Status.PENDING, self.model.Status.FAILED])
        if disbursement_ids is not None:
            queryset = queryset.filter(id__in=disbursement_ids)
        return queryset

    def totals(self) -> dict[int, DisbursementTotals]:
        """Una sola query: bruto y comisiones de cada disbursement del queryset."""
        rows = self.order_by().annotate(
            gross=Sum("orders__amount"),
            fees=Sum("orders__commission_fee"),
        ).values_list("id", "gross", "fees")
        return {
            disbursement_id: DisbursementTotals(disbursement_id, gross or ZERO_AMOUNT, fees or ZERO_AMOUNT)
            for disbursement_id, gross, fees in rows
        }

    def mark_as_completed(self, totals: list[DisbursementTotals]) -> None:
        now = timezone.now()
        disbursements = [
            self.model(
                id=t.disbursement_id,
                status=self.model.Status.COMPLETED,
                gross_amount=t.gross_amount,
                commission_fee_amount=t.commission_fee_amount,
                disbursed_amount=t.gross_amount - t.commission_fee_amount,
                error="",
                is_retryable=None,
                updated_at=now,
            )
            for t in totals
        ]
        self.bulk_update(
            disbursements,
            ["status", "gross_amount", "commission_fee_amount", "disbursed_amount", "error", "is_retryable", "updated_at"],
            batch_size=DISBURSEMENT_UPDATE_BATCH_SIZE,
        )

    def mark_as_failed_with_errors(self, failures: list[tuple[int, str]], *, is_retryable: bool) -> None:
        """Cada uno con su propio error (falla de datos de un disbursement)."""
        now = timezone.now()
        disbursements = [
            self.model(
                id=disbursement_id,
                status=self.model.Status.FAILED,
                error=error,
                is_retryable=is_retryable,
                gross_amount=None,
                commission_fee_amount=None,
                disbursed_amount=None,
                updated_at=now,
            )
            for disbursement_id, error in failures
        ]
        self.bulk_update(
            disbursements,
            ["status", "error", "is_retryable", "gross_amount", "commission_fee_amount", "disbursed_amount", "updated_at"],
            batch_size=DISBURSEMENT_UPDATE_BATCH_SIZE,
        )

    def mark_as_failed(self, error: str, *, is_retryable: bool) -> int:
        """Todos los del queryset con el mismo error (falla de infraestructura o inesperada)."""
        return self.update(
            status=self.model.Status.FAILED,
            error=error,
            is_retryable=is_retryable,
            gross_amount=None,
            commission_fee_amount=None,
            disbursed_amount=None,
            updated_at=timezone.now(),
        )

    # --- control de paquetes ---

    def packaged_for_payment_date(self, payment_date):
        return self.filter(payment_date=payment_date, package__isnull=False)

    def failed(self):
        return self.filter(status=self.model.Status.FAILED)
