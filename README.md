# Merchant disbursements

## Notes on the provided data

- **November 2023 monthly fees are calculated over a partial month.** The provided orders end on
  2023-11-07, and the backfill of monthly fees covers up to November 2023 included. November fees
  therefore only count the commissions of the first 7 days, so they are higher than they would be
  with the full month. In normal operation this does not happen: the monthly task runs on the 1st
  and calculates the previous month, which is already closed.
