"""Consultas sobre orders que usan otras apps, con nombres de negocio."""

from django.db import models
from django.db.models import Case, Min, Sum, Value, When


class OrderQuerySet(models.QuerySet):
    def pending_disbursement_by_merchant(self, merchant_ids, up_to) -> dict:
        """Una sola query: orders sin disbursement creadas hasta up_to (inclusive), por merchant.

        Devuelve {merchant_id: fecha de la order más vieja}; un merchant sin orders pendientes no aparece.
        """
        rows = (
            self.filter(merchant_id__in=merchant_ids, disbursement__isnull=True, order_creation_date__lte=up_to)
            .order_by()
            .values("merchant_id")
            .annotate(oldest=Min("order_creation_date"))
            .values_list("merchant_id", "oldest")
        )
        return dict(rows)

    def assign_to_disbursement(self, merchant_id, up_to, disbursement_id) -> int:
        """Asigna al disbursement las orders del merchant sin disbursement creadas hasta up_to. Devuelve cuántas."""
        return self.filter(
            merchant_id=merchant_id, disbursement__isnull=True, order_creation_date__lte=up_to
        ).update(disbursement_id=disbursement_id)

    def assign_to_disbursements(self, disbursement_by_merchant: dict, up_to) -> int:
        """assign_to_disbursement para varios merchants a la vez, con un solo UPDATE. Devuelve cuántas asignó.

        disbursement_by_merchant es {merchant_id: disbursement_id}.
        """
        if not disbursement_by_merchant:
            return 0
        return self.filter(
            merchant_id__in=disbursement_by_merchant, disbursement__isnull=True, order_creation_date__lte=up_to
        ).update(
            disbursement_id=Case(
                *[When(merchant_id=merchant_id, then=Value(disbursement_id))
                  for merchant_id, disbursement_id in disbursement_by_merchant.items()]
            )
        )

    def commissions_by_merchant(self, date_from, date_to) -> dict:
        """Una sola query: suma de commission_fee por merchant de las orders creadas en el rango (inclusive).

        Cuentan todas las orders creadas en el rango, estén pagadas o no.
        """
        rows = (
            self.filter(order_creation_date__range=(date_from, date_to))
            .order_by()
            .values("merchant_id")
            .annotate(commissions=Sum("commission_fee"))
            .values_list("merchant_id", "commissions")
        )
        return dict(rows)
