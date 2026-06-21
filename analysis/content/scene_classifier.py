"""
SceneClassifier — classify scenes into content categories (TASK-033).

Rule-based classifier using color histograms and edge density as features.
Optional CLIP-based classifier when torch is available (Level 4).

Output tags: nature, drone, urban, interior, sport, person, food, real_estate, other
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_TAGS = ["nature", "drone", "urban", "interior", "sport", "person", "food", "real_estate", "other"]


class SceneClassifier:
    """Multi-label scene classification."""

    def __init__(self, use_clip: bool = False) -> None:
        self._clip = None
        if use_clip:
            self._init_clip()

    def _init_clip(self) -> None:
        try:
            import open_clip
            import torch
            model, _, preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained="openai")
            self._clip = {"model": model, "preprocess": preprocess}
            logger.info("[SceneClassifier] CLIP model loaded")
        except ImportError:
            logger.info("[SceneClassifier] open_clip not available, using rule-based classifier")

    def classify(self, video_path: str, start_s: float, end_s: float) -> Dict:
        """
        Return {
            scene_tags: List[str],
            primary_tag: str,
            scene_type: str  ('close'|'medium'|'wide'),
        }
        """
        frame = _get_frame(video_path, (start_s + end_s) / 2)
        if frame is None:
            return {"scene_tags": ["other"], "primary_tag": "other", "scene_type": "medium"}

        if self._clip:
            tags = self._classify_clip(frame)
        else:
            tags = self._classify_rules(frame)

        scene_type = _estimate_shot_type(frame)

        return {
            "scene_tags": tags,
            "primary_tag": tags[0] if tags else "other",
            "scene_type": scene_type,
        }

    def _classify_rules(self, frame: np.ndarray) -> List[str]:
        """Color-histogram + edge-density rule classifier."""
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        h_channel = hsv[:, :, 0]
        s_channel = hsv[:, :, 1]
        v_channel = hsv[:, :, 2]

        green_mask = (h_channel > 35) & (h_channel < 90) & (s_channel > 40)
        blue_mask = (h_channel > 90) & (h_channel < 130) & (s_channel > 30)
        green_ratio = float(green_mask.mean())
        blue_ratio = float(blue_mask.mean())
        brightness = float(v_channel.mean() / 255.0)
        saturation = float(s_channel.mean() / 255.0)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        edge_density = float(edges.mean() / 255.0)

        tags = []
        if green_ratio > 0.25 or (blue_ratio > 0.15 and green_ratio > 0.15):
            tags.append("nature")
        if blue_ratio > 0.25 and brightness > 0.5:
            tags.append("drone")
        if edge_density > 0.08 and saturation < 0.4:
            tags.append("urban")
        if edge_density < 0.04 and saturation > 0.2:
            tags.append("interior")

        return tags if tags else ["other"]

    def _classify_clip(self, frame: np.ndarray) -> List[str]:
        import torch
        from PIL import Image
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)
        model = self._clip["model"]
        preprocess = self._clip["preprocess"]
        import open_clip
        tokenizer = open_clip.get_tokenizer("ViT-B-32")

        img_tensor = preprocess(pil_img).unsqueeze(0)
        prompts = [f"a photo of {tag}" for tag in _TAGS]
        text_tokens = tokenizer(prompts)

        with torch.no_grad():
            image_features = model.encode_image(img_tensor)
            text_features = model.encode_text(text_tokens)
            image_features /= image_features.norm(dim=-1, keepdim=True)
            text_features /= text_features.norm(dim=-1, keepdim=True)
            similarity = (image_features @ text_features.T).squeeze(0)
            probs = similarity.softmax(dim=0).tolist()

        top = sorted(zip(_TAGS, probs), key=lambda x: -x[1])
        return [tag for tag, p in top if p > 0.15][:3] or ["other"]


def _estimate_shot_type(frame: np.ndarray) -> str:
    """Estimate shot type from detected subject size heuristic."""
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 30, 100)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return "wide"
    largest = max(contours, key=cv2.contourArea)
    area_ratio = cv2.contourArea(largest) / (h * w)
    if area_ratio > 0.4:
        return "close"
    if area_ratio > 0.1:
        return "medium"
    return "wide"


def _get_frame(video_path: str, t: float):
    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ret, frame = cap.read()
    cap.release()
    return frame if ret else None
