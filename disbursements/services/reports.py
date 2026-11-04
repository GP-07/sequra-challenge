"""Tabla anual del README.

- Disbursements: solo los COMPLETED, por año de su fecha de pago. disbursed_amount es lo pagado al
  merchant (bruto menos comisiones) y order_fees_amount, las comisiones.
- Monthly fees: por año del mes que cubren (la de diciembre cuenta en ese año aunque se calcule en enero).

Dos queries en total, una por app; los años se unen en Python.
"""

from core.constants import ZERO_AMOUNT
from disbursements.data_classes import YearlyDisbursementTotals
from disbursements.models import Disbursement
from fees.data_classes import MonthlyFeesTotals
from fees.models import MonthlyFee

NO_DISBURSEMENTS = YearlyDisbursementTotals(0, ZERO_AMOUNT, ZERO_AMOUNT)
NO_MONTHLY_FEES = MonthlyFeesTotals(0, ZERO_AMOUNT)


def yearly_report() -> list[dict]:
    """Filas de la tabla anual del README, una por año con disbursements o monthly fees, en orden."""
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
