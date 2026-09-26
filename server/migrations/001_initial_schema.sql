-- iWitness initial metadata schema.
-- Run this against the Supabase PostgreSQL database before starting the API.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS camera (
    id text PRIMARY KEY,
    name text NOT NULL,
    location text NOT NULL,
    source_type text NOT NULL CHECK (source_type IN ('live', 'replay')),
    input_url text NOT NULL,
    permitted boolean NOT NULL DEFAULT false,
    recording boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app_user (
    id uuid PRIMARY KEY,
    email text NOT NULL,
    display_name text,
    avatar_url text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trip (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid REFERENCES app_user(id) ON DELETE SET NULL,
    camera_id text NOT NULL REFERENCES camera(id) ON DELETE RESTRICT,
    anonymous_token_hash text NOT NULL UNIQUE,
    started_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz,
    state text NOT NULL DEFAULT 'active'
        CHECK (state IN ('active', 'ended')),
    CHECK (ended_at IS NULL OR ended_at >= started_at)
);

CREATE TABLE IF NOT EXISTS incident (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid REFERENCES app_user(id) ON DELETE SET NULL,
    trip_id uuid NOT NULL REFERENCES trip(id) ON DELETE RESTRICT,
    camera_id text NOT NULL REFERENCES camera(id) ON DELETE RESTRICT,
    trigger_at timestamptz NOT NULL,
    requested_start timestamptz NOT NULL,
    requested_end timestamptz NOT NULL,
    actual_start timestamptz,
    actual_end timestamptz,
    source_start timestamptz,
    source_end timestamptz,
    duration_seconds double precision,
    size_bytes bigint,
    sha256 text,
    storage_path text,
    processing_state text NOT NULL DEFAULT 'recording'
        CHECK (processing_state IN (
            'recording', 'assembling', 'uploading', 'ready', 'failed'
        )),
    claim_state text NOT NULL DEFAULT 'unclaimed'
        CHECK (claim_state IN ('unclaimed', 'claimed', 'expired')),
    expires_at timestamptz,
    video_version integer NOT NULL DEFAULT 1 CHECK (video_version > 0),
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (requested_end >= requested_start),
    CHECK (actual_end IS NULL OR actual_start IS NULL OR actual_end >= actual_start),
    CHECK (source_end IS NULL OR source_start IS NULL OR source_end >= source_start),
    CHECK (claim_state = 'unclaimed' OR user_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS segment (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    camera_id text NOT NULL REFERENCES camera(id) ON DELETE RESTRICT,
    file_path text NOT NULL UNIQUE,
    actual_start timestamptz NOT NULL,
    actual_end timestamptz NOT NULL,
    source_start timestamptz,
    source_end timestamptz,
    status text NOT NULL DEFAULT 'temporary'
        CHECK (status IN ('temporary', 'preserved')),
    incident_id uuid REFERENCES incident(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (actual_end >= actual_start),
    CHECK (source_end IS NULL OR source_start IS NULL OR source_end >= source_start),
    CHECK (status = 'temporary' OR incident_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS trip_camera_state_idx
    ON trip (camera_id, state, started_at DESC);

CREATE INDEX IF NOT EXISTS incident_user_trigger_idx
    ON incident (user_id, trigger_at DESC);

CREATE INDEX IF NOT EXISTS incident_claim_expiry_idx
    ON incident (claim_state, expires_at);

CREATE INDEX IF NOT EXISTS segment_camera_time_idx
    ON segment (camera_id, actual_start, actual_end);

CREATE INDEX IF NOT EXISTS segment_retention_idx
    ON segment (camera_id, status, actual_end);

INSERT INTO camera (
    id,
    name,
    location,
    source_type,
    input_url,
    permitted,
    recording
)
VALUES (
    'camera-demo',
    'Demo FDOT camera',
    'I-95 demo camera',
    'replay',
    'server/replay/camera-demo.mp4',
    true,
    false
)
ON CONFLICT (id) DO NOTHING;
