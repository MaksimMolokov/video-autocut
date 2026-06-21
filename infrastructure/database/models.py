"""
SQLAlchemy ORM models — full data model per TZ section 11.

Entities (TZ list):
  User, Project, SourceVideo, SourceAudio, Scene, Shot, ClipCandidate,
  QualityMetrics, AudioBeatMap, MusicSection, StylePreset, OutputFormat,
  Timeline, TimelineSegment, Transition, ManualSelection, RenderJob,
  ExportFile, RenderFeedback, ManualSegment, Duplicate, SchemaVersion.

Critical fields per TZ:
  - relative paths (not absolute)
  - schema_version, project_version, preset_version
  - render_config_snapshot, analysis_config_snapshot
"""
from __future__ import annotations

import time

from sqlalchemy import (
    Boolean, Column, Float, ForeignKey, Integer,
    String, Text, JSON, UniqueConstraint, create_engine,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ── Schema version (TZ: schema_version) ───────────────────────────────────────

class SchemaVersion(Base):
    __tablename__ = "schema_version"

    id = Column(Integer, primary_key=True)
    version = Column(Integer, nullable=False)
    applied_at = Column(Float, default=time.time)
    description = Column(String(256), default="")


# ── Project (TZ: Project) ─────────────────────────────────────────────────────

class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    name = Column(String(256), nullable=False)
    root_path = Column(String(1024), nullable=False, unique=True)  # absolute only here
    created_at = Column(Float, default=time.time)
    updated_at = Column(Float, default=time.time)

    # TZ: project_version, schema_version
    schema_version = Column(Integer, default=2)
    project_version = Column(Integer, default=1)

    # TZ: analysis_config_snapshot (what settings were used during analysis)
    analysis_config_snapshot = Column(JSON)

    source_videos = relationship("SourceVideo", back_populates="project", cascade="all, delete-orphan")
    source_audios = relationship("SourceAudio", back_populates="project", cascade="all, delete-orphan")
    timelines = relationship("Timeline", back_populates="project", cascade="all, delete-orphan")
    render_jobs = relationship("RenderJob", back_populates="project", cascade="all, delete-orphan")
    manual_selections = relationship("ManualSelection", back_populates="project", cascade="all, delete-orphan")


# ── SourceVideo (TZ: SourceVideo) ─────────────────────────────────────────────

class SourceVideo(Base):
    __tablename__ = "source_videos"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    rel_path = Column(String(1024), nullable=False)   # relative to project root
    filename = Column(String(512))
    duration_s = Column(Float)
    fps = Column(Float)
    width = Column(Integer)
    height = Column(Integer)
    codec = Column(String(64))
    file_size = Column(Integer)
    file_hash = Column(String(64))
    analyzed_at = Column(Float)
    status = Column(String(32), default="pending")    # pending | analyzed | error
    error_msg = Column(Text)

    project = relationship("Project", back_populates="source_videos")
    scenes = relationship("Scene", back_populates="source_video", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("project_id", "rel_path"),)


# ── SourceAudio (TZ: SourceAudio) ─────────────────────────────────────────────

class SourceAudio(Base):
    __tablename__ = "source_audios"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    rel_path = Column(String(1024), nullable=False)
    filename = Column(String(512))
    duration_s = Column(Float)
    file_hash = Column(String(64))
    analyzed_at = Column(Float)
    status = Column(String(32), default="pending")

    project = relationship("Project", back_populates="source_audios")
    beat_maps = relationship("AudioBeatMap", back_populates="source_audio", cascade="all, delete-orphan")
    music_sections = relationship("MusicSection", back_populates="source_audio", cascade="all, delete-orphan")


# ── Scene (TZ: Scene) ─────────────────────────────────────────────────────────

class Scene(Base):
    """A detected scene within a source video."""
    __tablename__ = "scenes"

    id = Column(Integer, primary_key=True)
    source_video_id = Column(Integer, ForeignKey("source_videos.id"), nullable=False)
    start_s = Column(Float, nullable=False)
    end_s = Column(Float, nullable=False)
    duration_s = Column(Float, nullable=False)
    scene_index = Column(Integer)

    source_video = relationship("SourceVideo", back_populates="scenes")
    shots = relationship("Shot", back_populates="scene", cascade="all, delete-orphan")
    clip_candidates = relationship("ClipCandidate", back_populates="scene", cascade="all, delete-orphan")


# ── Shot (TZ: Shot) ───────────────────────────────────────────────────────────

class Shot(Base):
    """A detected cut/dissolve point within a scene."""
    __tablename__ = "shots"

    id = Column(Integer, primary_key=True)
    scene_id = Column(Integer, ForeignKey("scenes.id"), nullable=False)
    start_s = Column(Float, nullable=False)
    end_s = Column(Float, nullable=False)
    shot_type = Column(String(32))       # cut | dissolve | fade | interior
    confidence = Column(Float)

    scene = relationship("Scene", back_populates="shots")


# ── QualityMetrics (TZ: QualityMetrics) ──────────────────────────────────────

class QualityMetrics(Base):
    """Technical quality metrics for a scene — stored separately."""
    __tablename__ = "quality_metrics"

    id = Column(Integer, primary_key=True)
    scene_id = Column(Integer, ForeignKey("scenes.id"), unique=True, nullable=False)

    # Technical (TASK-022, 023, 024)
    sharpness = Column(Float)
    blur_score = Column(Float)
    brightness = Column(Float)
    contrast = Column(Float)
    noise_level = Column(Float)
    colorfulness = Column(Float)
    saturation = Column(Float)

    # Motion / stability
    motion_magnitude = Column(Float)
    camera_shake = Column(Float)
    camera_motion_type = Column(String(32))    # static | pan | tilt | zoom | shake
    optical_flow_mean = Column(Float)

    # Content
    face_count = Column(Integer, default=0)
    face_size_ratio = Column(Float)
    person_count = Column(Integer, default=0)
    has_face = Column(Boolean, default=False)
    has_person = Column(Boolean, default=False)

    # Composition
    composition_score = Column(Float)
    saliency_score = Column(Float)
    rule_of_thirds_score = Column(Float)
    aesthetic_score = Column(Float)

    # Scene classification
    scene_type = Column(String(32))            # close | medium | wide
    scene_tags = Column(JSON)                  # ["nature", "drone"]
    primary_scene_tag = Column(String(64))

    # Quality flags
    is_blurry = Column(Boolean, default=False)
    is_shaky = Column(Boolean, default=False)
    is_dark = Column(Boolean, default=False)
    is_duplicate = Column(Boolean, default=False)
    reject_reason = Column(String(64))

    scene = relationship("Scene", uselist=False)


# ── ClipCandidate (TZ: ClipCandidate) ────────────────────────────────────────

class ClipCandidate(Base):
    """A scene that passed quality filters and is a candidate for timeline."""
    __tablename__ = "clip_candidates"

    id = Column(Integer, primary_key=True)
    # scene_id is kept for FK compatibility but timing is stored directly below
    scene_id = Column(Integer, ForeignKey("scenes.id"), nullable=True)
    # Direct reference to source file (avoids needing Scene join for cache reads)
    source_file_id = Column(Integer, ForeignKey("source_videos.id"), nullable=True)

    # Timing — stored directly so cache reads don't need a Scene join
    start_s = Column(Float)
    end_s = Column(Float)
    duration_s = Column(Float)
    source_filename = Column(String(512))  # original filename for display

    # Composite scores (per TZ: separate technical, content, style scores)
    technical_score = Column(Float)      # sharpness + stability + exposure
    content_score = Column(Float)        # faces, persons, subject presence
    aesthetic_score = Column(Float)      # composition, color harmony
    quality_score = Column(Float)        # UMS: weighted combination

    # Extra quality metrics for UI
    sharpness = Column(Float)
    brightness = Column(Float)
    camera_shake = Column(Float)
    camera_motion_type = Column(String(32))
    has_face = Column(Boolean, default=False)
    has_person = Column(Boolean, default=False)
    scene_tags = Column(JSON)
    is_duplicate = Column(Boolean, default=False)
    reject_reason = Column(Text)

    # Style-specific scores (computed per preset)
    style_scores = Column(JSON)          # {"cinematic_nature": 0.8, "fast_reels": 0.5, ...}

    # Selection reason — explainability (TZ section 15 point 9)
    selection_reason = Column(Text)      # "High sharpness, stable, wide shot with sky"
    rejection_reason = Column(Text)      # "Too blurry (score 0.03 < threshold 0.04)"

    # User interaction
    user_approved = Column(Integer)      # NULL | 1 | 0
    user_priority = Column(Boolean, default=False)
    is_pinned = Column(Boolean, default=False)
    is_excluded = Column(Boolean, default=False)

    # Thumbnail
    thumbnail_rel_path = Column(String(1024))
    preview_rel_path = Column(String(1024))

    scene = relationship("Scene", back_populates="clip_candidates")
    source_video = relationship("SourceVideo")


# ── Duplicate ─────────────────────────────────────────────────────────────────

class Duplicate(Base):
    __tablename__ = "duplicates"

    id = Column(Integer, primary_key=True)
    candidate_id_a = Column(Integer, ForeignKey("clip_candidates.id"), nullable=False)
    candidate_id_b = Column(Integer, ForeignKey("clip_candidates.id"), nullable=False)
    similarity = Column(Float)
    method = Column(String(32), default="phash")    # phash | embedding


# ── AudioBeatMap (TZ: AudioBeatMap) ──────────────────────────────────────────

class AudioBeatMap(Base):
    __tablename__ = "audio_beat_maps"

    id = Column(Integer, primary_key=True)
    source_audio_id = Column(Integer, ForeignKey("source_audios.id"), nullable=False)
    bpm = Column(Float)
    beat_times = Column(JSON)           # [0.5, 1.0, 1.5, ...]
    beat_strengths = Column(JSON)       # [0.8, 0.6, 0.9, ...]
    strong_beats = Column(JSON)         # downbeat positions
    onset_times = Column(JSON)
    beat_clarity = Column(Float)
    analyzed_at = Column(Float, default=time.time)

    source_audio = relationship("SourceAudio", back_populates="beat_maps")


# ── MusicSection (TZ: MusicSection) ──────────────────────────────────────────

class MusicSection(Base):
    __tablename__ = "music_sections"

    id = Column(Integer, primary_key=True)
    source_audio_id = Column(Integer, ForeignKey("source_audios.id"), nullable=False)
    start_s = Column(Float)
    end_s = Column(Float)
    duration_s = Column(Float)
    section_type = Column(String(32))   # intro | verse | chorus | drop | bridge | breakdown | buildup | outro
    energy_score = Column(Float)
    rhythm_score = Column(Float)
    montage_score = Column(Float)
    status = Column(String(32))         # best | recommended | optional

    selected_by_system = Column(Boolean, default=False)
    selected_by_user = Column(Integer)
    excluded_by_user = Column(Boolean, default=False)

    source_audio = relationship("SourceAudio", back_populates="music_sections")


# ── StylePreset (TZ: StylePreset) ─────────────────────────────────────────────

class StylePreset(Base):
    """Cached preset metadata from YAML files."""
    __tablename__ = "style_presets"

    id = Column(Integer, primary_key=True)
    preset_id = Column(String(64), unique=True, nullable=False)
    name = Column(String(128))
    description = Column(Text)
    dynamic_level = Column(String(32))
    # TZ: preset_version
    preset_version = Column(Integer, default=1)
    config_snapshot = Column(JSON)           # full YAML contents at time of use
    updated_at = Column(Float, default=time.time)


# ── OutputFormat (TZ: OutputFormat — separate from style!) ────────────────────

class OutputFormat(Base):
    """Output format config — independent of style (TZ section 8)."""
    __tablename__ = "output_formats"

    id = Column(Integer, primary_key=True)
    format_id = Column(String(64), unique=True, nullable=False)
    name = Column(String(128))
    aspect_ratio = Column(String(16))       # "9:16" | "16:9" | "1:1" | "21:9"
    width = Column(Integer)
    height = Column(Integer)
    fps = Column(Integer, default=30)
    crop_strategy = Column(String(32))      # smart | center | left | right
    codec = Column(String(32), default="h264")
    bitrate = Column(String(16))


# ── Timeline (TZ: Timeline) ───────────────────────────────────────────────────

class Timeline(Base):
    __tablename__ = "timelines"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    preset_id = Column(String(64))
    format_id = Column(String(64))
    target_duration_s = Column(Float)
    actual_duration_s = Column(Float)
    variant_id = Column(String(4))          # A | B | C | D
    seed_offset = Column(Integer, default=0)
    created_at = Column(Float, default=time.time)
    is_approved = Column(Boolean, default=False)

    # TZ: render_config_snapshot
    render_config_snapshot = Column(JSON)

    project = relationship("Project", back_populates="timelines")
    segments = relationship("TimelineSegment", back_populates="timeline", cascade="all, delete-orphan")


# ── TimelineSegment (TZ: TimelineSegment) ────────────────────────────────────

class TimelineSegment(Base):
    __tablename__ = "timeline_segments"

    id = Column(Integer, primary_key=True)
    timeline_id = Column(Integer, ForeignKey("timelines.id"), nullable=False)
    position = Column(Integer, nullable=False)     # order in timeline
    source_video_rel_path = Column(String(1024))   # relative path
    start_s = Column(Float, nullable=False)
    end_s = Column(Float, nullable=False)
    duration_s = Column(Float)
    role = Column(String(32))              # intro | main | outro
    score = Column(Float)
    is_pinned = Column(Boolean, default=False)
    is_required = Column(Boolean, default=False)

    # Selection explainability (TZ section 15 point 9)
    selection_reason = Column(Text)

    timeline = relationship("Timeline", back_populates="segments")
    transition_after = relationship("Transition", uselist=False,
                                    foreign_keys="[Transition.segment_id]",
                                    cascade="all, delete-orphan")


# ── Transition (TZ: Transition) ───────────────────────────────────────────────

class Transition(Base):
    __tablename__ = "transitions"

    id = Column(Integer, primary_key=True)
    segment_id = Column(Integer, ForeignKey("timeline_segments.id"), nullable=False)
    transition_type = Column(String(32))   # cut | crossfade | fade | flash | zoom | blur
    duration_s = Column(Float, default=0.0)
    is_beat_aligned = Column(Boolean, default=False)


# ── ManualSelection (TZ: ManualSelection) ─────────────────────────────────────

class ManualSelection(Base):
    """User manual markup: pin, exclude, required range, forbidden range."""
    __tablename__ = "manual_selections"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    source_rel_path = Column(String(1024), nullable=False)
    start_s = Column(Float, nullable=False)
    end_s = Column(Float, nullable=False)
    duration_s = Column(Float)
    action = Column(String(32), nullable=False)    # pin | exclude | required | forbidden | trim
    tags = Column(JSON)
    note = Column(Text)
    status = Column(String(32), default="active")  # active | deleted
    created_at = Column(Float, default=time.time)

    project = relationship("Project", back_populates="manual_selections")


# ── RenderJob (TZ: RenderJob) ─────────────────────────────────────────────────

class RenderJob(Base):
    __tablename__ = "render_jobs"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    timeline_id = Column(Integer, ForeignKey("timelines.id"), nullable=True)
    preset_id = Column(String(64))
    format_id = Column(String(64))
    target_duration_s = Column(Float)
    actual_duration_s = Column(Float)
    clip_count = Column(Integer)
    quality_avg = Column(Float)
    variant_id = Column(String(4))
    is_preview = Column(Boolean, default=False)    # True = 480p preview, False = final
    created_at = Column(Float, default=time.time)
    completed_at = Column(Float)
    status = Column(String(32), default="pending") # pending | rendering | done | failed
    error_msg = Column(Text)

    # TZ: render_config_snapshot
    render_config_snapshot = Column(JSON)

    project = relationship("Project", back_populates="render_jobs")
    export_files = relationship("ExportFile", back_populates="render_job", cascade="all, delete-orphan")
    feedback = relationship("RenderFeedback", uselist=False, back_populates="render_job",
                            cascade="all, delete-orphan")


# ── ExportFile (TZ: ExportFile) ───────────────────────────────────────────────

class ExportFile(Base):
    __tablename__ = "export_files"

    id = Column(Integer, primary_key=True)
    render_job_id = Column(Integer, ForeignKey("render_jobs.id"), nullable=False)
    rel_path = Column(String(1024))         # relative to project root
    format_id = Column(String(64))
    width = Column(Integer)
    height = Column(Integer)
    duration_s = Column(Float)
    file_size = Column(Integer)
    codec = Column(String(32))
    created_at = Column(Float, default=time.time)

    render_job = relationship("RenderJob", back_populates="export_files")


# ── RenderFeedback (TZ: RenderFeedback) ──────────────────────────────────────

class RenderFeedback(Base):
    """User rating and feedback on a render — to be used in future scoring."""
    __tablename__ = "render_feedback"

    id = Column(Integer, primary_key=True)
    render_job_id = Column(Integer, ForeignKey("render_jobs.id"), nullable=False)
    rating = Column(Integer)              # 1–5 stars
    liked_segments = Column(JSON)        # list of (source_rel_path, start_s, end_s)
    disliked_segments = Column(JSON)
    comment = Column(Text)
    created_at = Column(Float, default=time.time)

    render_job = relationship("RenderJob", back_populates="feedback")


# ══════════════════════════════════════════════════════════════════════════════
# VIDEO INTELLIGENCE LAYER (Phase 1)
# ══════════════════════════════════════════════════════════════════════════════

class SegmentFeatureProfile(Base):
    """
    Enriched per-segment intelligence: camera motion, people pose, semantic tags.
    One row per ClipCandidate — filled after the intelligence analysis pass.
    """
    __tablename__ = "segment_feature_profiles"

    id = Column(Integer, primary_key=True)
    candidate_id = Column(Integer, ForeignKey("clip_candidates.id"), unique=True, nullable=False)

    # Camera motion (15 types)
    camera_motion_type = Column(String(64))     # static|pan_left|pan_right|tilt_up|tilt_down|
                                                # zoom_in|zoom_out|dolly|orbit|handheld|
                                                # aerial_forward|aerial_descent|shake|roll|unknown
    camera_motion_confidence = Column(Float)
    camera_motion_speed = Column(String(16))    # slow | medium | fast

    # People intelligence
    eye_state = Column(String(16))              # open | closed | partial | none
    pose_type = Column(String(32))              # standing | sitting | walking | action | none
    body_crop_quality = Column(Float)           # 0–1: how well the body fits the frame
    human_frame_quality = Column(Float)         # composite: eye open + good pose + good crop

    # Semantic tags (rule-based + optional CLIP)
    semantic_tags = Column(JSON)                # ["drone", "sunset", "crowd", "sport"]
    primary_semantic_tag = Column(String(64))
    scene_context = Column(String(64))          # indoor | outdoor | studio | nature | urban

    # Face sharpness, exposure, noise (extended quality from Phase 2)
    face_sharpness = Column(Float)
    motion_blur_score = Column(Float)
    exposure_score = Column(Float)              # 0 = under, 1 = good, 2 = over
    noise_score = Column(Float)
    horizon_level = Column(Float)               # 0 = horizontal horizon, >0 = tilted

    # Timeline role hints
    suggested_role = Column(String(16))         # intro | body | outro | transition
    role_confidence = Column(Float)

    analyzed_at = Column(Float, default=time.time)

    candidate = relationship("ClipCandidate", uselist=False)


class SegmentStyleFit(Base):
    """
    Per-segment, per-style fitness score — computed by StyleFitService.
    Updated whenever a new style is evaluated.
    """
    __tablename__ = "segment_style_fits"

    id = Column(Integer, primary_key=True)
    candidate_id = Column(Integer, ForeignKey("clip_candidates.id"), nullable=False)
    style_preset_id = Column(String(64), nullable=False)  # matches StylePreset.preset_id

    fit_score = Column(Float)                   # 0–1 composite
    motion_fit = Column(Float)                  # camera motion matches style energy
    semantic_fit = Column(Float)                # semantic tags match style rules
    role_fit = Column(Float)                    # role suggestion matches style needs
    quality_fit = Column(Float)                 # technical quality meets style threshold

    explanation = Column(Text)                  # "Fast pan matches high-energy style"
    computed_at = Column(Float, default=time.time)

    candidate = relationship("ClipCandidate")
    __table_args__ = (UniqueConstraint("candidate_id", "style_preset_id"),)


class VideoConcept(Base):
    """
    High-level concept inferred for the project — used to guide timeline assembly.
    One concept per project (can have multiple candidates, one is active).
    """
    __tablename__ = "video_concepts"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)

    concept_type = Column(String(64))           # travel | wedding | sport | event | product | other
    narrative_arc = Column(String(64))          # three_act | highlight_reel | journey | montage
    dominant_tags = Column(JSON)                # top semantic tags across all clips
    energy_profile = Column(String(32))         # low | medium | high | dynamic

    description = Column(Text)                  # human-readable concept summary
    is_active = Column(Boolean, default=True)
    confidence = Column(Float)

    created_at = Column(Float, default=time.time)
    updated_at = Column(Float, default=time.time)

    project = relationship("Project")


class AnalysisCache(Base):
    """
    Content-addressed cache for expensive per-frame analysis results
    (e.g. CLIP embeddings, face mesh, deep optical flow).
    Key: SHA-256 of (file_path + start_s + end_s + analysis_type + model_version).
    """
    __tablename__ = "analysis_cache"

    id = Column(Integer, primary_key=True)
    cache_key = Column(String(64), unique=True, nullable=False)  # SHA-256 hex
    analysis_type = Column(String(64), nullable=False)   # clip_embedding | face_mesh | flow | ...
    model_version = Column(String(32))
    source_rel_path = Column(String(1024))
    start_s = Column(Float)
    end_s = Column(Float)
    result = Column(JSON)                       # serialized analysis output
    result_blob_path = Column(String(1024))     # for large arrays: path to .npy file
    created_at = Column(Float, default=time.time)
    expires_at = Column(Float)                  # NULL = never expires


# ── Engine factory ────────────────────────────────────────────────────────────

def create_db_engine(db_path: str, echo: bool = False):
    return create_engine(
        f"sqlite:///{db_path}",
        echo=echo,
        connect_args={"check_same_thread": False},
    )


def init_db(engine) -> None:
    Base.metadata.create_all(engine)
