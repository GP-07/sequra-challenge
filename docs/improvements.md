# Improvements with more time

Detail of the improvements summarized in the [README](../README.md#improvements-with-more-time).

## Detecting packages that stay PENDING

If the message that enqueues a package is lost (for example, Redis loses it), the package stays
PENDING and no worker ever takes it. The daily check does not look at PENDING packages, so today
nothing alerts about it. The check could alert, or re-enqueue, the packages of the day still PENDING
some time after they were created.

## Inactive merchants

Today a live merchant keeps paying its full minimum every month, even after a long time without
orders. A merchant could move to an inactive status after a certain number of days without orders,
and stop being charged the monthly fee while it stays inactive.

## Visibility of the packages' status

Today it is followed through `check_package_status` and the logs. An API or a dashboard with the
status of the packages (completed, failed, stuck) would make it easier to follow the daily run and
the backfill.

## Creating orders one by one

New orders only enter today through the `load_orders` command. A `create_order` service (and a REST
endpoint on top of it) to create a single order with its commission would make it easy to keep
feeding the daily flow and test it end to end.

## A command to generate orders

A `generate_orders` command that creates random orders for existing merchants, for the same purpose:
exercising the daily creation, packaging and processing with fresh data.

## A backfill run id

Each run of `create_disbursements_for_range` would get an id that groups all the packages it
created, so their status can be followed by that single id instead of the list of package ids the
command prints.

## A limit on retries per run

Today the daily check only retries the packages of its own day (one or two on a normal day), and the
packages of a backfill are retried by hand, one by one. If failed packages were ever retried in bulk
(for example, all the failed packages of a backfill), a limit on how many packages are re-enqueued
per run would keep a database that is already failing from receiving hundreds of retries at once. It
would most likely build on the backfill run id above: retry the failed packages of a run, up to the
limit, and report the rest.
