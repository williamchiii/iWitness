-- The five I-95 cameras the app shows, north to south through downtown Miami
-- and Brickell. Ids and names match client/src/lib/cameras.ts, which keeps
-- each camera's map position; the number in each id is the FL511 camera ID.
--
-- Every camera replays the local demo video for now, so each has its own
-- rolling loop buffer and the UI labels the footage as replayed. Before
-- pointing input_url at a live FDOT feed, confirm that camera streams
-- continuous video and is covered by the FDOT permission (CLAUDE.local.md),
-- and set source_type to 'live'.
INSERT INTO camera (
    id,
    name,
    location,
    source_type,
    input_url,
    permitted,
    recording
)
VALUES
    ('fl511-760', 'I-95 at NW 13th St', 'Southbound', 'replay', 'server/replay/camera-demo.mp4', true, false),
    ('fl511-733', 'I-95 at NW 6th St', 'Northbound', 'replay', 'server/replay/camera-demo.mp4', true, false),
    ('fl511-1329', 'I-95 at SW 8th St', 'Southbound', 'replay', 'server/replay/camera-demo.mp4', true, false),
    ('fl511-1428', 'I-95 at SW 20th Rd', 'Southbound', 'replay', 'server/replay/camera-demo.mp4', true, false),
    ('fl511-736', 'I-95 at SW 26th Rd', 'Southbound', 'replay', 'server/replay/camera-demo.mp4', true, false)
ON CONFLICT (id) DO NOTHING;
