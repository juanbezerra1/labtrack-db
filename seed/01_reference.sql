-- seed 01: helper functions, then everything that exists before the first participant walks in:
-- studies, researchers, devices and their calibrations.
--
-- The data is SYNTHETIC and DETERMINISTIC: no random(), no now(). Every "random" number comes from
-- md5() of a text key, so the same seed gives the same rows on any machine and any PostgreSQL version.
-- Settings read by the seed files (the runner sets them; to run by hand use SET labtrack.seed_...):
--   labtrack.seed_participants   how many participants (20 tiny, 60 small, 200 medium, 1800 large)
--   labtrack.seed_as_of          the seed's "today" (default 2026-10-31): nothing is dated after it,
--                                except bookings for the next six weeks

-- Helpers live in their own schema, which the last seed file drops again.
CREATE SCHEMA lab_seed;

-- A number in [0, 1) that depends only on the text key: the first 52 bits of its md5, divided by 2^52.
CREATE FUNCTION lab_seed.u(key text) RETURNS float8
    LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
    AS $$ SELECT (('x' || substr(md5(key), 1, 13))::bit(52)::bigint)::float8 / 4503599627370496.0 $$;

-- An integer between lo and hi, both included.
CREATE FUNCTION lab_seed.between_(key text, lo integer, hi integer) RETURNS integer
    LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
    AS $$ SELECT lo + floor(lab_seed.u(key) * (hi - lo + 1))::integer $$;

CREATE FUNCTION lab_seed.as_of() RETURNS date
    LANGUAGE sql STABLE AS $$ SELECT current_setting('labtrack.seed_as_of')::date $$;

CREATE FUNCTION lab_seed.n_participants() RETURNS integer
    LANGUAGE sql STABLE AS $$ SELECT current_setting('labtrack.seed_participants')::integer $$;

-- ---------------------------------------------------------------------------------------------
-- Studies. target_n scales with the number of participants so the "target vs enrolled" query is
-- meaningful at every size.
INSERT INTO lab.study (code, title, started_on, ended_on, planned_visits, target_n)
SELECT s.code, s.title, s.started_on, s.ended_on, 4,
       greatest(10, round(s.share * lab_seed.n_participants() * 1.15)::integer)
FROM (VALUES
    ('FFB-01', 'Force feedback for myoelectric control',   DATE '2024-03-04', DATE '2025-12-19', 0.45),
    ('EEG-02', 'Visual stimulus size and motor execution', DATE '2025-02-03', DATE '2026-08-28', 0.35),
    ('EMG-03', 'Biceps EMG during a fatigue protocol',     DATE '2025-09-01', NULL::date,        0.20)
) AS s (code, title, started_on, ended_on, share)
ORDER BY s.started_on;

-- ---------------------------------------------------------------------------------------------
-- Researchers: invented names; a few were hired during the studies and one left.
INSERT INTO lab.researcher (full_name, role, email, hired_on, left_on)
SELECT n.first[1 + (r.i * 7) % 20] || ' ' || n.last[1 + (r.i * 5) % 24],
       r.role::lab.researcher_role,
       lower(n.first[1 + (r.i * 7) % 20] || '.' || n.last[1 + (r.i * 5) % 24]) || '@lab.example',
       r.hired_on,
       r.left_on
FROM (VALUES
    ( 1, 'pi',         DATE '2016-03-01', NULL::date),
    ( 2, 'postdoc',    DATE '2020-08-17', NULL),
    ( 3, 'postdoc',    DATE '2022-02-07', DATE '2026-04-30'),
    ( 4, 'phd',        DATE '2021-03-01', NULL),
    ( 5, 'phd',        DATE '2022-08-01', NULL),
    ( 6, 'phd',        DATE '2023-03-06', NULL),
    ( 7, 'phd',        DATE '2024-08-05', NULL),
    ( 8, 'msc',        DATE '2024-03-04', NULL),
    ( 9, 'msc',        DATE '2025-03-03', NULL),
    (10, 'msc',        DATE '2025-08-04', NULL),
    (11, 'technician', DATE '2019-05-20', NULL),
    (12, 'technician', DATE '2025-01-13', NULL)
) AS r (i, role, hired_on, left_on)
CROSS JOIN (SELECT
    ARRAY['Ana','Bruno','Carla','Diego','Elisa','Fabio','Gabriela','Hugo','Isabel','Jorge',
          'Karen','Lucas','Marina','Nelson','Olivia','Paulo','Quiteria','Rafael','Sofia','Thiago'] AS first,
    ARRAY['Almeida','Barbosa','Carvalho','Dias','Esteves','Ferraz','Gomes','Horta','Ibrahim','Jardim',
          'Klein','Lima','Moraes','Nogueira','Oliveira','Pires','Queiroz','Ramos','Silva','Teixeira',
          'Uchoa','Viana','Xavier','Zanetti'] AS last) AS n
ORDER BY r.i;

