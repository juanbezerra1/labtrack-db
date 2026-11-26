-- seed 02: participants and their enrollments.
--
-- Everything here is pseudonymised and invented: a code, a birth year, a sex, a hand. About 10% of
-- the participants take part in a second study, which is what makes the enrollment table
-- many-to-many in practice and not only on paper. About 4% withdraw after a few weeks.

-- Each participant's first study and enrollment date. Studies are drawn with these shares:
-- FFB-01 45%, EEG-02 35%, EMG-03 20%. Enrollment dates are spread evenly over the study's recruiting
-- window: closed studies stop recruiting 14 weeks before they end, so everybody can finish.
CREATE TABLE lab_seed.plan_primary AS
WITH st AS (
    SELECT study_id, code, started_on,
           least(coalesce(ended_on - 98, lab_seed.as_of()), lab_seed.as_of()) AS enroll_until
    FROM lab.study
), pick AS (
    SELECT g,
           CASE WHEN lab_seed.u('study:' || g) < 0.45 THEN 'FFB-01'
                WHEN lab_seed.u('study:' || g) < 0.80 THEN 'EEG-02'
                ELSE 'EMG-03' END AS study_code
    FROM generate_series(1, lab_seed.n_participants()) AS g
)
SELECT pick.g, st.study_id, st.code AS study_code,
       st.started_on + floor(lab_seed.u('enroll:' || pick.g) * (st.enroll_until - st.started_on + 1))::integer AS enrolled_on
FROM pick
JOIN st ON st.code = pick.study_code;

INSERT INTO lab.participant (code, birth_year, sex, dominant_hand, consent_signed_on, withdrawn_on)
SELECT 'P' || lpad(pp.g::text, 4, '0'),
       1950 + lab_seed.between_('birth:' || pp.g, 0, 55),
       CASE WHEN lab_seed.u('sex:' || pp.g) < 0.52 THEN 'F' ELSE 'M' END,
       (CASE WHEN lab_seed.u('hand:' || pp.g) < 0.86 THEN 'right'
             WHEN lab_seed.u('hand:' || pp.g) < 0.97 THEN 'left'
             ELSE 'ambidextrous' END)::lab.hand,
       pp.enrolled_on - lab_seed.between_('consent:' || pp.g, 0, 7),
       CASE WHEN lab_seed.u('withdraw:' || pp.g) < 0.04
             AND pp.enrolled_on + lab_seed.between_('withdraw-after:' || pp.g, 10, 60) <= lab_seed.as_of()
            THEN pp.enrolled_on + lab_seed.between_('withdraw-after:' || pp.g, 10, 60)
       END
FROM lab_seed.plan_primary AS pp
ORDER BY pp.g;

INSERT INTO lab.enrollment (study_id, participant_id, group_label, enrolled_on)
SELECT e.study_id, p.participant_id,
       CASE WHEN lab_seed.u('group:' || e.g || ':' || e.study_id) < 0.5 THEN 'control' ELSE 'intervention' END,
       e.enrolled_on
FROM (
    SELECT g, study_id, enrolled_on FROM lab_seed.plan_primary
  UNION ALL
    -- a second study for about 10% of the people who have not withdrawn, at least 30 days later
    SELECT pp.g, s2.study_id,
           greatest(s2.started_on, pp.enrolled_on + 30) + lab_seed.between_('second-date:' || pp.g, 0, 60)
    FROM lab_seed.plan_primary AS pp
    JOIN lab.participant AS p0 ON p0.code = 'P' || lpad(pp.g::text, 4, '0')
    CROSS JOIN LATERAL (
        SELECT st.study_id, st.started_on,
               least(coalesce(st.ended_on - 98, lab_seed.as_of()), lab_seed.as_of()) AS enroll_until
        FROM lab.study AS st
        WHERE st.code <> pp.study_code
        ORDER BY md5('second-study:' || pp.g || st.code)
        LIMIT 1
    ) AS s2
    WHERE p0.withdrawn_on IS NULL
      AND lab_seed.u('second:' || pp.g) < 0.10
      AND greatest(s2.started_on, pp.enrolled_on + 30) + lab_seed.between_('second-date:' || pp.g, 0, 60) <= s2.enroll_until
) AS e
JOIN lab.participant AS p ON p.code = 'P' || lpad(e.g::text, 4, '0')
ORDER BY e.study_id, p.participant_id;
