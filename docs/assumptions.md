# Assumptions

Detail of the assumptions summarized in the [README](../README.md#assumptions).

## Dates and order arrival

Dates are in UTC, and orders only have a date, without a time. No order comes in during the run of
its own day: an order arrives at least one day later and goes into the next run. An order that
arrives with an older date is handled as a delayed order: it goes into the next disbursement of its
merchant, which is flagged with `has_processed_delayed_orders`.

## Commission tiers

An order of exactly 50 € pays 0.95%, and one of exactly 300 € pays 0.85%. Commissions are
calculated per order and rounded half-up to 2 decimals.

## Valid amounts

Orders with amount 0 are valid, with commission 0.00; only negative amounts are rejected. An empty
`minimum_monthly_fee` is loaded as 0, and a merchant with minimum 0 never pays a monthly fee.

## Monthly fee over every order of the month, paid or not

The monthly fee counts every order created in the month, whether it has been paid or not. Charging
the order is seQura's responsibility, not the merchant's, so an order that has not been paid yet, or
whose disbursement failed, still counts towards the minimum. Risks accepted:

- If an order cannot be paid in the end (for example, its disbursement failed because of invalid
  data that is later corrected or removed), the monthly fee of that month was already calculated
  counting it, and it has to be reviewed by hand.
- If an order of a month arrives late, after the 1st of the next month, the monthly fee of its month
  was already calculated without it.

## A month without orders pays the whole minimum

A live merchant that generated no commissions is below its minimum, so it is charged the full
`minimum_monthly_fee`. There is no special rule for merchants without orders for a long time (see
[inactive merchants](improvements.md#inactive-merchants)).

## The first month is not prorated

A merchant that goes live in the middle of a month pays the full minimum for that month.

## Yearly report

Disbursements count by year of their payment date, and only the COMPLETED ones. Monthly fees count
by year of the month they cover: December's fee is calculated on January 1st, but it counts in
December's year.

## No concurrent creations for the same merchant

Two disbursement creations never run at the same time for the same merchant on different payment
dates (for example, the historical backfill overlapping a daily run). If they did, both could see
the same pending orders: the one that assigns them first keeps them, and the other one could end up
with a disbursement without orders, which would be completed with amount 0. Orders are never paid
twice: the assignment only takes orders without a disbursement, and Postgres checks that again under
the row lock. Guarding against it (rolling back or deleting a disbursement left without orders) is
cheap but not free, so it is left out for a scenario that should not happen in this setup.

## November 2023 is a partial month in the provided data

The provided orders end on 2023-11-07, and the backfill of monthly fees covers up to November 2023
included. November fees therefore only count the commissions of the first 7 days, so they are higher
than they would be with the full month. In normal operation this does not happen: the monthly task
runs on the 1st and calculates the previous month, which is already closed.
