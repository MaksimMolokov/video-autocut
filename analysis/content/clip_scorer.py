"""
CLIPScorer — семантическая релевантность кадра тексту (ROADMAP Фаза 5, SEM-1; PDF §3).

Кодирует кадр и текстовый промпт-сценарий в один вектор (CLIP) и считает косинусную
близость → «насколько кадр соответствует теме/стилю». Это реальный сигнал M_semantic
вместо эвристических тегов (ARCHITECTURE §10.7).

Зависимости (опциональны): ``open_clip_torch`` + ``torch`` (закомментированы в
requirements). Если их нет — ``available == False`` и весь модуль тихо no-op:
вызывающий код продолжает работать на эвристике.
"""
from __future__ import annotations

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

# Промпты под стиль/концепцию (PDF §3.1: "cinematic lighting, perfectly framed…").
_STYLE_PROMPTS = {
    "cinematic_nature": "cinematic epic landscape, beautiful nature, perfect lighting",
    "dynamic_travel":   "dynamic travel shot, scenic location, vibrant colors",
    "drone_smooth":     "smooth aerial drone shot, wide landscape from above",
    "fast_reels":       "energetic action moment, dynamic motion, eye-catching",
    "family_memories":  "warm candid moment with people, happy faces, emotional",
    "luxury_promo":     "premium luxury product, clean elegant composition, high quality",
    "real_estate":      "clean interior of a modern home, well-lit spacious room",
    "fpv_action":       "extreme fpv action sports, fast motion, adrenaline",
}
_DEFAULT_PROMPT = "high quality, well composed, visually interesting shot"


def prompt_for(style_id: Optional[str], concept_type: Optional[str] = None) -> str:
    """Подобрать текстовый промпт по стилю (и опц. концепции)."""
    p = _STYLE_PROMPTS.get(style_id or "", "")
    if not p and concept_type:
        p = f"beautiful {concept_type} footage, high quality, well composed"
    return p or _DEFAULT_PROMPT


class CLIPScorer:
    """Скорер CLIP с ленивой загрузкой и мягкой деградацией."""

    _model = None
    _preprocess = None
    _tokenizer = None
    _torch = None
    _failed = False

    def __init__(self, model_name: str = "ViT-B-32", pretrained: str = "laion2b_s34b_b79k"):
        self._model_name = model_name
        self._pretrained = pretrained

    @property
    def available(self) -> bool:
        return self._ensure_loaded()

    # ── загрузка модели (один раз на процесс) ────────────────────────────────
    def _ensure_loaded(self) -> bool:
        cls = CLIPScorer
        if cls._failed:
            return False
        if cls._model is not None:
            return True
        # Выключено по умолчанию: импорт torch конфликтует с file-watcher Streamlit
        # и грузит тяжёлую модель. Включается явно: ENABLE_CLIP_SCORING=1.
        import os
        if os.getenv("ENABLE_CLIP_SCORING", "0") != "1":
            cls._failed = True
            return False
        try:
            import open_clip          # импортируем ПЕРЕД torch: если его нет —
            import torch              # ImportError до импорта torch
            model, _, preprocess = open_clip.create_model_and_transforms(
                self._model_name, pretrained=self._pretrained
            )
            model.eval()
            cls._model = model
            cls._preprocess = preprocess
            cls._tokenizer = open_clip.get_tokenizer(self._model_name)
            cls._torch = torch
            logger.info("[CLIP] загружен %s/%s", self._model_name, self._pretrained)
            return True
        except Exception as exc:
            logger.info("[CLIP] недоступен (%s) — M_semantic останется эвристическим", exc)
            cls._failed = True
            return False

    # ── эмбеддинг кадра ──────────────────────────────────────────────────────
    def embed_frame(self, video_path: str, t_s: float):
        """Вернуть нормированный image-эмбеддинг кадра в момент t_s или None."""
        if not self._ensure_loaded():
            return None
        try:
            import cv2
            from PIL import Image
            cap = cv2.VideoCapture(video_path)
            cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t_s) * 1000.0)
            ok, frame = cap.read()
            cap.release()
            if not ok or frame is None:
                return None
            img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            torch = CLIPScorer._torch
            with torch.no_grad():
                tensor = CLIPScorer._preprocess(img).unsqueeze(0)
                feat = CLIPScorer._model.encode_image(tensor)
                feat = feat / feat.norm(dim=-1, keepdim=True)
            return feat
        except Exception as exc:
            logger.debug("[CLIP] embed_frame failed: %s", exc)
            return None

    def embed_text(self, prompt: str):
        if not self._ensure_loaded():
            return None
        try:
            torch = CLIPScorer._torch
            with torch.no_grad():
                tokens = CLIPScorer._tokenizer([prompt])
                feat = CLIPScorer._model.encode_text(tokens)
                feat = feat / feat.norm(dim=-1, keepdim=True)
            return feat
        except Exception as exc:
            logger.debug("[CLIP] embed_text failed: %s", exc)
            return None

    def zero_shot_fragments(self, fragments: List[dict], labels: List[str],
                            path_key: str = "_abs_path", max_frames: int = 24) -> dict:
        """Zero-shot классификация концепции (ROADMAP Фаза 5, SEM-2; PDF §3).

        Усредняет softmax-вероятности меток по кадрам фрагментов. Возвращает
        {label: prob} (нормированный), либо {} если CLIP недоступен.
        """
        if not self._ensure_loaded() or not labels:
            return {}
        torch = CLIPScorer._torch
        text_feats = []
        for lbl in labels:
            tf = self.embed_text(f"a video of {lbl}")
            if tf is None:
                return {}
            text_feats.append(tf)
        text_mat = torch.cat(text_feats, dim=0)              # [L, D]
        acc = [0.0] * len(labels)
        n = 0
        for f in fragments[:max_frames]:
            emb = f.get("_clip_embed")
            if emb is None:
                t = (float(f.get("start_s", 0)) + float(f.get("end_s", 0))) / 2.0
                emb = self.embed_frame(f.get(path_key, ""), t)
                f["_clip_embed"] = emb
            if emb is None:
                continue
            with torch.no_grad():
                logits = (emb @ text_mat.T) * 100.0          # CLIP temperature
                probs = logits.softmax(dim=-1).squeeze(0).tolist()
            for i, p in enumerate(probs):
                acc[i] += float(p)
            n += 1
        if n == 0:
            return {}
        return {lbl: round(acc[i] / n, 4) for i, lbl in enumerate(labels)}

    def score_fragments(self, fragments: List[dict], prompt: str,
                         path_key: str = "_abs_path") -> int:
        """Проставить ``clip_score`` ∈ [0,1] каждому фрагменту. Вернуть число обработанных.

        Эмбеддинг кадра кэшируется на фрагменте (``_clip_embed``), чтобы при смене
        стиля/промпта не пересчитывать тяжёлую часть.
        """
        if not self._ensure_loaded():
            return 0
        text = self.embed_text(prompt)
        if text is None:
            return 0
        torch = CLIPScorer._torch
        done = 0
        for f in fragments:
            emb = f.get("_clip_embed")
            if emb is None:
                t = (float(f.get("start_s", 0)) + float(f.get("end_s", 0))) / 2.0
                emb = self.embed_frame(f.get(path_key, ""), t)
                f["_clip_embed"] = emb
            if emb is None:
                continue
            with torch.no_grad():
                sim = float((emb @ text.T).item())          # косинус ∈ [-1,1]
            f["clip_score"] = max(0.0, min(1.0, (sim + 1.0) / 2.0))
            done += 1
        return done
