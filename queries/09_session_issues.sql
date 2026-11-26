-- Query 09: what goes wrong in sessions, and is it hotter then?
--
-- Question   Which problems do the session notes mention, how often, and what was the average room
--            temperature in those sessions?
-- Concepts   jsonb: ->, ->>, jsonb_array_elements_text, LATERAL; casting a JSON value to a number
--
-- Read it like this
--   * lab.session.notes is a jsonb object: {"room_temp_c": 23.4, "issues": ["late_start"]}. The "issues" key
--     exists only in sessions that had problems.
--   * notes -> 'issues' returns the JSON array; notes ->> 'room_temp_c' returns the value as TEXT, so it is
--     cast to numeric before averaging.
--   * jsonb_array_elements_text turns an array into rows, one per element. In a LATERAL join it runs once per
--     session. A session without the key produces NULL there and, with CROSS JOIN, simply no rows.
--   * Other operators worth trying:  notes ? 'issues'  (has the key),  notes @> '{"issues": ["late_start"]}'
--     (contains), and jsonb_path_exists for nested searches. A GIN index makes ? and @> fast.

SELECT i.issue,
       count(*) AS sessions,
       round(avg((s.notes ->> 'room_temp_c')::numeric), 1) AS avg_room_temp_c
FROM lab.session AS s
CROSS JOIN LATERAL jsonb_array_elements_text(s.notes -> 'issues') AS i (issue)
GROUP BY i.issue
ORDER BY sessions DESC, i.issue;
