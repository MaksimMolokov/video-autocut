"""CLIP-based semantic scene tagger (Level 4). Requires open_clip-torch."""

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

SCENE_TAGS: List[str] = [
    'nature', 'city', 'interior', 'ocean', 'mountains',
    'people', 'sport', 'food', 'architecture', 'abstract',
]

TAG_LABELS_RU = {
    'nature':       '🌿 природа',
    'city':         '🏙 город',
    'interior':     '🏠 интерьер',
    'ocean':        '🌊 море',
    'mountains':    '⛰️ горы',
    'people':       '👥 люди',
    'sport':        '🏃 спорт',
    'food':         '🍽 еда',
    'architecture': '🏛 архитектура',
    'abstract':     '🎨 абстракция',
}


class ClipTagger:
    """
    Lightweight wrapper around OpenCLIP ViT-B/32.
    Model is loaded lazily on first use and reused across calls.
    Supports CPU / CUDA / Apple Silicon MPS automatically.
    """

    def __init__(self, device: Optional[str] = None):
        self._device = device
        self._model = None
        self._preprocess = None
        self._text_features = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self):
        if self._model is not None:
            return
        import open_clip
        import torch

        if self._device is None:
            if torch.backends.mps.is_available():
                self._device = 'mps'
            elif torch.cuda.is_available():
                self._device = 'cuda'
            else:
                self._device = 'cpu'

        model, _, preprocess = open_clip.create_model_and_transforms(
            'ViT-B-32', pretrained='openai',
        )
        model = model.to(self._device).eval()

        tokenizer = open_clip.get_tokenizer('ViT-B-32')
        texts = tokenizer([f'a photo of {t}' for t in SCENE_TAGS])
        with torch.no_grad():
            tf = model.encode_text(texts.to(self._device))
            tf = tf / tf.norm(dim=-1, keepdim=True)

        self._model = model
        self._preprocess = preprocess
        self._text_features = tf
        logger.info(f'[ClipTagger] Loaded ViT-B/32 on {self._device}')

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def tag_frame(self, frame) -> Optional[str]:
        """
        Classify a single BGR numpy frame.
        Returns a SCENE_TAGS string or None on failure.
        """
        try:
            self._load()
        except Exception as e:
            logger.warning(f'[ClipTagger] Model unavailable: {e}')
            return None
        try:
            import cv2
            import torch
            from PIL import Image

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = self._preprocess(Image.fromarray(rgb)).unsqueeze(0).to(self._device)
            with torch.no_grad():
                feat = self._model.encode_image(img)
                feat = feat / feat.norm(dim=-1, keepdim=True)
                idx = int((feat @ self._text_features.T).squeeze(0).argmax())
            return SCENE_TAGS[idx]
        except Exception as e:
            logger.debug(f'[ClipTagger] tag_frame error: {e}')
            return None

    def tag_scene(
        self,
        video_path: str,
        start_s: float,
        end_s: float,
    ) -> Optional[str]:
        """
        Tag a scene by sampling the middle frame.
        Returns a SCENE_TAGS string or None on failure.
        """
        try:
            import cv2
            mid = (start_s + end_s) / 2.0
            cap = cv2.VideoCapture(video_path)
            cap.set(cv2.CAP_PROP_POS_MSEC, mid * 1000.0)
            ret, frame = cap.read()
            cap.release()
            if not ret or frame is None:
                return None
            return self.tag_frame(frame)
        except Exception as e:
            logger.debug(f'[ClipTagger] tag_scene error: {e}')
            return None


def tag_label_ru(tag: Optional[str]) -> str:
    """Return localised emoji label for a SCENE_TAG string."""
    if tag is None:
        return ''
    return TAG_LABELS_RU.get(tag, tag)
