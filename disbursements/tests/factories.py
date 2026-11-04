"""factory_boy factories to create test data."""

import uuid
from datetime import date

import factory
from factory.django import DjangoModelFactory

from disbursements.models import Disbursement
from merchants.tests.factories import MerchantFactory
from orders.models import Order


class DisbursementFactory(DjangoModelFactory):
    """`orders=[...]` assigns those orders to the disbursement."""

    class Meta:
        model = Disbursement
        skip_postgeneration_save = True

    merchant = factory.SubFactory(MerchantFactory)
    payment_date = date(2023, 2, 8)
    reference = factory.LazyAttribute(lambda disbursement: f"{disbursement.merchant.reference}_for_{disbursement.payment_date:%Y%m%d}")
    natural_key_hash = factory.LazyFunction(lambda: uuid.uuid4().hex)

    @factory.post_generation
    def orders(self, create, extracted, **kwargs):
        if not create or not extracted:
            return
        Order.objects.filter(id__in=[order.id for order in extracted]).update(disbursement=self)
