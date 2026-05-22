CREATE TABLE IF NOT EXISTS source_files (
    id          INTEGER PRIMARY KEY,
    path        TEXT UNIQUE NOT NULL,
    filename    TEXT NOT NULL,
    duration_s  REAL,
    fps         REAL,
    resolution  TEXT,
    file_size   INTEGER,
    file_hash   TEXT,
    analyzed_at TEXT,
    status      TEXT DEFAULT 'pending',
    error_msg   TEXT
);

CREATE TABLE IF NOT EXISTS fragments (
    id              INTEGER PRIMARY KEY,
    source_id       INTEGER REFERENCES source_files(id),
    start_s         REAL NOT NULL,
    end_s           REAL NOT NULL,
    duration_s      REAL,

    sharpness       REAL,
    brightness      REAL,
    contrast        REAL,
    motion          REAL,
    stability       REAL,
    action          REAL,
    calm            REAL,

    has_face        INTEGER,
    has_person      INTEGER,
    has_subject     INTEGER,
    scene_type      TEXT,
    scene_tag       TEXT,

    quality_score   REAL,
    cinematic_score REAL,
    action_score    REAL,
    social_score    REAL,
    premium_score   REAL,
    travel_score    REAL,

    crop_16_9       REAL,
    crop_9_16       REAL,
    crop_1_1        REAL,

    is_duplicate    INTEGER DEFAULT 0,
    user_approved   INTEGER,
    user_priority   INTEGER,
    tags            TEXT,

    thumbnail_path  TEXT,
    preview_path    TEXT
);

CREATE TABLE IF NOT EXISTS duplicates (
    fragment_id  INTEGER REFERENCES fragments(id),
    duplicate_id INTEGER REFERENCES fragments(id),
    similarity   REAL,
    PRIMARY KEY (fragment_id, duplicate_id)
);

CREATE INDEX IF NOT EXISTS idx_fragments_source   ON fragments(source_id);
CREATE INDEX IF NOT EXISTS idx_fragments_quality  ON fragments(quality_score DESC);
CREATE INDEX IF NOT EXISTS idx_fragments_approved ON fragments(user_approved);
CREATE INDEX IF NOT EXISTS idx_source_status      ON source_files(status);
