"""Factories de factory_boy para crear datos de prueba."""

import uuid
from datetime import date
from decimal import Decimal

import factory
from factory.django import DjangoModelFactory

from disbursements.models import Disbursement, DisbursementPackage, Order
from merchants.tests.factories import MerchantFactory


class OrderFactory(DjangoModelFactory):
    """commission_fee es explícita para no depender del cálculo."""

    class Meta:
        model = Order

    id = factory.Sequence(lambda n: f"order{n:07d}")
    merchant = factory.SubFactory(MerchantFactory)
    amount = Decimal("100.00")
    commission_fee = Decimal("0.95")
    created_at = date(2023, 2, 7)


class DisbursementFactory(DjangoModelFactory):
    """`orders=[...]` asigna esas orders al disbursement."""

    class Meta:
        model = Disbursement
        skip_postgeneration_save = True

    merchant = factory.SubFactory(MerchantFactory)
    payment_date = date(2023, 2, 8)
    reference = factory.LazyAttribute(lambda d: f"{d.merchant.reference}_for_{d.payment_date:%Y%m%d}")
    natural_key_hash = factory.LazyFunction(lambda: uuid.uuid4().hex)

    @factory.post_generation
    def orders(self, create, extracted, **kwargs):
        if not create or not extracted:
            return
        Order.objects.filter(id__in=[o.id for o in extracted]).update(disbursement=self)
        self.order_count = len(extracted)
        self.save(update_fields=["order_count"])


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
