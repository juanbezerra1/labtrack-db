-- Lesson 08: page 1500 of a list (OFFSET versus keyset pagination)
-- Needs: medium
--
-- Question  Show page 1500 (20 trials per page, ordered by id) of the trial list.
-- Takeaway  OFFSET 29980 does not jump to the page: PostgreSQL produces the 29,980 rows before it and throws them away,
--           so every page is slower than the one before. Keyset pagination remembers the last id seen and asks for
--           "the next 20 after it" (WHERE trial_id > last): the primary-key index goes straight there, and page
--           10,000 costs the same as page 1. The price: you can go to the next page, not to an arbitrary one.
--           Compare "actual rows" of the index scan in the two steps.

-- @explain offset
SELECT trial_id, condition FROM lab.trial ORDER BY trial_id OFFSET 29980 LIMIT 20;

-- @explain keyset
SELECT trial_id, condition FROM lab.trial WHERE trial_id > 29980 ORDER BY trial_id LIMIT 20;

-- @expect offset: Index Scan using trial_pkey
-- @expect keyset: Index Scan using trial_pkey
