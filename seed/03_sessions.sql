-- seed 03: sessions (visits), the researcher who ran each one, and the devices booked for it.
--
-- The hard part is the calendar. Each study owns two rooms and each room has five two-hour windows
-- per working day, so a study can run 10 sessions a day. Visits want a date ("about a week after the
-- previous one"); this file turns wishes into slots with a queue: first come, first served, a visit
-- never lands before its wish and never in a window that is already taken. Because no two sessions
-- share a room window, the exclusion constraint of lab.session is satisfied by construction.

CREATE TABLE lab_seed.study_room (study_code text, idx integer, room text, PRIMARY KEY (study_code, idx));
INSERT INTO lab_seed.study_room (study_code, idx, room) VALUES
    ('FFB-01', 1, 'R03'), ('FFB-01', 2, 'R04'),
    ('EEG-02', 1, 'R01'), ('EEG-02', 2, 'R02'),
    ('EMG-03', 1, 'R05'), ('EMG-03', 2, 'R06');

-- Five windows a day. A session starts at most 10 minutes after the window opens and lasts at most
-- 105, so it always ends before the next window opens (135 minutes after).
CREATE TABLE lab_seed.slot_window (idx integer PRIMARY KEY, starts time NOT NULL);
INSERT INTO lab_seed.slot_window (idx, starts) VALUES
    (0, '08:00'), (1, '10:15'), (2, '13:00'), (3, '15:15'), (4, '17:30');

-- Working days (Monday to Friday; public holidays are ignored) numbered 0, 1, 2, ...
CREATE TABLE lab_seed.workday AS
SELECT d::date AS day, (row_number() OVER (ORDER BY d) - 1)::integer AS ord
FROM generate_series(DATE '2023-01-02', DATE '2030-12-31', INTERVAL '1 day') AS g (d)
WHERE extract(isodow FROM d) < 6;
CREATE UNIQUE INDEX workday_day_key ON lab_seed.workday (day);
CREATE UNIQUE INDEX workday_ord_key ON lab_seed.workday (ord);

CREATE TABLE lab_seed.session_plan AS
WITH visits AS (
    -- one row per planned visit; visit 1 happens 0-10 days after enrollment, the next ones 7-16 days
    -- after the previous one; some visits will be cancelled (5%) or missed (3%)
    SELECT e.study_id, st.code AS study_code, st.ended_on, st.planned_visits,
           e.participant_id, p.code AS participant_code, p.withdrawn_on, e.enrolled_on, v.n AS visit_no,
           CASE WHEN v.n = 1 THEN lab_seed.between_('gap:' || st.code || p.code || v.n, 0, 10)
                ELSE lab_seed.between_('gap:' || st.code || p.code || v.n, 7, 16) END AS gap_days,
           CASE WHEN lab_seed.u('fate:' || st.code || p.code || v.n) < 0.05 THEN 'cancelled'
                WHEN lab_seed.u('fate:' || st.code || p.code || v.n) < 0.08 THEN 'no_show'
                ELSE 'attended' END AS fate
    FROM lab.enrollment AS e
    JOIN lab.study AS st USING (study_id)
    JOIN lab.participant AS p USING (participant_id)
    CROSS JOIN LATERAL generate_series(1, st.planned_visits) AS v (n)
), wished AS (
    SELECT *, enrolled_on + (sum(gap_days) OVER (PARTITION BY study_id, participant_id ORDER BY visit_no))::integer AS wish_date
    FROM visits
), with_last AS (
    SELECT *, max(wish_date) OVER (PARTITION BY study_id, participant_id) AS last_wish_date
    FROM wished
), makeups AS (
    -- a visit missed in the past is made up after the last planned visit: one week later for the first
    -- make-up, two weeks for the second, plus 0-6 days
    SELECT w.study_id, w.study_code, w.ended_on, w.planned_visits, w.participant_id, w.participant_code,
           w.withdrawn_on, w.enrolled_on,
           w.planned_visits + (row_number() OVER (PARTITION BY w.study_id, w.participant_id ORDER BY w.visit_no))::integer AS visit_no,
           0 AS gap_days,
           CASE WHEN lab_seed.u('fate2:' || w.study_code || w.participant_code || w.visit_no) < 0.10
                THEN 'cancelled' ELSE 'attended' END AS fate,
           w.last_wish_date
             + 7 * (row_number() OVER (PARTITION BY w.study_id, w.participant_id ORDER BY w.visit_no))::integer
             + lab_seed.between_('makeup:' || w.study_code || w.participant_code || w.visit_no, 0, 6) AS wish_date
    FROM with_last AS w
    WHERE w.fate <> 'attended' AND w.wish_date <= lab_seed.as_of()
), every_visit AS (
    SELECT study_id, study_code, ended_on, participant_id, participant_code, withdrawn_on, visit_no, fate, wish_date FROM with_last
    UNION ALL
    SELECT study_id, study_code, ended_on, participant_id, participant_code, withdrawn_on, visit_no, fate, wish_date FROM makeups
), on_workday AS (
    -- a wish that falls on a weekend moves to the Monday
    SELECT v.*, w.ord AS wish_ord, r.n_rooms, r.n_rooms * 5 AS cap
    FROM every_visit AS v
    JOIN lab_seed.workday AS w
      ON w.day = v.wish_date + CASE extract(isodow FROM v.wish_date)::integer WHEN 6 THEN 2 WHEN 7 THEN 1 ELSE 0 END
    JOIN (SELECT study_code, count(*)::integer AS n_rooms FROM lab_seed.study_room GROUP BY study_code) AS r USING (study_code)
), queued AS (
    SELECT *, row_number() OVER (PARTITION BY study_id ORDER BY wish_ord, md5(participant_code || ':' || visit_no)) AS rn
    FROM on_workday
), slotted AS (
    -- The queue in one window function. Slot numbers count every room window of the study in order
    -- (day 0 slot 0, day 0 slot 1, ... day 1 slot 0, ...). Visit i takes slot max(first slot of its
    -- wished day, slot of visit i-1 plus one), and unrolling that recurrence gives
    --   slot(i) = i + max over j <= i of (first slot of j's wished day - j).
    SELECT *, rn + max(wish_ord * cap - rn) OVER (PARTITION BY study_id ORDER BY rn) AS slot_no
    FROM queued
)
SELECT s.study_id, s.study_code, s.ended_on, s.participant_id, s.participant_code, s.withdrawn_on, s.visit_no, s.fate,
       wd.day AS local_day, sr.room, sw.starts AS window_start
FROM slotted AS s
JOIN lab_seed.workday     AS wd ON wd.ord = s.slot_no / s.cap
JOIN lab_seed.study_room  AS sr ON sr.study_code = s.study_code AND sr.idx = 1 + ((s.slot_no % s.cap) % s.n_rooms)
JOIN lab_seed.slot_window AS sw ON sw.idx = (s.slot_no % s.cap) / s.n_rooms;

INSERT INTO lab.session (study_id, participant_id, researcher_id, visit_no, room, starts_at, ends_at,
                         status, notes, protocol_version)
-- visit_no counts a participant's visits in the order they happen; a make-up visit is simply the next number
SELECT x.study_id, x.participant_id, res.researcher_id,
       (row_number() OVER (PARTITION BY x.study_id, x.participant_id ORDER BY x.starts_at, x.key))::smallint,
       x.room, x.starts_at,
       x.starts_at + make_interval(mins => x.minutes),
       x.status::lab.session_status,
       jsonb_build_object('room_temp_c', round((21 + 4 * lab_seed.u('temp:' || x.key))::numeric, 1))
         || CASE WHEN lab_seed.u('issue:' || x.key) < 0.06
                 THEN jsonb_build_object('issues', jsonb_build_array(
                          (ARRAY['electrode_drift', 'stimulator_reset', 'late_start'])[1 + floor(lab_seed.u('issue-kind:' || x.key) * 3)::integer]))
                 ELSE '{}'::jsonb END,
       CASE WHEN x.local_day < DATE '2025-01-01' THEN 'v1'
            WHEN x.local_day < DATE '2026-01-01' THEN 'v2'
            ELSE 'v3' END
FROM (
    SELECT sp.*,
           sp.study_code || sp.participant_code || ':' || sp.visit_no AS key,
           lab_seed.between_('duration:' || sp.study_code || sp.participant_code || ':' || sp.visit_no, 60, 105) AS minutes,
           (sp.local_day + sp.window_start
              + make_interval(mins => lab_seed.between_('jitter:' || sp.study_code || sp.participant_code || ':' || sp.visit_no, 0, 10)))
              AT TIME ZONE 'America/Sao_Paulo' AS starts_at,
           CASE WHEN sp.withdrawn_on IS NOT NULL AND sp.local_day > sp.withdrawn_on THEN 'cancelled'
                WHEN sp.local_day > lab_seed.as_of()  THEN 'scheduled'
                WHEN sp.fate = 'cancelled'            THEN 'cancelled'
                WHEN sp.fate = 'no_show'              THEN 'no_show'
                ELSE 'completed' END AS status
    FROM lab_seed.session_plan AS sp
    -- bookings exist only for the next six weeks, and never after the study ended
    WHERE sp.local_day <= least(coalesce(sp.ended_on, DATE '9999-12-31'), lab_seed.as_of() + 42)
) AS x
CROSS JOIN LATERAL (
    -- the researcher: anyone but the PI who was working in the lab that day, picked by hash
    SELECT r.researcher_id
    FROM lab.researcher AS r
    WHERE r.role <> 'pi' AND r.hired_on <= x.local_day AND (r.left_on IS NULL OR r.left_on > x.local_day)
    ORDER BY md5(x.key || ':' || r.researcher_id)
    LIMIT 1
) AS res
ORDER BY x.starts_at, x.room;

-- Devices booked for each session: the room's own devices of the kinds the study needs. In R01 and R02
-- about one session in ten uses the spare EMG amplifier instead (once it exists).
CREATE TABLE lab_seed.study_kind (study_code text, kind text, abbr text, PRIMARY KEY (study_code, kind));
INSERT INTO lab_seed.study_kind (study_code, kind, abbr) VALUES
    ('FFB-01', 'emg_amplifier', 'EMG'), ('FFB-01', 'dynamometer', 'DYN'), ('FFB-01', 'stimulator', 'STM'),
    ('EEG-02', 'eeg_amplifier', 'EEG'), ('EEG-02', 'emg_amplifier', 'EMG'),
    ('EMG-03', 'emg_amplifier', 'EMG');

INSERT INTO lab.session_device (session_id, device_id)
SELECT b.session_id, d.device_id
FROM (
    SELECT s.session_id, sk.kind, sk.abbr, substr(s.room, 3, 1)::integer AS room_no,
           (s.starts_at AT TIME ZONE 'America/Sao_Paulo')::date AS local_day
    FROM lab.session AS s
    JOIN lab.study AS st USING (study_id)
    JOIN lab_seed.study_kind AS sk ON sk.study_code = st.code
    WHERE s.status IN ('scheduled', 'completed')
) AS b
JOIN lab.device AS d
  ON d.serial_no = CASE WHEN b.abbr = 'EMG' AND b.room_no <= 2
                         AND lab_seed.u('spare:' || b.session_id) < 0.10
                         AND b.local_day >= CASE b.room_no WHEN 1 THEN DATE '2023-02-01' ELSE DATE '2026-09-14' END
                        THEN 'SN-EMG-0' || (6 + b.room_no)
                        ELSE 'SN-' || b.abbr || '-0' || b.room_no END
ORDER BY b.session_id, d.device_id;
