Apply the migrations in filename order to the configured PostgreSQL database.
Existing installations that already ran `001_initial_schema.sql` must run
`002_incident_segments.sql` before starting this version of the backend. The
second migration adds shared incident-to-segment links and permits anonymous
incidents to be marked expired. It backfills links for preserved segments.

`003_i95_cameras.sql` adds the five I-95 cameras the app shows, each
replaying `server/replay/camera-demo.mp4` for now. It is safe to run again.

`004_fl511_live_cameras.sql` switches those five cameras to their live FL511
streams (`input_url = 'fl511:<site id>'`, see `server/fl511.py`). Restart the
backend after running it. To demo offline, save each feed with
`python -m server.camera_sources capture` and switch with
`python -m server.camera_sources use replay` (and `use live` to switch back).

`005_media_deletion_queue.sql` keeps pending file removals in PostgreSQL so
retention and incident expiry can retry them after a crash or filesystem error.
Apply it before starting a backend that uses the deletion queue.
