class DayCreationFailed(Exception):
    """The creation of a day of the backfill failed. The previous days are already saved."""

    def __init__(self, payment_date, frequency, created_before):
        self.payment_date = payment_date
        self.frequency = frequency
        self.created_before = created_before
        super().__init__(f"Creation of {frequency} disbursements for payment date {payment_date} failed.")
