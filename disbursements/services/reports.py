"""Yearly table of the README.

- Disbursements: only the COMPLETED ones, by year of their payment date. disbursed_amount is what was
  paid to the merchant (gross minus commissions) and order_fees_amount, the commissions.
- Monthly fees: by year of the month they cover (December's counts in that year even if it is
  calculated in January).

Two queries in total, one per app; the years are merged in Python.
"""

from core.constants import ZERO_AMOUNT
from disbursements.data_classes import YearlyDisbursementTotals
from disbursements.models import Disbursement
from fees.data_classes import MonthlyFeesTotals
from fees.models import MonthlyFee

NO_DISBURSEMENTS = YearlyDisbursementTotals(0, ZERO_AMOUNT, ZERO_AMOUNT)
NO_MONTHLY_FEES = MonthlyFeesTotals(0, ZERO_AMOUNT)


def yearly_report() -> list[dict]:
    """Rows of the README yearly table, one per year with disbursements or monthly fees, in order."""
    disbursements = Disbursement.objects.completed_totals_by_year()
    monthly_fees = MonthlyFee.objects.totals_by_year()
    rows = []
    for year in sorted(disbursements.keys() | monthly_fees.keys()):
        year_disbursements = disbursements.get(year, NO_DISBURSEMENTS)
        year_fees = monthly_fees.get(year, NO_MONTHLY_FEES)
        rows.append(
            {
                "year": year,
                "disbursements_count": year_disbursements.count,
                "disbursed_amount": year_disbursements.disbursed_amount,
                "order_fees_amount": year_disbursements.order_fees_amount,
                "monthly_fees_count": year_fees.count,
                "monthly_fees_amount": year_fees.amount,
            }
        )
    return rows
