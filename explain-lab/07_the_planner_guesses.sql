-- Lesson 07: when the planner guesses wrong (correlated columns)
-- Needs: medium
--
-- Question  How many recordings are EEG recordings with 8 channels?
-- Takeaway  PostgreSQL keeps statistics per column and assumes columns are independent: P(modality = eeg AND
--           n_channels = 8) is estimated as P(eeg) x P(8 channels). But here the two are the same fact (every EEG
--           recording has 8 channels), so the estimate is several times too low. A bad estimate does not change the
--           result, only the choice of plan, and in bigger queries it snowballs into slow joins. CREATE STATISTICS
--           ... (dependencies) tells PostgreSQL the columns are related, and the estimate becomes accurate.
--           Look at "rows: estimated ..., actual ..." in each step.

-- @explain independent columns
SELECT recording_id FROM lab.recording WHERE modality = 'eeg' AND n_channels = 8;

-- @do
CREATE STATISTICS recording_modality_channels (dependencies) ON modality, n_channels FROM lab.recording;
ANALYZE lab.recording;

-- @explain with extended statistics
SELECT recording_id FROM lab.recording WHERE modality = 'eeg' AND n_channels = 8;

-- @expect with extended statistics: Seq Scan on recording
