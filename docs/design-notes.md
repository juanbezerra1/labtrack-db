# Design notes

Why the schema looks the way it does, which traps I fell into while building it, and what I would
change on a database that is not a teaching one. Where a claim can be checked, a test in `tests/`
checks it (the test is named when it matters); the judgment calls are marked as opinions.

Contents: [Layout](#layout) · [Keys and types](#keys-and-types) · [Constraints that do real work](#constraints-that-do-real-work) ·
[Traps](#traps-i-fell-into) · [Migrations](#migrations) · [The synthetic data](#the-synthetic-data) ·
[Indexes](#indexes) · [Tests](#tests) · [At real scale](#what-would-change-at-real-scale)

## Layout

* `lab` holds the data, `bi` holds read-only views shaped as a star schema for dashboards, and
  nothing of the application lives in `public` except the bookkeeping table `schema_migrations`
  (and the objects of the `btree_gist` extension).
  A dedicated schema is easy to list, grant and drop; `public` is shared by everybody.
* The functions that generate the synthetic data live in a throw-away schema, `lab_seed`, which the
  last seed file drops. Nothing the application needs depends on it.
* Two cluster-wide roles, `labtrack_reader` and `labtrack_writer`, give least privilege: a dashboard
  can read everything and change nothing; the application can change rows but not the schema.
  (Row-level security is not used: nothing here is multi-tenant.)

## Keys and types

* **Surrogate keys** are `GENERATED ALWAYS AS IDENTITY`, the standard-SQL replacement for `serial`.
  `ALWAYS` means an `INSERT` that supplies the id is an error unless it says `OVERRIDING SYSTEM VALUE`,
  so nobody sets one by accident. The natural identifiers (`study.code`, `participant.code`,
  `device.serial_no`, `recording.sha256`) are `UNIQUE` as well: a surrogate key identifies the row for
  the database, the natural key identifies it for people.
* `integer` for the small tables, `bigint` for the ones that grow (`session`, `recording`, `trial`).
  `trial_feature` is by far the biggest table (about ten million rows at the large scale), so its
  columns are as narrow as they can be: `smallint` for the channel and the feature.
* **Junction tables** have a composite primary key instead of an extra id: `enrollment (study_id,
  participant_id)` makes "enrolled twice" impossible without any other rule.
* `timestamptz` for moments, `date` for calendar days, `numeric` with a fixed number of decimals for
  seconds (`trial.onset_s` is `numeric(8,3)`: exact decimals; `double precision` only for the computed
  feature values, where rounding is part of the nature of the number). `participant.birth_year` is a year, not a date: enough for age analyses, not enough to
  identify a person.
* **Enums or CHECK?** Six closed vocabularies that code branches on or that are shared by several
  places are enums (`researcher_role`, `hand`, `device_kind`, `session_status`, `modality`, `qc_status`):
  4 bytes, readable, sorted in declaration order. A short list private to one column (`sex`,
  `group_label`, `channel.unit`) is a `CHECK (... IN (...))`. The difference is that you can add a
  value to an enum but never remove one, whereas a CHECK can be dropped and re-added in a migration.
  The third option, a lookup table with a foreign key, is the right answer when the list changes often or
  carries attributes (`feature_def` is exactly that). The line between the first two is a judgment call.

## Constraints that do real work

A constraint is a rule the database refuses to let anyone break, whatever the application does.
These are the ones worth reading, with the name the error message gives:

| Rule | Mechanism | Name |
|---|---|---|
| A session exists only for a participant who is enrolled in that study | composite foreign key `(study_id, participant_id)` → `enrollment` | `session_enrollment_fk` |
| A recording can only use a device that was booked for **its** session | composite foreign key `(session_id, device_id)` → `session_device` | `recording_session_device_fk` |
| Two active sessions never overlap in the same room | exclusion constraint, GiST on `(room =, during &&)`, only for `scheduled` and `completed` | `session_room_no_overlap` |
| A session ends after it starts and lasts at most six hours | `CHECK` | `session_times_ordered`, `session_max_length` |
| A valid trial has no rejection reason; a rejected one must have one | `CHECK ((valid AND reason IS NULL) OR (NOT valid AND reason IS NOT NULL))` | `trial_reason_iff_rejected` |
| A feature value is a finite number | `CHECK` (and `NaN` is tested explicitly, see below) | `trial_feature_finite` |
| No session before consent, enrollment or the study's start; none after withdrawal or the study's end | `BEFORE` trigger, because a `CHECK` cannot read other tables | `session_before_consent`, `session_before_enrollment`, `session_outside_study`, `session_after_withdrawal` |

The trigger raises `check_violation` (SQLSTATE 23514) and names the rule as `CONSTRAINT`, so a client
handles it exactly like a failed `CHECK`.

**What constraints do not do.** A constraint guards writes to the table it is attached to. If a
participant's withdrawal date is moved back *after* sessions were booked, the trigger on `session` does
not fire and the old sessions silently become wrong. That is why the project also has `labtrack check`:
twelve queries that must always return zero rows, run in the tests and meant to run on a schedule.
A rule that spans tables needs either triggers on every table involved or a periodic check; this
project uses one trigger for the common path and the checks as the safety net.

## Traps I fell into

1. **A generated column is computed before the CHECK constraints run.** `session.during` is
   `tstzrange(starts_at, ends_at)`. Insert a session whose end is *before* its start and PostgreSQL
   raises its range error (`data_exception`, 22000) while computing the column, before
   `session_times_ordered` ever gets a say; only an end *equal* to the start reaches the CHECK. Both
   cases are tested. Lesson: with generated columns, the order of evaluation decides which error the
   client sees.
2. **`NOT NULL` through a CHECK needs `IS NOT NULL` inside the CHECK.** A CHECK passes when its
   expression is true *or null*, so `protocol_version ~ '^v[0-9]+$'` lets a NULL through. Only
   `CHECK (protocol_version IS NOT NULL AND ...)`, once validated, lets PostgreSQL skip the full scan
   that `SET NOT NULL` would otherwise do. The test turns on `client_min_messages = debug1` and looks
   for the server's own message that it skipped the scan.
3. **A migration is one transaction, and locks last until the transaction ends.** `ADD CONSTRAINT`
   takes a strong lock; if the long `VALIDATE CONSTRAINT` shared its transaction, the strong lock would
   be held for the whole scan. Hence four small files (0008 to 0011) for what looks like one change,
   and a test that checks `VALIDATE` really takes only `SHARE UPDATE EXCLUSIVE`.
4. **`CREATE INDEX CONCURRENTLY` cannot run inside a transaction.** The runner supports a file marked
   `-- labtrack: no-transaction` (one statement only, so a failure cannot leave half a file applied).
   An aborted concurrent build leaves an `INVALID` index behind that must be dropped by hand.
5. **PostgreSQL does not index the referencing side of a foreign key.** Primary keys and `UNIQUE`
   get an index; `session.researcher_id` does not, until you create one. Every foreign key here has an
   index that starts with its first column, with one deliberate exception, `trial_feature.feature_id`
   (the EXPLAIN lab builds that index as lesson 1). The test
   `test_every_foreign_key_has_an_index_that_serves_it` lists the exception, so a new foreign key
   without an index fails the build.
6. **An index you already have.** `UNIQUE (device_id, performed_on)` is already the index for "latest
   calibration of a device", because a B-tree can be read backwards. A second index on
   `(device_id, performed_on DESC)` was pure overhead and was removed.
7. **`NaN = NaN` is true in PostgreSQL** (unlike most languages), and it sorts above every other
   number. A `CHECK (value <> 'NaN')` is therefore a real test, and infinities are refused separately.
8. **Days depend on the time zone.** The trigger turns `starts_at` into a day with an explicit
   `AT TIME ZONE 'America/Sao_Paulo'`, never with the client's `TimeZone` setting; otherwise the same
   insert would pass or fail depending on who ran it.
9. **A half-open range lets sessions touch.** `tstzrange(a, b)` includes `a` and excludes `b`, so one
   session may end at 10:00 and the next start at 10:00 in the same room.
10. **`btree_gist` is needed for the exclusion constraint** (equality on `room` plus overlap on the
    range in one GiST index). It ships with PostgreSQL as a *trusted* extension, so the database owner
    can create it without being a superuser.

## Migrations

The runner (`src/labtrack/migrate.py`, under 200 lines) is deliberately small, to show what Flyway,
sqitch or Alembic do for you; in a real project use one of those. What it guarantees:

* each migration and the row that records it commit together, or neither does;
* the file's SHA-256 (line endings normalised, so Windows checkouts agree) is stored, and changing an
  applied file is an error with a message that says what to do;
* a file whose migration was applied but is now missing, two files with the same number, and a new
  file numbered below one that is already applied are all errors (gaps in the numbering are not);
* an advisory lock keeps two runners apart.

There are no down-migrations: a database in use rolls *forward* (a bad change is fixed by another
migration). The one-way policy is an opinion, and the usual one for teams that restore from backup when
they must go back.

## The synthetic data

* **Why not `random()`.** The server's own generator is only repeatable within one version:
  PostgreSQL 15 replaced the algorithm behind `random()`, and the documentation promises nothing more
  than "deterministic". Every number here instead comes from `md5()` of a text key (first 52 bits,
  divided by 2^52), so the same seed gives the same rows on any machine and any server version. The
  tests compare an md5 of every row of every table across two runs.
* **Only `+ - * /` and rounding to three decimals** are used to turn those numbers into values, because
  `exp`, `ln` and friends may differ in the last digits between platforms.
* **The calendar is a queue.** Each study owns two rooms with five two-hour windows a day; every visit
  wants a date ("about a week after the last one") and gets the first free window not earlier than
  that. Because no two sessions share a window, the exclusion constraint holds by construction
  instead of by retrying. The allocation is a window-function closed form, not a loop.
* **Effects are planted on purpose** (feedback lowers force variability, fatigue lowers EMG frequency,
  a large visual stimulus lowers alpha power) so the teaching queries have something to find. They are
  not science. Do not read the numbers as evidence of anything.
* **Privacy by construction.** Participants have a code and a birth year, researchers have invented
  names and addresses under `.example` (a reserved domain), and the link to a real person, if any,
  would live outside this database.

## Indexes

The policy is "the primary keys, the indexes that foreign keys need, and nothing else until a query
asks for it". `trial_feature` keeps only its primary key on purpose: the EXPLAIN lab adds an index per
lesson inside a transaction it then rolls back (DDL is transactional in PostgreSQL), measures the
plan before and after, and leaves the database untouched. The one index added later by a migration,
`recording (recorded_at)`, exists to show the concurrent build.

## Tests

* They run against a real PostgreSQL (`LABTRACK_TEST_DSN`), in throw-away databases with random names;
  a mock cannot tell you what an exclusion constraint does.
* Each constraint test runs in a transaction that is rolled back, with a savepoint around the statement
  that is expected to fail, so one failure does not abort the rest.
* Query results are compared with golden JSON files (`pytest --update-golden` rewrites them; review
  the diff in git). Row counts and per-table md5 digests pin the seed.
* The EXPLAIN lessons assert the **shape** of the plan (a `Seq Scan` before, an `Index Scan` after),
  never a duration: timings depend on the machine, plan shapes mostly on the data and the version.
  The shapes were checked on PostgreSQL 16 only, which is why CI uses 16.

## What would change at real scale

None of this is implemented; it is the list I would start from.

* `trial_feature` is the table to partition (by hash or range of `trial_id`) once it reaches hundreds
  of millions of rows; the primary key already starts with `trial_id`, which a partition key must be
  part of.
* A BRIN index on `recording.recorded_at` would be far smaller than the B-tree if rows arrive in time
  order, which they do here and might not in production.
* The raw signals stay out of the database (`storage_uri` points at them); keep it that way.
* Dashboards should read from a replica or a separate warehouse, not from the database that accepts
  writes; the `bi` views are written so that moving them is a copy.
* Put a connection pooler in front of it as soon as more than a few dozen clients connect.
