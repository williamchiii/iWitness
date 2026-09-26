-- Record the five I-95 cameras from their live FL511 streams instead of the
-- demo test pattern. "fl511:<site id>" is resolved to a tokenized DIVAS HLS
-- URL each time the recorder starts (server/fl511.py); the site id is the
-- number in the camera's fl511.com tooltip URL.
--
-- The team's FDOT permission covers recording these cameras for educational
-- use (details in CLAUDE.local.md). To demo without the network, switch to
-- saved recordings with `python -m server.camera_sources use replay`; the
-- same site ids are in server/camera_sources.py.
UPDATE camera AS c
SET source_type = 'live',
    input_url = v.input_url
FROM (
    VALUES
        ('fl511-760', 'fl511:450'),
        ('fl511-733', 'fl511:5499'),
        ('fl511-1329', 'fl511:435'),
        ('fl511-1428', 'fl511:5489'),
        ('fl511-736', 'fl511:5488')
) AS v (id, input_url)
WHERE c.id = v.id;
