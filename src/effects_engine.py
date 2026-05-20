"""
Effects Engine - applies visual effects to video segments
Generates FFmpeg filter commands for transitions, color grading, speed effects, etc.
"""

from typing import List, Optional
from src.effects_config import (
    EffectsConfiguration, TransitionType, SpeedMode, ColorStyle
)


class EffectsEngine:
    """Applies effects to video segments using FFmpeg filters"""

    @staticmethod
    def generate_transition_filter(
        transition_type: TransitionType,
        duration: float,
        total_segments: int
    ) -> Optional[str]:
        """
        Generate FFmpeg xfade filter for transitions

        Args:
            transition_type: Type of transition
            duration: Transition duration in seconds
            total_segments: Total number of segments

        Returns:
            FFmpeg filter string or None for CUT
        """
        if transition_type == TransitionType.CUT or duration <= 0:
            return None

        # Map our transition types to xfade transitions
        xfade_transitions = {
            TransitionType.CROSSFADE: "fade",
            TransitionType.FADE: "fadeblack",
            TransitionType.ZOOM: "zoomin",
            TransitionType.SWIPE: "slideleft",
            TransitionType.BLUR: "smoothleft",
            TransitionType.FLASH: "fadewhite"
        }

        xfade_type = xfade_transitions.get(transition_type, "fade")

        # Build xfade filter chain for multiple segments
        # Format: [0][1]xfade=transition=TYPE:duration=DUR:offset=OFFSET[v01];
        #         [v01][2]xfade=transition=TYPE:duration=DUR:offset=OFFSET[v02];
        #         ...

        return xfade_type

    @staticmethod
    def generate_speed_filter(speed_mode: SpeedMode, factor: float = 1.0) -> Optional[str]:
        """
        Generate FFmpeg setpts filter for speed effects

        Args:
            speed_mode: Speed effect mode
            factor: Speed factor (0.5 = half speed, 2.0 = double speed)

        Returns:
            FFmpeg filter string or None
        """
        if speed_mode == SpeedMode.NONE:
            return None

        if speed_mode == SpeedMode.SLOW_MOTION:
            # Slow motion: factor < 1.0
            # setpts=PTS/FACTOR - higher divisor = slower
            pts_factor = 1.0 / factor  # e.g., 0.75 speed = PTS/0.75 = PTS*1.33
            return f"setpts={pts_factor}*PTS"

        elif speed_mode == SpeedMode.SPEED_UP:
            # Speed up: factor > 1.0
            pts_factor = 1.0 / factor  # e.g., 1.25 speed = PTS/1.25 = PTS*0.8
            return f"setpts={pts_factor}*PTS"

        elif speed_mode == SpeedMode.SPEED_RAMP:
            # Speed ramp would require more complex expression
            # For now, use average factor
            pts_factor = 1.0 / factor
            return f"setpts={pts_factor}*PTS"

        elif speed_mode == SpeedMode.AUTO_DYNAMIC:
            # Auto dynamic - apply slight variations
            # For MVP, use no change
            return None

        return None

    @staticmethod
    def generate_color_filter(
        color_style: ColorStyle,
        brightness: float = 0.0,
        contrast: float = 0.0,
        saturation: float = 0.0,
        temperature: float = 0.0
    ) -> Optional[str]:
        """
        Generate FFmpeg color grading filters

        Args:
            color_style: Color grading style
            brightness: Brightness adjustment (-1.0 to 1.0)
            contrast: Contrast adjustment (-1.0 to 1.0)
            saturation: Saturation adjustment (-1.0 to 1.0)
            temperature: Color temperature adjustment (-1.0 to 1.0)

        Returns:
            FFmpeg filter string or None
        """
        if color_style == ColorStyle.NONE:
            return None

        filters = []

        # Apply style presets
        if color_style == ColorStyle.BASIC_ENHANCE:
            filters.append("eq=brightness=0.02:contrast=1.05:saturation=1.05")

        elif color_style == ColorStyle.CINEMATIC:
            filters.append("eq=contrast=1.1:saturation=0.95:gamma=0.95")
            filters.append("curves=vintage")

        elif color_style == ColorStyle.NATURAL:
            filters.append("eq=saturation=0.98:gamma=1.02")

        elif color_style == ColorStyle.WARM:
            # Warm look - shift towards red/yellow
            filters.append("eq=brightness=0.02:contrast=1.05:saturation=1.1")
            filters.append("colorbalance=rs=0.1:gs=-0.05:bs=-0.1")

        elif color_style == ColorStyle.HIGH_CONTRAST:
            filters.append("eq=contrast=1.15:saturation=1.15")

        # Apply manual adjustments if provided
        if abs(brightness) > 0.01 or abs(contrast) > 0.01 or abs(saturation) > 0.01:
            # Convert adjustments to eq filter values
            eq_brightness = brightness * 0.5  # Scale to reasonable range
            eq_contrast = 1.0 + contrast  # 0.0 → 1.0, 0.1 → 1.1
            eq_saturation = 1.0 + saturation

            filters.append(f"eq=brightness={eq_brightness}:contrast={eq_contrast}:saturation={eq_saturation}")

        # Temperature adjustment (color balance)
        if abs(temperature) > 0.01:
            # Positive = warmer (more red/yellow), negative = cooler (more blue)
            rs = temperature * 0.2  # Red shadows
            bs = -temperature * 0.2  # Blue shadows (opposite)
            filters.append(f"colorbalance=rs={rs}:bs={bs}")

        return ",".join(filters) if filters else None

    @staticmethod
    def build_filter_complex(
        effects_config: EffectsConfiguration,
        segments: List,
        include_audio: bool = True
    ) -> str:
        """
        Build complete FFmpeg filter_complex string

        Args:
            effects_config: Effects configuration
            segments: List of video segments
            include_audio: Whether to include audio filters

        Returns:
            FFmpeg filter_complex string
        """
        filters = []
        num_segments = len(segments)

        # For each input segment, apply effects
        for i in range(num_segments):
            segment_filters = []

            # Speed effects
            if effects_config.speed_effects.enabled:
                speed_filter = EffectsEngine.generate_speed_filter(
                    effects_config.speed_effects.mode,
                    effects_config.speed_effects.slow_motion_factor
                    if effects_config.speed_effects.mode == SpeedMode.SLOW_MOTION
                    else effects_config.speed_effects.speed_up_factor
                )
                if speed_filter:
                    segment_filters.append(speed_filter)

            # Color grading
            if effects_config.color.enabled:
                color_filter = EffectsEngine.generate_color_filter(
                    effects_config.color.style,
                    effects_config.color.brightness,
                    effects_config.color.contrast,
                    effects_config.color.saturation,
                    effects_config.color.temperature
                )
                if color_filter:
                    segment_filters.append(color_filter)

            # Apply segment filters
            if segment_filters:
                filter_str = ",".join(segment_filters)
                filters.append(f"[{i}:v]{filter_str}[v{i}]")
            else:
                # No filters, just label
                filters.append(f"[{i}:v]copy[v{i}]")

        # Transitions (if more than one segment)
        if num_segments > 1 and effects_config.transitions.enabled:
            transition_type = effects_config.transitions.type
            duration = effects_config.transitions.duration

            if transition_type != TransitionType.CUT and duration > 0:
                # Build xfade chain
                xfade_type = EffectsEngine.generate_transition_filter(
                    transition_type, duration, num_segments
                )

                if xfade_type:
                    # Chain transitions between segments
                    # This is simplified - real implementation needs segment durations
                    # For MVP, we'll just concatenate
                    pass

        # Concatenation (simple for MVP)
        video_inputs = "".join([f"[v{i}]" for i in range(num_segments)])
        filters.append(f"{video_inputs}concat=n={num_segments}:v=1:a=0[outv]")

        return ";".join(filters)

    @staticmethod
    def apply_effects_to_segment(
        input_path: str,
        output_path: str,
        effects_config: EffectsConfiguration,
        segment_start: float = None,
        segment_duration: float = None
    ) -> List[str]:
        """
        Generate FFmpeg command to apply effects to a single segment

        Args:
            input_path: Input video file
            output_path: Output video file
            effects_config: Effects configuration
            segment_start: Start time (optional)
            segment_duration: Duration (optional)

        Returns:
            List of FFmpeg command arguments
        """
        cmd = ["ffmpeg", "-y"]

        # Input with optional trimming
        if segment_start is not None:
            cmd.extend(["-ss", str(segment_start)])

        cmd.extend(["-i", input_path])

        if segment_duration is not None:
            cmd.extend(["-t", str(segment_duration)])

        # Build filter chain
        filters = []

        # Speed
        if effects_config.speed_effects.enabled:
            speed_filter = EffectsEngine.generate_speed_filter(
                effects_config.speed_effects.mode,
                effects_config.speed_effects.slow_motion_factor
                if effects_config.speed_effects.mode == SpeedMode.SLOW_MOTION
                else effects_config.speed_effects.speed_up_factor
            )
            if speed_filter:
                filters.append(speed_filter)

        # Color
        if effects_config.color.enabled:
            color_filter = EffectsEngine.generate_color_filter(
                effects_config.color.style,
                effects_config.color.brightness,
                effects_config.color.contrast,
                effects_config.color.saturation,
                effects_config.color.temperature
            )
            if color_filter:
                filters.append(color_filter)

        # Apply filters if any
        if filters:
            filter_str = ",".join(filters)
            cmd.extend(["-vf", filter_str])

        # Output
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            output_path
        ])

        return cmd


if __name__ == "__main__":
    # Test effects generation
    from src.effects_config import TransitionSettings, SpeedEffectSettings, ColorSettings

    print("Testing Effects Engine...")

    # Test transition filter
    trans_filter = EffectsEngine.generate_transition_filter(
        TransitionType.CROSSFADE, 0.5, 3
    )
    print(f"Transition filter: {trans_filter}")

    # Test speed filter
    speed_filter = EffectsEngine.generate_speed_filter(
        SpeedMode.SLOW_MOTION, 0.75
    )
    print(f"Speed filter: {speed_filter}")

    # Test color filter
    color_filter = EffectsEngine.generate_color_filter(
        ColorStyle.WARM, brightness=0.05, saturation=0.1
    )
    print(f"Color filter: {color_filter}")
