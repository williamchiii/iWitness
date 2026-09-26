-- Keep file deletion work durable after the owning database row is removed.
CREATE TABLE IF NOT EXISTS pending_media_delete (
    file_path text PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now()
);
