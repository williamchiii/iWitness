-- Allow several incidents to retain the same camera segment.
CREATE TABLE IF NOT EXISTS incident_segment (
    incident_id uuid NOT NULL REFERENCES incident(id) ON DELETE CASCADE,
    segment_id uuid NOT NULL REFERENCES segment(id) ON DELETE CASCADE,
    PRIMARY KEY (incident_id, segment_id)
);

CREATE INDEX IF NOT EXISTS incident_segment_segment_idx
    ON incident_segment (segment_id);

INSERT INTO incident_segment (incident_id, segment_id)
SELECT incident_id, id
FROM segment
WHERE status = 'preserved' AND incident_id IS NOT NULL
ON CONFLICT DO NOTHING;

-- Expired anonymous incidents have no owner. Claimed incidents still require one.
DO $$
DECLARE old_constraint text;
BEGIN
    SELECT conname INTO old_constraint
    FROM pg_constraint
    WHERE conrelid = 'incident'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%user_id IS NOT NULL%'
      AND pg_get_constraintdef(oid) LIKE '%claim_state%'
    LIMIT 1;
    IF old_constraint IS NOT NULL THEN
        EXECUTE format('ALTER TABLE incident DROP CONSTRAINT %I', old_constraint);
    END IF;
END $$;

ALTER TABLE incident DROP CONSTRAINT IF EXISTS incident_claim_requires_user;
ALTER TABLE incident ADD CONSTRAINT incident_claim_requires_user
    CHECK (claim_state <> 'claimed' OR user_id IS NOT NULL);
