# Historical backfill

Detail of the backfill summarized in the [README](../README.md#technical-choices-and-trade-offs).

## Bulk creation of disbursements

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

## If a day fails, the backfill stops

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

## Measurements

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
