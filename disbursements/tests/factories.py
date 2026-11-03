"""Factories de factory_boy para crear datos de prueba."""

import uuid
from datetime import date

import factory
from factory.django import DjangoModelFactory

from disbursements.models import Disbursement
from merchants.tests.factories import MerchantFactory
from orders.models import Order


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
