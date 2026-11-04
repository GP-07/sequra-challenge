# Merchant disbursements

Calculation of seQura's merchant disbursements, order commissions and monthly fees, built with
Django 5.2, PostgreSQL and huey (Redis). It processes the provided history (backfill) and is ready to
run every day for new orders.

## Yearly report

Result of the backfill with the provided data (`yearly_report`):

| Year | Number of disbursements | Amount disbursed to merchants | Amount of order fees | Number of monthly fees charged | Amount of monthly fees charged |
| --- | --- | --- | --- | --- | --- |
| 2022 | 1,509 | 36,929,320.27 € | 333,677.15 € | 31 | 566.76 € |
| 2023 | 10,380 | 187,802,783.37 € | 1,702,434.68 € | 120 | 2,048.25 € |

- Disbursements count by year of their payment date, and only the COMPLETED ones. The amount
  disbursed is what is paid to the merchant (gross amount minus commissions).
- Monthly fees count by year of the month they cover: December's fee is calculated on January 1st,
  but it counts in December's year.
- November 2023 is a partial month in the provided data (see
  [assumptions](docs/assumptions.md#november-2023-is-a-partial-month-in-the-provided-data)).

## Setup and running

Requirements: Docker with Docker Compose.

Services: `db` (PostgreSQL), `redis` (huey queue), `migrate` (applies migrations and exits) and
`worker` (huey consumer with the periodic tasks, times in UTC). Commands run in the `app` service.
The database is published on `localhost:5433` (database `disbursements`, user and password
`postgres`; change the port with `DB_PORT`).

```bash
docker compose up -d
```

Historical load and backfill (the CSV files go in `./import_data`, which is mounted in the
containers):

```bash
docker compose run --rm app python manage.py load_merchants merchants.csv
docker compose run --rm app python manage.py load_orders orders.csv
docker compose run --rm app python manage.py create_disbursements_for_range --from 2022-09-05 --to 2023-11-08
docker compose run --rm app python manage.py calculate_monthly_fees_for_range --from 2022-09 --to 2023-11
docker compose run --rm app python manage.py yearly_report
```

`create_disbursements_for_range` only enqueues the packages and prints their ids; the `worker`
processes them in the background (`HUEY_WORKERS`, 4 by default), so run `yearly_report` once the
worker has finished (`docker compose logs -f worker`).

Following and fixing the packages of a backfill:

```bash
docker compose run --rm app python manage.py check_package_status --from 2022-09-05 --to 2023-11-08
docker compose run --rm app python manage.py release_stuck_packages <package ids>
docker compose run --rm app python manage.py retry_disbursement_package <package id>
```

- `check_package_status` counts the packages by status, by id or by the payment dates of the
  backfill, and lists the failed and processing ones.
- `release_stuck_packages` moves to FAILED (retryable) the packages stuck in PROCESSING because
  their worker died, so they can be retried (see [stuck packages](docs/design.md#stuck-packages)).
- `retry_disbursement_package` reprocesses a package by hand; `retry_disbursements` does the same
  for some disbursements by id.

Trying the daily flow with test data. `generate_testing_orders` creates 2 new DAILY merchants and
from 2 to 50 orders for them (50 by default), dated yesterday. Each merchant gets at least one order
and the rest are spread at random; amounts are random and cover the three commission tiers. Then the
daily task can be enqueued by hand instead of waiting for 00:05, and the worker log shows creation →
packaging → processing:

```bash
docker compose run --rm app python manage.py generate_testing_orders --count 20
docker compose run --rm app python manage.py shell -c "from disbursements.tasks import create_disbursements_task; create_disbursements_task()"
docker compose run --rm app python manage.py check_package_status --from <today> --to <today>
```

These are test data only. In production, orders would come in through a REST API, with serializers
validating the input (see [improvements](docs/improvements.md#creating-orders-through-a-rest-api)).

Tests run against their own in-memory PostgreSQL (`db_test`), separate from the data:

```bash
docker compose run --rm test
docker compose --profile test stop db_test
```

## Technical choices and trade-offs

### Daily flow

Times in UTC. Processing has to be finished by 08:00.

| Task | When | What it does |
| --- | --- | --- |
| `create_disbursements_task` | 00:05 | Creates the DAILY and then the WEEKLY disbursements of the day. When it finishes, it enqueues the packaging. |
| `create_disbursement_packages_task` | Enqueued by the creation | Groups the day's disbursements into packages and enqueues one `process_disbursement_package` per package. |
| `process_disbursement_package` | Enqueued, one per package | Calculates the totals of each disbursement of the package. |
| `check_disbursement_packages_task` | 02:00, 04:00, 06:00 | Releases stuck packages and retries the failed ones that can be retried. The last run only alerts. |
| `calculate_monthly_fees_task` | Day 1, 00:30 | Calculates the monthly fees of the previous month. |

- **Packaging has no schedule of its own:** the creation enqueues it when it finishes, so it always
  runs after the creation, never before or at the same time.
- **Retries:** the creation is retried by huey twice, every 10 minutes, with a critical alert on the
  last attempt; it is idempotent. A failed package is retried by the next check, up to
  `PACKAGE_MAX_RETRIES` (2) times. The last check, at 06:00, leaves 2 hours before 08:00 to act on
  its alerts.
- **Alerts** go through a single function (`disbursements/alerts.py`), which today writes ERROR or
  CRITICAL logs. Connecting it to a real notification channel is a change in one place.

### Summary

- **Disbursements:** the run of day D pays closed days (DAILY: D-1; WEEKLY: D-7 to D-1, on the
  weekday of `live_on`). Exactly once is enforced by a unique hash of merchant and payment date, and
  orders are only assigned if they have no disbursement yet. Delayed orders go into the next
  disbursement. [More](docs/design.md#disbursements)
- **Packages:** disbursements are processed in packages of up to 5,000 orders, never splitting a
  disbursement. A normal day fits in one or two packages; they bound the work of each task and let
  the backfill run on several workers. A package is taken with a single atomic `UPDATE`, so two
  workers never process the same one. [More](docs/design.md#packages)
- **Results per disbursement:** a disbursement with invalid data fails on its own and the rest of
  its package is completed; an infrastructure error rolls the package back and leaves it retryable.
  Reprocessing only touches what is not completed, so it is idempotent.
  [More](docs/design.md#packages)
- **Stuck packages:** the calculation holds a row lock and a 5 s `statement_timeout`, so a package
  whose worker died can be detected (no lock) and released without touching one a live worker is
  processing. [More](docs/design.md#stuck-packages)
- **Monthly fees:** calculated on the 1st for the previous month and stored, not deducted from any
  disbursement; idempotent. [More](docs/design.md#monthly-fees)
- **Historical backfill:** creates disbursements in bulk, one transaction per day, instead of one per
  merchant (123 s → about 72 s for the whole history). Trade-off accepted for the backfill only: a
  failure rolls back the whole day. If a day fails, the backfill stops instead of skipping it, so
  the result is either complete or clearly unfinished.
  [More](docs/backfill.md#bulk-creation-of-disbursements)
- **Performance:** a partial index on pending orders makes the search for orders to pay almost free
  once most orders are paid (14.9 s → 0.9 s for a run with nothing to create). The whole backfill
  is processed by 4 workers in about 7 s. [Measurements](docs/backfill.md#measurements)
- **Data loading:** CSV files are loaded in batches, skipping and reporting invalid rows; both loads
  are idempotent. [More](docs/design.md#data-loading)
- **Code and tests:** one Django app per domain, business logic in services, and pytest tests against
  PostgreSQL, including real concurrency tests. [More](docs/design.md#code-organization-and-tests)

## Assumptions

- Dates are in UTC, and orders only have a date; an order arrives at least one day later.
  [More](docs/assumptions.md#dates-and-order-arrival)
- An order of exactly 50 € pays 0.95%, and one of exactly 300 € pays 0.85%.
  [More](docs/assumptions.md#commission-tiers)
- Orders with amount 0 are valid; an empty minimum is loaded as 0.
  [More](docs/assumptions.md#valid-amounts)
- The monthly fee counts every order created in the month, paid or not: charging the order is
  seQura's responsibility, not the merchant's.
  [More](docs/assumptions.md#monthly-fee-over-every-order-of-the-month-paid-or-not)
- A month without orders pays the whole minimum.
  [More](docs/assumptions.md#a-month-without-orders-pays-the-whole-minimum)
- The first month is not prorated. [More](docs/assumptions.md#the-first-month-is-not-prorated)
- In the yearly report, disbursements count by payment date and monthly fees by the month they
  cover. [More](docs/assumptions.md#yearly-report)
- Two creations never run at the same time for the same merchant on different payment dates.
  [More](docs/assumptions.md#no-concurrent-creations-for-the-same-merchant)

## Improvements with more time

- Detecting packages that stay PENDING because their message was lost.
  [More](docs/improvements.md#detecting-packages-that-stay-pending)
- Inactive merchants, which stop paying the monthly fee after some time without orders.
  [More](docs/improvements.md#inactive-merchants)
- An API or dashboard with the status of the packages.
  [More](docs/improvements.md#visibility-of-the-packages-status)
- Creating orders through a REST API, with serializers validating the input.
  [More](docs/improvements.md#creating-orders-through-a-rest-api)
- A backfill run id, to follow all its packages by a single id.
  [More](docs/improvements.md#a-backfill-run-id)
- A limit on retries per run. [More](docs/improvements.md#a-limit-on-retries-per-run)
