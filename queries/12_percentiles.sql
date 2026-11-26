-- Query 12: the spread of RMS amplitude by channel
--
-- Question   For the EMG recordings, what do the 10th, 50th and 90th percentiles of the RMS look like for each
--            channel, using only valid trials?
-- Concepts   ordered-set aggregates: percentile_cont ... WITHIN GROUP; why the mean alone misleads
--
-- Read it like this
--   * percentile_cont(0.5) WITHIN GROUP (ORDER BY x) is the median, interpolating between the two middle values
--     when the count is even; percentile_disc picks an actual value instead. You can ask for several
--     percentiles at once by giving an array: percentile_cont(ARRAY[0.1, 0.5, 0.9]).
--   * The p90 / p10 ratio is a quick, outlier-proof measure of spread.
--   * Channel numbers come from the long table; the channel's name (biceps, triceps...) is in lab.channel.
--     The join needs BOTH keys, (recording_id, channel_no): a channel number alone is not unique.

SELECT c.label AS channel,
       count(*) AS values_used,
       round(avg(tf.value)::numeric, 1)                                         AS mean_rms,
       round((percentile_cont(0.10) WITHIN GROUP (ORDER BY tf.value))::numeric, 1) AS p10,
       round((percentile_cont(0.50) WITHIN GROUP (ORDER BY tf.value))::numeric, 1) AS median,
       round((percentile_cont(0.90) WITHIN GROUP (ORDER BY tf.value))::numeric, 1) AS p90,
       round((percentile_cont(0.90) WITHIN GROUP (ORDER BY tf.value)
            / percentile_cont(0.10) WITHIN GROUP (ORDER BY tf.value))::numeric, 2) AS p90_over_p10
FROM lab.trial_feature AS tf
JOIN lab.trial     AS t USING (trial_id)
JOIN lab.recording AS r USING (recording_id)
JOIN lab.channel   AS c ON c.recording_id = r.recording_id AND c.channel_no = tf.channel_no
WHERE tf.feature_id = 1          -- rms
  AND r.modality = 'emg'
  AND t.valid
GROUP BY c.label
ORDER BY c.label;
