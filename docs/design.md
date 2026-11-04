# Design and technical choices

Detail of the choices summarized in the [README](../README.md#technical-choices-and-trade-offs), where
the daily flow is described.

## Disbursements

- **Payment window (the run of day D pays closed days):** DAILY merchants are paid the orders of
  D-1. WEEKLY merchants are paid on the weekday of their `live_on`, with the orders from D-7 to D-1.
  The date of the disbursement is the payment date.
- **Delayed orders:** an order that arrives with a date before the window and was never paid goes
  into the next disbursement of its merchant. The disbursement is flagged with
  `has_processed_delayed_orders` and a WARNING is logged.
- **Exactly once:** each disbursement has a `natural_key_hash` (sha256 of merchant and payment date)
  with a unique constraint, so the same disbursement can never be created twice, even by two runs at
  the same time. Orders are assigned with an update that only takes orders without a disbursement,
  so an order is never paid twice. If the disbursement already exists, it is not touched, and orders
  that arrived later wait for the next payment.
- **Reference:** readable and unique, made of the merchant reference and the dates of the orders it
  pays: `padberg_group_for_20230201` (daily) or `padberg_group_from_20230125_to_20230131` (weekly).
- **No empty disbursements:** a disbursement is only created when the merchant has orders to pay.
- **Commissions** are calculated per order when the order comes in, and stored with it. A
  disbursement subtracts the sum of its orders' commissions from their gross amount.
- **Money** is stored as `Decimal` with 2 decimals, and amounts are rounded half-up.

## Packages

Disbursements are processed in packages (`DisbursementPackage`) of up to `PACKAGE_MAX_ORDERS` (5,000)
orders. A disbursement is never split across packages, and packages are built in a deterministic
order (payment date and merchant id), so the same data gives the same packages.

- A normal day fits in one or two packages; the backfill makes 281. Packages are not there to
  parallelize the daily run: they bound the work of each task, let each package be calculated with
  a single aggregated query, and let the backfill be processed by several workers.
- A disbursement with more orders than fit in a package goes into no package: it becomes
  `REQUIRES_ATTENTION` with a critical alert, to be processed by hand. It does not happen with the
  provided data (the largest disbursement has 1,965 orders).
- **Taking a package** is a single atomic `UPDATE` (PENDING/FAILED → PROCESSING) with the status
  condition in its `WHERE`, so two workers can never take the same package.
- **Processing** runs in one transaction: one aggregated query for the totals, validation in
  Python and bulk updates. The result belongs to each disbursement:
  - a disbursement with invalid totals (negative amounts, or commissions greater than the gross
    amount) becomes FAILED, not retryable, with its error, and the others are completed;
  - an infrastructure error (for example, the database goes down) rolls everything back and the
    unfinished disbursements become FAILED and retryable;
  - an unexpected error (a bug) does the same, but not retryable.
- The package is COMPLETED when all its disbursements are, and FAILED otherwise. Processing it again
  only touches the disbursements that are not COMPLETED, so it is idempotent.
- **Manual reprocessing**, after fixing the data: a whole package (`retry_disbursement_package`) or
  some disbursements by id (`retry_disbursements`). Never the whole day.

## Stuck packages

- A package can get stuck in PROCESSING if the worker dies while processing it: taking the package
  (PENDING/FAILED → PROCESSING) and calculating it are separate transactions, so the calculation is
  rolled back but the status stays. `release_stuck_packages` moves those packages to FAILED
  (retryable), so they can be retried with `retry_disbursement_package`.
- The daily package check (02:00, 04:00 and 06:00 UTC) does the same for the packages of the day
  before deciding anything else: a released package is retried in that same run, like any other
  retryable failure, or raises a critical alert if it is the last run. Packages left in PENDING
  (enqueued but never picked up by a worker) are not covered (see
  [improvements](improvements.md#detecting-packages-that-stay-pending)).
- It never touches a package a live worker is processing: the calculation transaction holds a lock
  on the package row (`SELECT ... FOR UPDATE`) until it ends, and the release looks for packages with
  `FOR UPDATE SKIP LOCKED`. When a worker dies, PostgreSQL releases its lock. On top of that, a
  package must be in PROCESSING for more than `PACKAGE_STUCK_AFTER_MINUTES` (5).
- A worker that is alive but hung on a query keeps the lock, so the calculation transaction also
  sets a `statement_timeout` (`PACKAGE_STATEMENT_TIMEOUT_SECONDS`, 5 s): the query is cancelled and
  the package fails as retryable. Measured on the full backfill in Docker with 4 workers, the slowest
  package took 0.30 s and the slowest query while processing 0.21 s.

## Monthly fees

On the 1st of each month, for each merchant that was live in the previous month and has a
`minimum_monthly_fee` greater than 0: if the commissions of the orders created in that month are
lower than the minimum, the difference is stored as a `MonthlyFee`. It is not deducted from any
disbursement. Existing fees are never recalculated, so running it twice changes nothing. The
backfill uses the same function through `calculate_monthly_fees_for_range`.

## Data loading

- `load_merchants` and `load_orders` read the CSV files from a folder mounted in Docker
  (`./import_data`). Invalid rows are skipped and reported with their line number; they do not stop
  the load. Both are idempotent by the CSV id.
- Merchant and order ids from the CSV are kept in `external_id` (unique, for lookups); the primary
  keys are database integer ids.
- `load_orders` works in batches, so it never keeps the whole file in memory. It loads the 1.3M
  provided orders in about 1 minute.

## Code organization and tests

- One Django app per domain: `merchants`, `orders`, `disbursements`, `disbursement_packages` and
  `fees`, plus `core` for what they share. An app never filters or updates another app's models
  directly: it calls queryset methods or services with business names (for example,
  `Order.objects.pending_disbursement_by_merchant`).
- Business logic lives in services; tasks and commands only call them.
- Tests use pytest against PostgreSQL (the same database as production), including real concurrency
  tests with threads for taking packages and releasing stuck ones. The creation tests run with both
  creation strategies, to make sure they give the same result.
