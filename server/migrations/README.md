Apply the migrations in filename order to the configured PostgreSQL database.
Existing installations that already ran `001_initial_schema.sql` must run
`002_incident_segments.sql` before starting this version of the backend. The
second migration adds shared incident-to-segment links and permits anonymous
incidents to be marked expired. It backfills links for preserved segments.

`003_i95_cameras.sql` adds the five I-95 cameras the app shows, each
replaying `server/replay/camera-demo.mp4` for now. It is safe to run again.
