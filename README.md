# labtrack-db

[![CI](https://github.com/juanbezerra1/labtrack-db/actions/workflows/ci.yml/badge.svg)](https://github.com/juanbezerra1/labtrack-db/actions/workflows/ci.yml)

**A PostgreSQL schema for a biosignal lab, built to be read, run and broken.**

The lab is invented (participants, study visits, devices and their calibrations, EMG and EEG recordings, trials,
and the features computed from them) and so is every row. What is real is the engineering: a schema whose
constraints refuse bad data, a small migration runner, a deterministic data generator in four sizes, teaching
queries, EXPLAIN lessons, a star schema with CSV exports for dashboards, and a test-suite that runs against a real
PostgreSQL. I work with EMG and EEG experiments, so the domain is one I know; none of the data comes from them.

Também em português: [README.pt-BR.md](README.pt-BR.md)

## At a glance

| | |
|---|---:|
| Tables in schema `lab` | 13 |
| Foreign keys between them | 13 |
| Enum types | 6 |
| Migrations | 13 |
| Teaching queries | 12 |
| EXPLAIN lessons | 8 |
| Data-quality checks | 12 |
| Sizes of synthetic data | 4 |

If you only have five minutes, read in this order: the [schema diagram](#the-schema),
[`docs/design-notes.md`](docs/design-notes.md) (why it looks like this, and ten traps I fell into), one of the
[queries](queries/) (each is commented like a lesson), and [`tests/test_constraints.py`](tests/test_constraints.py).

## Quick start

You need Python 3.10 or newer and a PostgreSQL 16 server. The easiest server is the one in
[`docker-compose.yml`](docker-compose.yml):

```bash
git clone https://github.com/juanbezerra1/labtrack-db.git
cd labtrack-db
docker compose up -d --wait        # PostgreSQL 16 on localhost:5432 (user, password and database: labtrack)
python3 -m venv .venv              # Windows: py -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1   (cmd.exe: .venv\Scripts\activate.bat)
python -m pip install -e .         # Windows: py -m pip install -e .
labtrack migrate                   # creates the schema
labtrack seed --scale small        # synthetic data, about 10 seconds
labtrack check                     # the data-quality checks
labtrack query 10                  # one of the teaching queries
```

The last two commands print this (the data is the same on every machine):

```console
$ labtrack check
  ok   room_double_booked
  ok   visits_out_of_order
  ok   completed_without_recording
  ok   recording_outside_session
  ok   recording_of_uncompleted_session
  ok   trial_beyond_recording
  ok   feature_for_missing_channel
  ok   feature_of_wrong_modality
  ok   channel_count_mismatch
  ok   session_after_withdrawal
  ok   device_used_after_retirement
  ok   researcher_not_employed
12 of 12 checks passed
```

```console
$ labtrack query 10
-- Query 10: does the feedback lower force variability, and does it depend on the group?
group_label  | values_used | feedback_on | feedback_off | difference
-------------+-------------+-------------+--------------+-----------
control      |        1559 |       4.342 |        4.517 |     -0.175
intervention |        1279 |       3.717 |        4.539 |     -0.821
(2 rows)
```

Query 10 asks whether the feedback lowers the variability of the force, per group. It does, and more in the
intervention group: that is one of the effects the generator plants on purpose
([below](#what-is-planted-in-the-data)).

Things that go differently on your machine:

* **Port 5432 is taken.** Start the server with `LABTRACK_PORT=5433 docker compose up -d --wait` (PowerShell:
  `$env:LABTRACK_PORT = "5433"; docker compose up -d --wait`) and pass
  `--dsn postgresql://labtrack:labtrack@localhost:5433/labtrack` before the command name
  (`labtrack --dsn ... status`), or set the environment variable `LABTRACK_DSN` once.
* **No Docker.** Use a PostgreSQL 16 you already have, with a user that may create databases:
  `export LABTRACK_DSN=postgresql://USER:PASSWORD@localhost:5432/labtrack` (PowerShell:
  `$env:LABTRACK_DSN = "..."`), then `labtrack createdb` and `labtrack migrate`. `psql` is not needed.
* **PowerShell will not activate the environment** ("running scripts is disabled on this system"). Run
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and open a new window, or use `cmd.exe` and
  `.venv\Scripts\activate.bat`.

## The schema

```mermaid
erDiagram
    study ||--o{ enrollment : "has"
    participant ||--o{ enrollment : "joins"
    enrollment ||--o{ session : "session_enrollment_fk"
    researcher ||--o{ session : "runs"
    researcher ||--o{ calibration : "performs"
    device ||--o{ calibration : "has"
    session ||--o{ session_device : "books"
    device ||--o{ session_device : "is booked"
    session_device ||--o{ recording : "recording_session_device_fk"
    recording ||--o{ channel : "has"
    recording ||--o{ trial : "has"
    trial ||--o{ trial_feature : "has"
    feature_def ||--o{ trial_feature : "defines"

    study {
        integer study_id PK
        text code UK
        text title
        date started_on
        date ended_on
    }
    participant {
        integer participant_id PK
        text code UK
        smallint birth_year
        date consent_signed_on
        date withdrawn_on
    }
    enrollment {
        integer study_id PK, FK
        integer participant_id PK, FK
        text group_label
        date enrolled_on
    }
    researcher {
        integer researcher_id PK
        text full_name
        researcher_role role
        text email UK
    }
    device {
        integer device_id PK
        device_kind kind
        text serial_no UK
        text home_room
        date retired_on
    }
    calibration {
        integer calibration_id PK
        integer device_id FK
        date performed_on
        integer performed_by FK
        boolean passed
        date valid_until
    }
    session {
        bigint session_id PK
        integer study_id FK
        integer participant_id FK
        integer researcher_id FK
        smallint visit_no
        text room
        timestamptz starts_at
        timestamptz ends_at
        session_status status
        tstzrange during "generated"
    }
    session_device {
        bigint session_id PK, FK
        integer device_id PK, FK
    }
    recording {
        bigint recording_id PK
        bigint session_id FK
        integer device_id FK
        modality modality
        smallint block_no
        timestamptz recorded_at
        char(64) sha256 UK
        qc_status qc
    }
    channel {
        bigint recording_id PK, FK
        smallint channel_no PK
        text label
    }
    trial {
        bigint trial_id PK
        bigint recording_id FK
        integer trial_no
        text condition
        boolean valid
    }
    feature_def {
        smallint feature_id PK
        modality modality
        text name
    }
    trial_feature {
        bigint trial_id PK, FK
        smallint channel_no PK
        smallint feature_id PK, FK
        float8 value
    }
```

Only the main columns are drawn; the [data dictionary](docs/data-dictionary.md) lists all of them. It is generated
from the `COMMENT`s in the migrations, and a test fails when the file is out of date. `PK` is a primary key, `FK` a
foreign key and `UK` a unique natural key.

Three layers: `lab` holds the data (the tables above, four `v_` views for everyday questions and one materialized
view), `bi` holds eight read-only views shaped as a star schema for dashboards (see [Dashboards](#dashboards)), and
`public` holds only the migration bookkeeping table. Two roles give least privilege: `labtrack_reader` reads
everything and changes nothing; `labtrack_writer` changes rows but not the schema.

### Rules the database enforces

A constraint is a rule that the database refuses to let anyone break, whatever the application does.

| Rule | Mechanism | Name |
|---|---|---|
| A session exists only for a participant who is enrolled in that study | composite foreign key to `enrollment` | `session_enrollment_fk` |
| A recording uses only a device that was booked for its own session | composite foreign key to `session_device` | `recording_session_device_fk` |
| Two active sessions never overlap in the same room | exclusion constraint (GiST, `btree_gist`) | `session_room_no_overlap` |
| A rejected trial has a reason and a valid one has none | `CHECK` | `trial_reason_iff_rejected` |
| No session before consent, enrollment or the study's start; none after withdrawal or the study's end | `BEFORE` trigger, because a `CHECK` cannot read other tables | `session_before_consent`, `session_before_enrollment`, `session_outside_study`, `session_after_withdrawal` |

The trigger raises `check_violation` (SQLSTATE 23514) and names the rule as the constraint, so a client handles it
like a failed `CHECK`. A constraint guards writes to its own table only: if a participant's withdrawal date is moved
back after sessions were booked, nothing fires. That is why `labtrack check` exists, with queries that must always
find nothing. [`docs/design-notes.md`](docs/design-notes.md) explains these choices and the traps behind them
(a generated column is computed before the `CHECK`s run, a `CHECK` lets a `NULL` through, `NaN = NaN` is true…).
In [`tests/test_constraints.py`](tests/test_constraints.py) every `CHECK`, `UNIQUE` and exclusion constraint has a
test that must make it fail, and one test fails when someone adds a constraint without a test.

## Sizes

`labtrack seed --scale SIZE` fills the tables with synthetic data. It is deterministic: the same size and the same
`--as-of` date give the same rows on any machine and any PostgreSQL version (no `random()`, no `now()`; the numbers
come from `md5()` of a text key). The default is `small`.

| Size | Participants | Sessions | Recordings | Trials | Feature values | Database size | Seed time |
|---|---:|---:|---:|---:|---:|---:|---:|
| `tiny` | 20 | 86 | 152 | 4,257 | 105,480 | 19 MB | 5 s |
| `small` | 60 | 261 | 460 | 12,907 | 314,368 | 37 MB | 10 s |
| `medium` | 200 | 909 | 1,634 | 45,806 | 1,105,112 | 106 MB | 30 s |
| `large` | 1,800 | 8,412 | 15,008 | 421,237 | 10,378,232 | 912 MB | 4 min 19 s |

The row counts of `tiny`, `small` and `medium` are pinned by golden files, and a test seeds twice and compares an
md5 digest of every table. `large` was measured once and is not part of the test-suite. Disk and time were measured on the machine described
in the [EXPLAIN lab](#explain-lab) section; yours will differ. The EXPLAIN lessons need `medium` or larger,
because the planner picks other plans on small tables.

## What is planted in the data

The generator plants a few things on purpose, so that the queries have something to find. They are **not science**:
do not read the numbers as evidence of anything.

* **Three effects.** The feedback lowers the variability of the force, more in the intervention group: query 10.
  After the fatiguing task of EMG-03 the median EMG frequency falls and the RMS rises. A large visual stimulus lowers
  alpha power, which is strongest at the occipital channels anyway. No numbered query looks at the last two, so they
  are an exercise: write the query.
* **Devices with a story.** Every device is calibrated every 90 days and each calibration covers 120 days, except
  these. The third column is what `lab.v_device_status` says on the seed's "today", 2026-10-31.

| Device | What was planted | Status on 2026-10-31 |
|---|---|---|
| `SN-EMG-03`, `SN-DYN-03`, `SN-EEG-02` | skipped calibration rounds in 2024 and 2025 | `ok` |
| `SN-DYN-02`, `SN-EEG-04`, `SN-STM-02` | stopped being calibrated | `overdue` |
| `SN-EMG-06` | stopped being calibrated | `due_soon` |
| `SN-EMG-08` | the newest amplifier, never calibrated | `never_calibrated` |
| `SN-STM-06` | a stimulator that was retired | `retired` |

Query 4 finds the recordings made on a day when the device had no valid calibration. From `small` up it finds exactly
the three devices that skipped rounds (`tiny` is too small to hit all three):

```console
$ labtrack query 4 --variant not_exists
-- Query 4: recordings made with a device that was not calibrated that day  [variant not_exists]
serial_no | kind          | recordings | first_day  | last_day
----------+---------------+------------+------------+-----------
SN-DYN-03 | dynamometer   |         25 | 2024-11-13 | 2025-03-17
SN-EMG-03 | emg_amplifier |         16 | 2025-05-12 | 2025-09-22
SN-EEG-02 | eeg_amplifier |          3 | 2025-04-14 | 2025-08-25
(3 rows)
```

## Teaching queries

`labtrack query` lists them, `labtrack query N` runs one and `labtrack query N --show` prints the SQL first. Each file in
[`queries/`](queries/) starts with the question and the concepts it teaches, followed by notes on how to read it. When a
query has variants (the same answer written in different ways), a test checks that they return the same rows.

| # | Question | What it teaches | Variants |
|---:|---|---|---|
| 1 | the ten most recent completed sessions | `JOIN ... USING`, a tie-breaker in `ORDER BY`, `AT TIME ZONE` | |
| 2 | how are the studies going? | `GROUP BY ROLLUP`, `FILTER`, `NULLIF`, integer against numeric division | |
| 3 | enrolled, but never completed a session | anti-joins and the `NOT IN` trap with `NULL` | `left_join`, `not_exists`, `not_in` |
| 4 | recordings made with a device that was not calibrated that day | range join, `NOT EXISTS`, time zones | `not_exists`, `left_join` |
| 5 | days between visits | window function `LAG` | |
| 6 | recorded hours, month by month, with a running total | `SUM() OVER`, materialized view | |
| 7 | the three most active participants of each study | top-N per group | `window`, `lateral` |
| 8 | stretches of consecutive busy weeks ("gaps and islands") | gaps and islands | |
| 9 | what goes wrong in sessions, and is it hotter then? | `jsonb`, `LATERAL` | |
| 10 | does the feedback lower force variability, and does it depend on the group? | conditional aggregation, why you filter on valid trials | |
| 11 | the latest passed calibration of each device | latest row per group, three ways | `distinct_on`, `lateral`, `window` |
| 12 | the spread of RMS amplitude by channel | `percentile_cont ... WITHIN GROUP` | |

## EXPLAIN lab

Eight lessons, each with a question, the plans of two or three versions of a query, and what to notice. `labtrack explain-lab`
lists them and `labtrack explain-lab N` runs one on a `medium` or larger database. A lesson runs in a transaction that
is rolled back, so it never changes your data or your indexes (`CREATE INDEX` is transactional in PostgreSQL).
`--plans` also prints PostgreSQL's own `EXPLAIN` text.

Execution times in milliseconds, at the `large` size:

| # | Lesson | Time (ms) | What to notice |
|---:|---|---:|---|
| 1 | an index for a selective filter | 316.9 → 3.3 | the primary key starts with `trial_id`, so a filter on `feature_id` cannot use it: `Seq Scan`, then a `Bitmap Index Scan` |
| 2 | a function around the column hides the index | 1.6 → < 0.1 | `recorded_at::date = ...` cannot use the index; a range on the bare column can. The table is small, so the plan shape matters, not the time |
| 3 | an index that holds the answer (index-only scan) | 0.2 → 0.3 | heap fetches fall to zero. With a warm cache the time hardly changes |
| 4 | an index for the rare rows only (partial index) | 37.2 → 6.9 | the lesson also prints the size of the partial index next to a full one |
| 5 | nested loop or hash join? It depends on how much you ask for | 0.2 / 2,151.0 | not a speed-up: two different questions, and the planner picks a join strategy for each |
| 6 | sorting in memory or on disk (work_mem) | 148.3 / 163.6 / 45.0 | `external merge`, `quicksort`, `top-N heapsort`. The in-memory sort did not win the clock here; asking for ten rows did |
| 7 | when the planner guesses wrong (correlated columns) | 1.7 → 1.4 | the estimate was several times too low until `CREATE STATISTICS`; the run time barely moved |
| 8 | page 1500 of a list (OFFSET versus keyset pagination) | 7.2 → < 0.1 | `OFFSET` produces 29,980 rows and throws them away; keyset goes straight to the page |

How these numbers were taken, and how far to trust them:

* Linux on 2 vCPUs and 7.8 GiB of RAM, PostgreSQL 16.15 with its default settings (`shared_buffers` 128 MB,
  `work_mem` 4 MB), 10,378,232 feature values. Median of 5 runs after one warm-up run. The raw numbers, with the
  minimum and maximum of each step, are in
  [`docs/measurements/explain-lab-large.json`](docs/measurements/explain-lab-large.json), and
  [`scripts/measure_explain_lab.py`](scripts/measure_explain_lab.py) repeats the measurement on your machine.
* Timings are machine-dependent and noisy: three separate runs of the whole measurement on this machine gave between 290 and 348 ms
  for the first step of lesson 1.
  Read the ratios, not the digits. The first run after restarting the server can be far slower.
* The tests assert the **shape** of each plan (a `Seq Scan` before, an `Index Scan` after), never a duration, and only
  on PostgreSQL 16.

## Dashboards

The `bi` schema has eight read-only views shaped as a star schema (three facts, five dimensions). `labtrack export --out DIR`
writes them as CSV files (UTF-8, `LF` line endings, `true` and `false`, an empty cell for `NULL`) plus a `SHA256SUMS`
file, for Power BI, Excel or pandas. [`exports/small/`](exports/small/) holds the export of the `small` size, so you can start
without a database; a test checks that it is exactly what the current seed produces.

| File | Rows | What a row is |
|---|---:|---|
| `dim_date.csv` | 2,192 | a calendar day |
| `dim_study.csv` | 3 | a study |
| `dim_participant.csv` | 60 | a participant |
| `dim_researcher.csv` | 12 | a researcher |
| `dim_device.csv` | 24 | a device |
| `fact_session.csv` | 261 | a session |
| `fact_recording.csv` | 460 | a recording |
| `fact_trial.csv` | 12,907 | a trial |

`fact_trial` carries the headline features of each trial as columns, so a report does not have to pivot the long
`trial_feature` table. A feature belongs to one modality: the trials of the other modalities have an empty cell there.
The EMG and EEG values are the mean of the recording's channels.

| Column of `fact_trial` | Modality | Feature in `feature_def` | Unit |
|---|---|---|---|
| `rms_mean_uv` | emg | `rms` | uV |
| `mnf_hz` | emg | `mnf` | Hz |
| `mdf_hz` | emg | `mdf` | Hz |
| `alpha_power_uv2` | eeg | `power_alpha` | uV^2 |
| `peak_force_n` | force | `peak_force` | N |
| `force_cv_pct` | force | `force_cv` | % |

`fact_recording.device_calibrated` is `false` for a recording made on a day when no passed calibration of its device was
valid: query 04 as a column that a report can filter on. In the `small` size it is `false` for 44 of the 460 recordings.

## Migrations

The schema is built by numbered SQL files in [`migrations/`](migrations/), applied in order by a runner of under 200
lines ([`src/labtrack/migrate.py`](src/labtrack/migrate.py)), small on purpose, to show what Flyway, sqitch or Alembic
do for you. It stores the SHA-256 of every applied file and refuses to continue if one was edited afterwards.

```console
$ labtrack status
  0001  applied   schema_types_helpers
  0002  applied   people_and_equipment
  0003  applied   sessions_and_recordings
  0004  applied   features
  0005  applied   views
  0006  applied   bi_star_schema
  0007  applied   roles
  0008  applied   session_protocol_version
  0009  applied   backfill_protocol_version
  0010  applied   protocol_version_check
  0011  applied   protocol_version_validate
  0012  applied   recording_time_index
  0013  applied   bi_more_columns
```

Files 0008 to 0011 are a worked example of adding a `NOT NULL` column to a table in use without holding a strong lock
for long: add the column, backfill it, add a `CHECK` as `NOT VALID`, validate it (a weaker lock) and set `NOT NULL`
(PostgreSQL skips the scan because the validated `CHECK` already proves it). Each step is its own file because a
migration is one transaction and its locks last until it ends. File 0012 builds an index with
`CREATE INDEX CONCURRENTLY`, which cannot run inside a transaction, so the runner lets a file opt out. File 0013 adds
columns to two views with `CREATE OR REPLACE VIEW`, which may append columns but never rename or retype the existing
ones, so a report that already reads the views keeps working. There are no down-migrations: a database in use rolls
forward. [`docs/design-notes.md`](docs/design-notes.md#migrations) has the rest.

## Tests and CI

```bash
python -m pip install -e ".[dev]"      # Windows: py -m pip install -e ".[dev]"
export LABTRACK_TEST_DSN=postgresql://labtrack:labtrack@localhost:5432/postgres   # a user that may create databases
pytest
```

In PowerShell, set the variable with `$env:LABTRACK_TEST_DSN = "..."`.

The tests create their own databases with random names and drop them at the end; nothing you have is touched. They
cover the constraints, the migration runner and the zero-downtime sequence, the determinism of the seed, every teaching
query against a golden result, the plan shape of every lesson, the integrity of the star schema and of the CSV export,
the data dictionary, the command line, and this README: the diagram, the tables of sizes, devices and queries, and every
`$ labtrack ...` block are compared with what the database and the tool really say.

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs `ruff`, `mypy` (strict) and `pytest` against a `postgres:16`
service on Python 3.10 and 3.13.

## Command line

`labtrack` is installed by `python -m pip install -e .`; `python -m labtrack` (`py -m labtrack` on Windows) does the same. `--dsn` goes before the command name;
without it the tool uses `$LABTRACK_DSN`, then `postgresql://labtrack:labtrack@localhost:5432/labtrack` (the Docker Compose database).

| Command | What it does |
|---|---|
| `labtrack createdb` | creates the database named in the DSN if it does not exist |
| `labtrack migrate` | applies the pending migrations (`--to N` stops after migration N) |
| `labtrack status` | lists the migrations and whether each is applied; exits with 1 if an applied file was changed |
| `labtrack seed` | fills the database with synthetic data (`--scale`, `--as-of`, `--reset`) |
| `labtrack check` | runs the data-quality checks, each of which must find nothing; exits with 1 if one does |
| `labtrack query` | lists the teaching queries, or runs one (`N`, `--variant`, `--show`) |
| `labtrack explain-lab` | lists the EXPLAIN lessons, or runs one (`N`, `--plans`) |
| `labtrack export` | writes the `bi` star schema as CSV files (`--out`) |
| `labtrack dictionary` | prints the data dictionary generated from the catalog (`--out`) |
| `labtrack counts` | the row count of every data table |

## Repository layout

```text
migrations/            numbered SQL files: schema, views, roles, and the zero-downtime change 0008 to 0012
seed/                  the synthetic data generator, as SQL
queries/               the teaching queries, each commented like a lesson
explain-lab/           the EXPLAIN lessons
docs/                  design notes, the generated data dictionary, the lesson measurements
exports/               the star schema of the small size as CSV
scripts/               measure_explain_lab.py
src/                   the command-line tool, in Python
tests/                 the pytest suite and its golden files
docker-compose.yml     PostgreSQL 16 for local use
pyproject.toml         packaging and the settings of ruff, mypy and pytest
README.md              this file
README.pt-BR.md        the same, in Portuguese
LICENSE                MIT
```

## Limits

* The data is synthetic and the effects in it are planted. Nothing here is a result.
* Timings depend on the machine, and the plan shapes were checked on PostgreSQL 16 only.
* The migration runner is a teaching tool. In a real project use Flyway, sqitch or Alembic.
* There is no row-level security and no authentication beyond the two roles: nothing here is multi-tenant.
* It is developed and tested on Linux. The code reads files as UTF-8, normalises line endings and uses `pathlib`,
  so it should behave the same on Windows, but CI does not run there.
* [`docs/design-notes.md`](docs/design-notes.md) ends with what would change at real scale (partitioning
  `trial_feature`, a BRIN index, a replica for dashboards). None of it is implemented.

## License

MIT, see [`LICENSE`](LICENSE).
