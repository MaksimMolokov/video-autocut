"""Анализ речи: границы фрагментов не режут фразы."""
from core.speech_analyzer import adjust_for_speech

# Сцена 0..30, фразы:
PHRASES = [
    (2.0, 5.0, "Привет, это наш отель"),
    (10.0, 14.0, "Посмотрите на этот вид"),
    (20.0, 29.0, "Очень длинный монолог о жизни у океана и погоде"),
]


def test_no_speech_no_change():
    assert adjust_for_speech(6.0, 9.0, PHRASES, 0, 30, 6.0) == (6.0, 9.0)


def test_start_extends_to_phrase_begin():
    """Начало режет фразу близко к её началу → захватываем фразу целиком."""
    start, end = adjust_for_speech(3.0, 8.0, PHRASES, 0, 30, 6.0)
    assert start == 2.0                     # от начала «Привет…»
    assert end == 8.0


def test_start_moves_after_long_phrase():
    """Начало глубоко внутри длинной фразы → начинаем после неё."""
    start, end = adjust_for_speech(25.0, 30.0, PHRASES, 0, 30, 6.0)
    assert start >= 29.0                    # после конца монолога


def test_end_extends_to_phrase_end():
    """Конец режет фразу, добор в пределах max_len → договариваем."""
    start, end = adjust_for_speech(8.0, 12.0, PHRASES, 0, 30, 6.0)
    assert end == 14.0                      # до конца «Посмотрите…»
    assert start == 8.0


def test_end_shrinks_when_phrase_too_long():
    """Фразу не вместить в max_len → заканчиваем до её начала."""
    start, end = adjust_for_speech(16.0, 22.0, PHRASES, 0, 30, 6.0)
    assert end == 20.0                      # перед монологом


def test_never_returns_tiny_fragment():
    """Правки съели фрагмент → возвращается исходный, а не 0.2с."""
    phrases = [(0.0, 9.8, "сплошная речь")]
    start, end = adjust_for_speech(4.0, 9.0, phrases, 0, 10, 5.0)
    assert end - start >= 1.0


def test_transcribe_unavailable_returns_none(monkeypatch):
    from core import speech_analyzer
    monkeypatch.setattr(speech_analyzer, "available", lambda: False)
    assert speech_analyzer.transcribe_video("/x.mp4") is None
