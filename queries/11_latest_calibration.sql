-- Query 11: the latest passed calibration of each device
--
-- Question   For every device, when was it last calibrated successfully, and until when is that valid?
-- Concepts   "latest row per group" three ways: DISTINCT ON, LATERAL ... LIMIT 1, window function
--
-- All three variants return the same rows. Which one to use:
--   distinct_on  PostgreSQL-specific, shortest. Keeps the first row of each device in the ORDER BY order.
--   lateral      for each device, a small subquery asks for its newest calibration. Fast with the index on
--                (device_id, performed_on) because each lookup reads one row; it is how lab.v_device_status
--                is written. A device with no calibration needs LEFT JOIN LATERAL ... ON true to still appear.
--   window       standard SQL: number the calibrations of each device from the newest, keep number 1.
--                Works everywhere, reads every calibration.

-- @variant distinct_on
SELECT DISTINCT ON (d.device_id)
       d.serial_no, d.kind, c.performed_on AS last_passed_on, c.valid_until
FROM lab.device AS d
JOIN lab.calibration AS c ON c.device_id = d.device_id AND c.passed
ORDER BY d.device_id, c.performed_on DESC;

-- @variant lateral
SELECT d.serial_no, d.kind, c.performed_on AS last_passed_on, c.valid_until
FROM lab.device AS d
CROSS JOIN LATERAL (
    SELECT cal.performed_on, cal.valid_until
    FROM lab.calibration AS cal
    WHERE cal.device_id = d.device_id AND cal.passed
    ORDER BY cal.performed_on DESC
    LIMIT 1
) AS c
ORDER BY d.device_id;

-- @variant window
SELECT serial_no, kind, performed_on AS last_passed_on, valid_until
FROM (
    SELECT d.device_id, d.serial_no, d.kind, c.performed_on, c.valid_until,
           row_number() OVER (PARTITION BY d.device_id ORDER BY c.performed_on DESC) AS rn
    FROM lab.device AS d
    JOIN lab.calibration AS c ON c.device_id = d.device_id AND c.passed
) AS ranked
WHERE rn = 1
ORDER BY device_id;
