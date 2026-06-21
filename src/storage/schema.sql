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

    -- Extended quality metrics (added v2)
    colorfulness        REAL,          -- Hasler & Süsstrunk 2003 colorfulness index [0–1]
    complexity          REAL,          -- Shannon entropy of frame histogram [0–1]
    camera_motion_type  TEXT,          -- static | pan_left | pan_right | tilt_up | tilt_down | zoom_in | zoom_out | shake

    -- Composition & coherence metrics (added v3)
    composition_score   REAL,          -- rule-of-thirds edge alignment [0–1]
    temporal_coherence  REAL,          -- internal histogram consistency across frames [0–1]
    saliency_score      REAL,          -- center-weighted motion saliency [0–1]

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

CREATE TABLE IF NOT EXISTS render_history (
    id           INTEGER PRIMARY KEY,
    project_dir  TEXT NOT NULL,
    style_id     TEXT,
    style_name   TEXT,
    music_path   TEXT,
    created_at   TEXT NOT NULL,
    output_path  TEXT,
    quality_avg  REAL,
    clip_count   INTEGER,
    duration_s   REAL,
    user_rating  INTEGER    -- 1–5 stars, NULL = not rated
);

CREATE INDEX IF NOT EXISTS idx_fragments_source   ON fragments(source_id);
CREATE INDEX IF NOT EXISTS idx_fragments_quality  ON fragments(quality_score DESC);
CREATE INDEX IF NOT EXISTS idx_fragments_approved ON fragments(user_approved);
CREATE INDEX IF NOT EXISTS idx_source_status      ON source_files(status);
CREATE INDEX IF NOT EXISTS idx_render_history_dir ON render_history(project_dir, created_at DESC);

CREATE TABLE IF NOT EXISTS music_fragments (
    id                  INTEGER PRIMARY KEY,
    audio_file          TEXT NOT NULL,
    audio_hash          TEXT,
    start_s             REAL NOT NULL,
    end_s               REAL NOT NULL,
    duration_s          REAL NOT NULL,
    fragment_type       TEXT,   -- intro | buildup | drop | peak | calm | loopable | outro
    energy_score        REAL,
    rhythm_score        REAL,
    beat_clarity        REAL,
    montage_score       REAL,
    reason              TEXT,
    warnings            TEXT,
    selected_by_system  INTEGER DEFAULT 0,
    selected_by_user    INTEGER,    -- NULL=untouched, 1=yes, 0=no
    excluded_by_user    INTEGER DEFAULT 0,
    status              TEXT DEFAULT 'recommended'  -- best | recommended | optional
);
CREATE INDEX IF NOT EXISTS idx_music_frags_file ON music_fragments(audio_file);
