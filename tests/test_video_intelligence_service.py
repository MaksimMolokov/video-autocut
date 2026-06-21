"""Unit tests for VideoIntelligenceService (VI2-006)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))


def _frag(**kw) -> dict:
    base = dict(
        id=0, start_s=0.0, end_s=5.0,
        sharpness=0.6, camera_shake=0.1, brightness=0.5,
        quality_score=0.6, scene_tags=[], camera_motion_type="static",
    )
    base.update(kw)
    return base


# ── Helpers to build mock analyzer objects ───────────────────────────────────

def _mock_motion():
    r = MagicMock()
    r.motion_type = "dolly"
    r.confidence  = 0.8
    r.speed       = 0.3
    clf = MagicMock()
    clf.classify.return_value = r
    return clf


def _mock_tagger():
    r = MagicMock()
    r.tags          = ["nature", "outdoor"]
    r.primary_tag   = "nature"
    r.scene_context = "outdoor"
    tgr = MagicMock()
    tgr.tag_segment.return_value = r
    return tgr


def _mock_aesthetic():
    sc = MagicMock()
    sc.score.return_value = 0.65
    return sc


def _mock_composition():
    from analysis.content.composition_analyzer import CompositionResult
    res = CompositionResult(
        composition_score=0.65,
        rule_of_thirds_score=0.6,
        horizon_level_score=0.7,
        symmetry_score=0.6,
        subject_position_score=0.5,
        visual_depth_score=0.4,
        background_clutter_score=0.7,
    )
    az = MagicMock()
    az.analyze.return_value = res
    return az


def _mock_pose():
    from analysis.content.pose_analyzer import PoseResult
    res = PoseResult(
        pose_quality_score=0.7, body_crop_quality_score=0.6,
        main_person_area_ratio=0.35, head_visible=True,
        full_body_visible=True, bad_crop=False, reject_reasons=[],
    )
    az = MagicMock()
    az.analyze.return_value = res
    return az


def _mock_eye():
    from analysis.content.eye_state_analyzer import EyeStateResult
    res = EyeStateResult(eyes_open_score=0.85, eyes_detected=True, eye_count=2, face_count=1)
    az = MagicMock()
    az.analyze.return_value = res
    return az


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestVideoIntelligenceServiceImport(unittest.TestCase):

    def test_import_ok(self):
        from backend.services.video_intelligence_service import VideoIntelligenceService
        self.assertTrue(callable(VideoIntelligenceService))

    def test_instantiation(self):
        from backend.services.video_intelligence_service import VideoIntelligenceService
        svc = VideoIntelligenceService()
        self.assertIsNotNone(svc)

    def test_enrich_signature(self):
        from backend.services.video_intelligence_service import VideoIntelligenceService
        import inspect
        sig = inspect.signature(VideoIntelligenceService.enrich)
        self.assertIn("fragments", sig.parameters)
        self.assertIn("video_path", sig.parameters)


class TestVideoIntelligenceEnrich(unittest.TestCase):

    def _run_enrich(self, frags, **kwargs):
        """Patch all module-level lazy-loaders and run enrich()."""
        mod = "backend.services.video_intelligence_service"
        with patch(f"{mod}._load_motion_classifier", return_value=_mock_motion()), \
             patch(f"{mod}._load_semantic_tagger",   return_value=_mock_tagger()), \
             patch(f"{mod}._load_aesthetic_scorer",  return_value=_mock_aesthetic()), \
             patch(f"{mod}._load_composition_analyzer", return_value=_mock_composition()), \
             patch(f"{mod}._load_pose_analyzer",     return_value=_mock_pose()), \
             patch(f"{mod}._load_eye_analyzer",      return_value=_mock_eye()), \
             patch(f"{mod}._load_style_fit_service", return_value=None):
            from backend.services.video_intelligence_service import VideoIntelligenceService
            return VideoIntelligenceService().enrich(frags, "fake.mp4", **kwargs)

    def test_returns_same_list(self):
        frags = [_frag(id=i) for i in range(3)]
        result = self._run_enrich(frags)
        self.assertIs(result, frags)

    def test_vi_score_added(self):
        frags = [_frag(id=0)]
        self._run_enrich(frags)
        self.assertIn("vi_score", frags[0])
        vi = frags[0]["vi_score"]
        self.assertGreaterEqual(vi, 0.0)
        self.assertLessEqual(vi, 1.0)

    def test_semantic_tags_added(self):
        frags = [_frag(id=0)]
        self._run_enrich(frags)
        self.assertIn("semantic_tags", frags[0])
        self.assertIsInstance(frags[0]["semantic_tags"], list)

    def test_camera_motion_added(self):
        frags = [_frag(id=0, camera_motion_type="")]
        self._run_enrich(frags)
        self.assertIn("camera_motion_type", frags[0])

    def test_composition_score_added(self):
        frags = [_frag(id=0)]
        self._run_enrich(frags)
        self.assertIn("composition_score", frags[0])
        self.assertAlmostEqual(frags[0]["composition_score"], 0.65, places=2)

    def test_suggested_role_added(self):
        frags = [_frag(id=0)]
        self._run_enrich(frags)
        self.assertIn("suggested_role", frags[0])
        self.assertIn(frags[0]["suggested_role"],
                      ("intro", "body", "outro", "transition"))

    def test_empty_list_no_crash(self):
        result = self._run_enrich([])
        self.assertEqual(result, [])

    def test_multiple_fragments_all_enriched(self):
        frags = [_frag(id=i) for i in range(5)]
        self._run_enrich(frags)
        for f in frags:
            self.assertIn("vi_score", f)


class TestVIComputeScore(unittest.TestCase):

    def test_compute_vi_score_module_fn(self):
        from backend.services.video_intelligence_service import _compute_vi_score
        score = _compute_vi_score({"quality_score": 0.8, "aesthetic_score": 0.7,
                                   "composition_score": 0.65, "reject_reasons": []})
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)
        self.assertGreater(score, 0.5)

    def test_reject_reasons_reduce_score(self):
        from backend.services.video_intelligence_service import _compute_vi_score
        clean = _compute_vi_score({"quality_score": 0.8, "aesthetic_score": 0.7,
                                   "composition_score": 0.65, "reject_reasons": []})
        dirty = _compute_vi_score({"quality_score": 0.8, "aesthetic_score": 0.7,
                                   "composition_score": 0.65,
                                   "reject_reasons": ["blurry", "shake"]})
        self.assertGreater(clean, dirty)


class TestInferRole(unittest.TestCase):

    def test_aerial_drone_gets_intro(self):
        from backend.services.video_intelligence_service import _infer_role
        frag = _frag(semantic_tags=["drone", "aerial"], camera_motion_type="aerial_forward")
        role, conf = _infer_role(frag)
        self.assertEqual(role, "intro")
        self.assertGreater(conf, 0.5)

    def test_face_static_gets_body(self):
        from backend.services.video_intelligence_service import _infer_role
        frag = _frag(has_face=True, camera_motion_type="static")
        role, conf = _infer_role(frag)
        self.assertEqual(role, "body")

    def test_short_low_quality_gets_transition(self):
        from backend.services.video_intelligence_service import _infer_role
        frag = _frag(start_s=0.0, end_s=1.0, quality_score=0.2)
        role, conf = _infer_role(frag)
        self.assertEqual(role, "transition")


if __name__ == "__main__":
    unittest.main()
