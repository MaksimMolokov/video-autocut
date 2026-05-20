"""
Render History - хранение истории использованных клипов
"""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import List, Set, Tuple, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class RenderRecord:
    """Запись о предыдущем рендере"""
    render_id: str
    timestamp: float
    preset_id: str
    target_duration: float
    used_clips: List[Tuple[str, float, float]] = field(default_factory=list)  # (video_path, start, end)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'render_id': self.render_id,
            'timestamp': self.timestamp,
            'preset_id': self.preset_id,
            'target_duration': self.target_duration,
            'used_clips': [
                {'video_path': v, 'start': s, 'end': e}
                for v, s, e in self.used_clips
            ]
        }

    @classmethod
    def from_dict(cls, data: dict):
        """Create from dictionary"""
        used_clips = [
            (clip['video_path'], clip['start'], clip['end'])
            for clip in data.get('used_clips', [])
        ]
        return cls(
            render_id=data['render_id'],
            timestamp=data['timestamp'],
            preset_id=data['preset_id'],
            target_duration=data['target_duration'],
            used_clips=used_clips
        )


class RenderHistory:
    """
    Хранение истории использованных клипов

    Позволяет избежать повторного выбора одних и тех же фрагментов
    """

    def __init__(self, project_dir: Path):
        """
        Args:
            project_dir: Path to project directory
        """
        self.project_dir = Path(project_dir)
        self.history_file = self.project_dir / ".render_history.json"
        self.records: List[RenderRecord] = []
        self.load()

    def load(self):
        """Загрузить историю из файла"""
        if self.history_file.exists():
            try:
                with open(self.history_file, 'r') as f:
                    data = json.load(f)
                    self.records = [RenderRecord.from_dict(r) for r in data]
                    logger.info(f"Loaded {len(self.records)} render records from history")
            except Exception as e:
                logger.error(f"Failed to load render history: {e}")
                self.records = []
        else:
            logger.info("No render history found, starting fresh")

    def save(self):
        """Сохранить историю в файл"""
        try:
            # Ensure directory exists
            self.project_dir.mkdir(parents=True, exist_ok=True)

            with open(self.history_file, 'w') as f:
                data = [r.to_dict() for r in self.records]
                json.dump(data, f, indent=2)

            logger.info(f"Saved {len(self.records)} render records to history")
        except Exception as e:
            logger.error(f"Failed to save render history: {e}")

    def add_render(self, record: RenderRecord):
        """
        Добавить запись о рендере

        Args:
            record: RenderRecord object
        """
        self.records.append(record)
        self.save()
        logger.info(f"Added render record: {record.render_id} (preset: {record.preset_id})")

    def get_used_clips(self, limit: Optional[int] = None) -> Set[Tuple[str, float, float]]:
        """
        Получить все использованные клипы

        Args:
            limit: If specified, only return clips from last N renders

        Returns:
            Set of (video_path, start, end) tuples
        """
        used = set()

        records_to_check = self.records[-limit:] if limit else self.records

        for record in records_to_check:
            used.update(record.used_clips)

        return used

    def get_last_render(self) -> Optional[RenderRecord]:
        """
        Получить последний рендер

        Returns:
            Last RenderRecord or None
        """
        return self.records[-1] if self.records else None

    def clear(self):
        """Очистить историю"""
        self.records = []
        if self.history_file.exists():
            self.history_file.unlink()
        logger.info("Render history cleared")

    @staticmethod
    def apply_previous_usage_penalty(
        candidates: List,  # List[CandidateClip]
        used_clips: Set[Tuple[str, float, float]],
        penalty: float = 0.5
    ) -> List:
        """
        Применить штраф за использованные ранее клипы

        Если клип уже использовался, снизить его score на penalty

        Args:
            candidates: List of CandidateClip objects
            used_clips: Set of (video_path, start, end) tuples
            penalty: Penalty value (0.0 - 1.0)

        Returns:
            candidates with previous_usage_penalty filled
        """
        if not used_clips:
            # Нет использованных клипов
            for clip in candidates:
                clip.previous_usage_penalty = 0.0
            return candidates

        penalized_count = 0

        for clip in candidates:
            # Check if this clip was used
            # We consider clips "used" if they overlap with used clips
            is_used = RenderHistory._is_clip_used(
                clip.source_path, clip.start, clip.end, used_clips
            )

            if is_used:
                clip.previous_usage_penalty = penalty
                penalized_count += 1
            else:
                clip.previous_usage_penalty = 0.0

        if penalized_count > 0:
            logger.info(
                f"Applied previous usage penalty to {penalized_count}/{len(candidates)} clips "
                f"(penalty={penalty:.2f})"
            )

        return candidates

    @staticmethod
    def _is_clip_used(
        video_path: str,
        start: float,
        end: float,
        used_clips: Set[Tuple[str, float, float]],
        overlap_threshold: float = 0.5
    ) -> bool:
        """
        Проверить, использовался ли клип ранее

        Клип считается использованным, если есть значительное перекрытие (>50%)
        с использованным клипом

        Args:
            video_path: Path to video file
            start, end: Clip boundaries
            used_clips: Set of used clips
            overlap_threshold: Minimum overlap ratio to consider "used"

        Returns:
            True if clip was used
        """
        clip_duration = end - start

        for used_path, used_start, used_end in used_clips:
            # Same video?
            if video_path != used_path:
                continue

            # Calculate overlap
            overlap_start = max(start, used_start)
            overlap_end = min(end, used_end)
            overlap = max(0, overlap_end - overlap_start)

            # Check overlap ratio
            if overlap / clip_duration >= overlap_threshold:
                return True

        return False

    @staticmethod
    def create_render_record(
        preset_id: str,
        target_duration: float,
        selected_clips: List  # List[CandidateClip]
    ) -> RenderRecord:
        """
        Создать RenderRecord из выбранных клипов

        Args:
            preset_id: ID пресета
            target_duration: Target duration
            selected_clips: List of selected CandidateClip objects

        Returns:
            RenderRecord object
        """
        render_id = f"render_{int(time.time())}"

        used_clips = [
            (clip.source_path, clip.start, clip.end)
            for clip in selected_clips
        ]

        return RenderRecord(
            render_id=render_id,
            timestamp=time.time(),
            preset_id=preset_id,
            target_duration=target_duration,
            used_clips=used_clips
        )


if __name__ == "__main__":
    # Test render history
    import tempfile

    temp_dir = Path(tempfile.mkdtemp())
    print(f"Testing RenderHistory in {temp_dir}")

    history = RenderHistory(temp_dir)

    # Add test record
    record = RenderRecord(
        render_id="test_1",
        timestamp=time.time(),
        preset_id="travel_story",
        target_duration=60.0,
        used_clips=[
            ("video1.mp4", 10.0, 15.0),
            ("video1.mp4", 20.0, 25.0),
            ("video2.mp4", 5.0, 10.0),
        ]
    )

    history.add_render(record)
    print(f"✓ Added render record: {record.render_id}")

    # Get used clips
    used = history.get_used_clips()
    print(f"✓ Used clips: {len(used)}")

    # Test loading
    history2 = RenderHistory(temp_dir)
    print(f"✓ Loaded {len(history2.records)} records from disk")

    # Cleanup
    history.clear()
    print("✓ History cleared")
