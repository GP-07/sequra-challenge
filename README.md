# Merchant disbursements

## Running with Docker

Services: `db` (PostgreSQL), `redis` (huey queue), `migrate` (applies migrations and exits) and
`worker` (huey consumer with the periodic tasks, times in UTC). Commands run in the `app` service.

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
processes them in the background (`HUEY_WORKERS`, 4 by default), so run `yearly_report` once the worker has finished
(`docker compose logs -f worker`). Tests run against their own in-memory PostgreSQL
(`db_test`), separate from the data:

```bash
docker compose run --rm test
docker compose --profile test stop db_test
```

### Following the packages of a backfill

```bash
docker compose run --rm app python manage.py check_package_status --from 2022-09-05 --to 2023-11-08
docker compose run --rm app python manage.py release_stuck_packages <package ids>
docker compose run --rm app python manage.py retry_disbursement_package <package id>
```

- `check_package_status` counts the packages by status (pending, processing, completed, failed),
  by id or by the payment dates of the backfill, and lists the failed and processing ones.
- A package can get stuck in PROCESSING if the worker dies while processing it: taking the package
  (PENDING/FAILED → PROCESSING) and calculating it are separate transactions, so the calculation is
  rolled back but the status stays. `release_stuck_packages` moves those packages to FAILED
  (retryable), so they can be retried with `retry_disbursement_package`.
- The daily package check (02:00, 04:00 and 06:00 UTC) does the same for the packages of the day
  before deciding anything else: a released package is retried in that same run, like any other
  retryable failure, or raises a critical alert if it is the last run. Packages left in PENDING
  (enqueued but never picked up by a worker) are not covered yet.
- It never touches a package a live worker is processing: the calculation transaction holds a lock
  on the package row (`SELECT ... FOR UPDATE`) until it ends, and the release looks for packages with
  `FOR UPDATE SKIP LOCKED`. When a worker dies, PostgreSQL releases its lock. On top of that, a
  package must be in PROCESSING for more than `PACKAGE_STUCK_AFTER_MINUTES` (5).
- A worker that is alive but hung on a query keeps the lock, so the calculation transaction also
  sets a `statement_timeout` (`PACKAGE_STATEMENT_TIMEOUT_SECONDS`, 5 s): the query is cancelled and
  the package fails as retryable. Measured on the full backfill in Docker with 4 workers, the slowest
  package took 0.30 s and the slowest query while processing 0.21 s.

## Assumptions

- **Two disbursement creations never run at the same time for the same merchant on different
  payment dates** (for example, the historical backfill overlapping a daily run). If they did, both
  could see the same pending orders: the one that assigns them first keeps them, and the other one
  could end up with a disbursement without orders, which would be completed with amount 0. Orders
  are never paid twice: the assignment only takes orders without a disbursement, and Postgres checks
  that again under the row lock. Guarding against it (rolling back or deleting a disbursement left
  without orders) is cheap but not free, so it is left out for a scenario that should not happen in
  this setup.

## Improvements with more time

- **Creating orders one by one (`create_order`).** New orders only enter today through the
  `load_orders` command. A service (and a REST endpoint on top of it) to create a single order with
  its commission would make it easy to keep feeding the daily flow and test it end to end.
- **A `generate_orders` command** that creates random orders for existing merchants, for the same
  purpose: exercising the daily creation, packaging and processing with fresh data.
- **A backfill run id.** Each run of `create_disbursements_for_range` would get an id that groups
  all the packages it created, so their status can be followed by that single id instead of the
  list of package ids the command prints.

## Notes on the provided data

- **November 2023 monthly fees are calculated over a partial month.** The provided orders end on
  2023-11-07, and the backfill of monthly fees covers up to November 2023 included. November fees
  therefore only count the commissions of the first 7 days, so they are higher than they would be
  with the full month. In normal operation this does not happen: the monthly task runs on the 1st
  and calculates the previous month, which is already closed.

## Historical backfill: bulk creation of disbursements