-- ---------------------------------------------------------------------------------------------
-- Devices: every room R01-R06 owns an EMG amplifier, a dynamometer and a stimulator; rooms R01-R04
-- also own an EEG amplifier; R01 and R02 keep one spare EMG amplifier each (the second spare is new
-- and has never been calibrated). One stimulator was retired.
INSERT INTO lab.device (kind, model, serial_no, home_room, acquired_on, retired_on)
SELECT d.kind::lab.device_kind, d.model, format('SN-%s-%s', d.abbr, lpad(d.n::text, 2, '0')),
       'R0' || (((d.n - 1) % 6) + 1), d.acquired_on, d.retired_on
FROM (
    SELECT 'emg_amplifier' AS kind, 'Acme EMG-8' AS model, 'EMG' AS abbr, n,
           CASE WHEN n <= 6 THEN DATE '2019-06-10' + n * 37
                WHEN n = 7  THEN DATE '2023-02-01'
                ELSE             DATE '2026-09-14' END AS acquired_on,
           NULL::date AS retired_on
    FROM generate_series(1, 8) AS n
  UNION ALL
    SELECT 'eeg_amplifier', 'Acme EEG-32', 'EEG', n, DATE '2020-09-01' + n * 90, NULL
    FROM generate_series(1, 4) AS n
  UNION ALL
    SELECT 'dynamometer', 'Acme Grip-100', 'DYN', n, DATE '2019-11-04' + n * 45, NULL
    FROM generate_series(1, 6) AS n
  UNION ALL
    SELECT 'stimulator', 'Acme Stim-3k', 'STM', n, DATE '2021-03-15' + n * 60,
           CASE WHEN n = 6 THEN DATE '2026-03-15' END
    FROM generate_series(1, 6) AS n
) AS d
ORDER BY d.kind, d.n;

-- ---------------------------------------------------------------------------------------------
-- Calibrations: every device is calibrated every 90 days and each calibration covers 120 days, so a
-- device with an up-to-date routine is never uncalibrated. The exceptions below are deliberate,
-- and the teaching queries (queries/04_*.sql) are designed to find them:
--   * three devices skipped a few rounds (a window with no calibration),
--   * four devices stopped being calibrated (three overdue, one due within two weeks, as of 2026-10-31),
--   * the newest amplifier was never calibrated, and the retired stimulator stops at its retirement,
--   * about 5% of calibrations fail and are repeated a week later.
CREATE TABLE lab_seed.calibration_rule (
    serial_no   text PRIMARY KEY,
    skip_from   date,
    skip_to     date,
    last_round  date
);
INSERT INTO lab_seed.calibration_rule (serial_no, skip_from, skip_to, last_round) VALUES
    ('SN-EMG-03', DATE '2025-01-10', DATE '2025-06-30', NULL),
    ('SN-DYN-03', DATE '2024-09-01', DATE '2025-02-28', NULL),
    ('SN-EEG-02', DATE '2025-03-01', DATE '2025-07-31', NULL),
    ('SN-EEG-04', NULL,             NULL,              DATE '2026-05-10'),
    ('SN-STM-02', NULL,             NULL,              DATE '2026-06-01'),
    ('SN-DYN-02', NULL,             NULL,              DATE '2026-07-05'),
    ('SN-EMG-06', NULL,             NULL,              DATE '2026-07-31');

WITH rounds AS (
    SELECT d.device_id, d.serial_no, k,
           d.acquired_on + 30 + 90 * k AS due,
           lab_seed.u('cal-fail:' || d.serial_no || ':' || k) < 0.05 AS first_fails
    FROM lab.device AS d
    CROSS JOIN generate_series(0, 40) AS k
    LEFT JOIN lab_seed.calibration_rule AS rule USING (serial_no)
    WHERE d.serial_no <> 'SN-EMG-08'
      AND d.acquired_on + 30 + 90 * k <= least(lab_seed.as_of(),
                                               coalesce(d.retired_on, DATE '9999-12-31'),
                                               coalesce(rule.last_round, DATE '9999-12-31'))
      AND NOT (d.acquired_on + 30 + 90 * k BETWEEN coalesce(rule.skip_from, DATE '9999-01-01')
                                               AND coalesce(rule.skip_to,   DATE '9999-01-01'))
), calibrations AS (
    SELECT device_id, serial_no, due AS performed_on, NOT first_fails AS passed,
           CASE WHEN first_fails THEN 'drift above tolerance, repeated a week later' END AS notes
    FROM rounds
  UNION ALL
    SELECT device_id, serial_no, due + 7, true, 'repeat after a failed round'
    FROM rounds WHERE first_fails
)
INSERT INTO lab.calibration (device_id, performed_on, performed_by, passed, valid_until, notes)
SELECT c.device_id, c.performed_on, tech.researcher_id, c.passed,
       c.performed_on + CASE WHEN c.passed THEN 120 ELSE 1 END, c.notes
FROM calibrations AS c
CROSS JOIN LATERAL (
    SELECT r.researcher_id
    FROM lab.researcher AS r
    WHERE r.role = 'technician' AND r.hired_on <= c.performed_on
    ORDER BY md5(c.serial_no || c.performed_on::text || r.researcher_id::text)
    LIMIT 1
) AS tech
ORDER BY c.device_id, c.performed_on;
