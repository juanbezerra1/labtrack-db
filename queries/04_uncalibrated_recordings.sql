-- Query 04: recordings made with a device that was not calibrated that day
--
-- Question   Which recordings were made with a device that had no valid, passed calibration on the day
--            of the recording? (Data you may have to explain to a reviewer.)
-- Concepts   a range join (a date BETWEEN two columns), NOT EXISTS, time zones, a data-quality finding
--
-- Read it like this
--   * A calibration covers the days from performed_on up to, but not including, valid_until, and only
--     if it passed. A recording is fine when SOME calibration of its device covers its day.
--   * "No calibration covers it" is a NOT EXISTS over that range condition. Both variants say it.
--   * The recording moment is converted to the lab's calendar day first: 22:30 in Sao Paulo is already
--     the next day in UTC, and a calibration "valid until the 5th" must be judged by local days.
--   * This is a finding, not a bug in the database: no constraint can know the calibration state at the
--     time of a recording. The query is how the lab notices.

-- @variant not_exists
SELECT d.serial_no, d.kind, count(*) AS recordings,
       min((r.recorded_at AT TIME ZONE 'America/Sao_Paulo')::date) AS first_day,
       max((r.recorded_at AT TIME ZONE 'America/Sao_Paulo')::date) AS last_day
FROM lab.recording AS r
JOIN lab.device    AS d USING (device_id)
WHERE NOT EXISTS (
    SELECT 1
    FROM lab.calibration AS c
    WHERE c.device_id = r.device_id
      AND c.passed
      AND c.performed_on <= (r.recorded_at AT TIME ZONE 'America/Sao_Paulo')::date
      AND (r.recorded_at AT TIME ZONE 'America/Sao_Paulo')::date < c.valid_until)
GROUP BY d.serial_no, d.kind
ORDER BY recordings DESC, d.serial_no;

-- @variant left_join
SELECT d.serial_no, d.kind, count(*) AS recordings,
       min((r.recorded_at AT TIME ZONE 'America/Sao_Paulo')::date) AS first_day,
       max((r.recorded_at AT TIME ZONE 'America/Sao_Paulo')::date) AS last_day
FROM lab.recording AS r
JOIN lab.device    AS d USING (device_id)
LEFT JOIN lab.calibration AS c
       ON c.device_id = r.device_id
      AND c.passed
      AND c.performed_on <= (r.recorded_at AT TIME ZONE 'America/Sao_Paulo')::date
      AND (r.recorded_at AT TIME ZONE 'America/Sao_Paulo')::date < c.valid_until
WHERE c.calibration_id IS NULL
GROUP BY d.serial_no, d.kind
ORDER BY recordings DESC, d.serial_no;