Disbursements are created with two strategies that give the same result:

- **Daily run (`create_disbursements`):** one transaction per merchant. If one merchant fails, the
  rest are created anyway.
- **Historical backfill (`create_disbursements_for_range` → `create_disbursements_in_bulk`):** one
  transaction and a fixed number of queries per payment date and frequency, whatever the number of
  merchants: one insert for all the disbursements of the day and one update that assigns all their
  orders.

Trade-offs accepted for the backfill only:

- If anything fails, the whole day is rolled back instead of a single merchant.
- If another run creates one of the same disbursements at the same time, the unique constraint on
  `natural_key_hash` stops the day with an `IntegrityError`. There are never duplicates, but the day
  has to be run again.

Both are acceptable because the backfill is run manually, once, and it is idempotent: running it
again skips the disbursements that already exist. The creation tests run with both strategies to
make sure they do not drift apart.

### If a day fails, the backfill stops

`create_disbursements_for_range` stops at the first payment date whose creation fails, reports which
day failed and why, and does not create any package. The days before it stay created, as PENDING
disbursements without a package, so nothing of the range is paid yet.

It does not skip the failing day and go on, on purpose. Going on would leave a partial result that
looks complete: someone could read it right away without knowing a day is missing. Worse, the orders
of the failed day would not wait for it: the next payment date would take them as delayed orders,
so they would be paid on the wrong date and flagged as delayed when they were not, and the numbers
per date would change silently. Stopping keeps the data trustworthy: either the range is complete,
or it is clearly unfinished. Running the command again over the same range is safe, because
existing disbursements are skipped.

Packages of the range left PENDING or FAILED by a previous run are only reported, with their ids,
to be retried with `retry_disbursement_package`; the command does not enqueue them again.

Measured with the provided data (payment dates 2022-09-05 to 2023-11-08, 11,889 disbursements,
1,309,023 orders, local PostgreSQL), creation only:

| Strategy | Time |
| --- | --- |
| One transaction per merchant | 123 s |
| Bulk per day | 71–74 s |

Both runs created exactly the same disbursements and assigned the same orders. The first number was
measured while disbursements still stored an `order_count` (one extra update per disbursement), so
the gap today is somewhat smaller. Identical runs varied by up to ~10 s, so differences below that
are noise.

Most of the bulk time is assigning the orders to their disbursements. Alternatives measured for that
step, inside the bulk strategy:

| Order assignment | Update queries | Time |
| --- | --- | --- |
| One `UPDATE ... CASE WHEN merchant ...` per day | 717 | 50 s |
| One `UPDATE` per merchant | 11,889 | 61 s |
| One `UPDATE` per merchant, in batches of 1,000 orders | 24,004 | 2,907 s |

The batched version was discarded: each batch (`id IN (SELECT ... ORDER BY id LIMIT n)`) has to
look again through the merchant's orders, and most disbursements have far fewer than 1,000 orders
(median 28, max 1,965), so batching only adds queries.

### Partial index on pending orders

Orders have a partial index `(merchant_id, order_creation_date) WHERE disbursement_id IS NULL`, so
the search for pending orders only touches the orders not yet disbursed instead of the whole history
of each merchant. One run each (backfill creation, packaging, and a second backfill run that finds
nothing to create, which is the closest to a normal daily run where almost every order is already
disbursed):

| Schema | Creation | Packaging | Second run |
| --- | --- | --- | --- |
| Before (CSV ids as primary keys) | 73.5 s | 1.3 s | 12.3 s |
| Integer primary keys, packages ordered by `merchant_id` | 87.7 s | 1.4 s | 14.9 s |
| Same, plus the partial index | 82.2 s | 1.3 s | 0.9 s |

All three assigned exactly the same orders. Switching to integer primary keys (the CSV ids are kept
in `external_id` for lookups) did not make a measurable difference here. The partial index barely
changes the backfill, where every order starts pending, but it removes almost all the cost of
looking for pending orders once most of them are disbursed.
