"""Factories de factory_boy para crear datos de prueba."""

import factory
from factory.django import DjangoModelFactory

from disbursement_packages.models import DisbursementPackage
from disbursements.models import Disbursement
from orders.models import Order


class DisbursementPackageFactory(DjangoModelFactory):
    """`disbursements=[...]` los asigna al paquete; order_count se cuenta desde sus orders."""

    class Meta:
        model = DisbursementPackage
        skip_postgeneration_save = True

    @factory.post_generation
    def disbursements(self, create, extracted, **kwargs):
        if not create or not extracted:
            return
        Disbursement.objects.filter(id__in=[d.id for d in extracted]).update(package=self)
        self.order_count = Order.objects.filter(disbursement__package=self).count()
        self.save(update_fields=["order_count"])
