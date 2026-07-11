from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np

from ai_video_editor.audio.disruption import detect_disruptions
from ai_video_editor.audio.models import DisruptionRegion
from ai_video_editor.config.settings import DisruptionConfig, FalseStartAudioConfig
from ai_video_editor.duplicate.false_start_audio import detect_audio_false_starts
from ai_video_editor.duplicate.models import FlagReason
from ai_video_editor.transcription.models import AudioEvent, Sentence, Transcript, Word


def _phrase(text: str, start: float, end: float) -> Sentence:
    toks = text.split()
    step = (end - start) / max(len(toks), 1)
    words = [
        Word(text=t, start=start + i * step, end=start + (i + 1) * step)
        for i, t in enumerate(toks)
    ]
    return Sentence(text=text, start=start, end=end, words=words)


def _write_wav(path: Path, samples: np.ndarray, sr: int = 16000) -> None:
    pcm = np.clip(samples, -1, 1)
    pcm16 = (pcm * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm16.tobytes())


def _ffmpeg_available() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


def test_detect_disruptions_finds_loud_burst_in_pause(tmp_path: Path) -> None:
    if not _ffmpeg_available():
        import pytest

        pytest.skip("ffmpeg not available")

    sr = 16000
    duration_s = 6
    rng = np.random.default_rng(0)
    # Quiet noise floor everywhere.
    x = rng.normal(0, 0.0008, sr * duration_s).astype(np.float32)
    # A loud 0.3s burst at t=3.0s (the "cough"), sitting in a pause.
    burst = slice(int(3.0 * sr), int(3.3 * sr))
    x[burst] += rng.normal(0, 0.3, x[burst].shape[0]).astype(np.float32)

    wav = tmp_path / "clip.wav"
    _write_wav(wav, x, sr)

    # No words near the burst -> it is in a pause, so it must be detected.
    sentences = [_phrase("prije", 0.5, 1.5), _phrase("poslije", 4.5, 5.5)]
    regions = detect_disruptions(wav, sentences, DisruptionConfig())

    assert any(2.8 <= r.start <= 3.4 for r in regions), regions
    assert all(r.source == "acoustic" for r in regions)


def test_disruption_inside_speech_is_ignored(tmp_path: Path) -> None:
    if not _ffmpeg_available():
        import pytest

        pytest.skip("ffmpeg not available")

    sr = 16000
    rng = np.random.default_rng(1)
    x = rng.normal(0, 0.0008, sr * 6).astype(np.float32)
    loud = slice(int(3.0 * sr), int(3.3 * sr))
    x[loud] += rng.normal(0, 0.3, x[loud].shape[0]).astype(np.float32)
    wav = tmp_path / "clip.wav"
    _write_wav(wav, x, sr)

    # A word covers the loud region -> it is speech, not a disruption.
    sentences = [_phrase("rijec", 2.9, 3.4)]
    regions = detect_disruptions(wav, sentences, DisruptionConfig())
    assert not any(2.8 <= r.start <= 3.4 for r in regions), regions


def test_audio_false_start_fires_on_stranded_phrase_after_disruption() -> None:
    sentences = [
        _phrase("Dakle to mi je taj argument.", 0.0, 5.0),
        _phrase("I dobro.", 11.0, 12.0),  # 6s pause before, short
        _phrase("Pa dobro ovako mi znamo.", 12.5, 16.0),  # resumes 0.5s later
    ]
    disruptions = [DisruptionRegion(start=8.0, end=8.5, peak_db=-32.0, floor_db=-72.0)]

    flags = detect_audio_false_starts(sentences, disruptions, set(), FalseStartAudioConfig())
    assert [f.idx for f in flags] == [1]
    assert flags[0].reason == FlagReason.FALSE_START


def test_audio_false_start_respects_guards() -> None:
    cfg = FalseStartAudioConfig()
    base = [
        _phrase("Prva recenica ovdje.", 0.0, 5.0),
        _phrase("I dobro.", 11.0, 12.0),
        _phrase("Treca recenica.", 12.5, 16.0),
    ]

    # No disruption in the pause -> nothing fires (require_disruption=True).
    assert detect_audio_false_starts(base, [], set(), cfg) == []

    # Short pause before -> not a flubbed restart.
    short_gap = [
        _phrase("Prva.", 0.0, 10.0),
        _phrase("I dobro.", 10.5, 11.5),
        _phrase("Treca.", 12.0, 14.0),
    ]
    disr = [DisruptionRegion(start=10.1, end=10.3, peak_db=-30.0, floor_db=-72.0)]
    assert detect_audio_false_starts(short_gap, disr, set(), cfg) == []

    # Too many words -> likely real content, not a stranded filler.
    long_phrase = [
        _phrase("Prva recenica.", 0.0, 5.0),
        _phrase("Ovo je puna recenica sadrzaja.", 11.0, 13.0),
        _phrase("Treca.", 13.5, 15.0),
    ]
    disr2 = [DisruptionRegion(start=8.0, end=8.5, peak_db=-30.0, floor_db=-72.0)]
    assert detect_audio_false_starts(long_phrase, disr2, set(), cfg) == []


def test_audio_false_start_skips_already_flagged() -> None:
    sentences = [
        _phrase("Prva recenica.", 0.0, 5.0),
        _phrase("I dobro.", 11.0, 12.0),
        _phrase("Treca recenica.", 12.5, 16.0),
    ]
    disr = [DisruptionRegion(start=8.0, end=8.5, peak_db=-30.0, floor_db=-72.0)]
    assert detect_audio_false_starts(sentences, disr, {1}, FalseStartAudioConfig()) == []


def test_stt_event_counts_as_disruption() -> None:
    # Even with no acoustic burst, an STT-tagged event in the pause is a cue.
    sentences = [
        _phrase("Prva recenica.", 0.0, 5.0),
        _phrase("I dobro.", 11.0, 12.0),
        _phrase("Treca recenica.", 12.5, 16.0),
    ]
    event_disr = [
        DisruptionRegion(start=8.0, end=8.6, peak_db=0.0, floor_db=0.0,
                         source="stt_event", label="(cough)")
    ]
    flags = detect_audio_false_starts(sentences, event_disr, set(), FalseStartAudioConfig())
    assert [f.idx for f in flags] == [1]
    assert "(cough)" in flags[0].note


def test_detect_all_flags_upgrades_existing_text_flag_with_audio_evidence(monkeypatch) -> None:
    from ai_video_editor import decisions
    from ai_video_editor.config.settings import Settings
    from ai_video_editor.duplicate.models import DuplicateFlag, FlagReason

    sentences = [
        _phrase("Prva recenica.", 0.0, 5.0),
        _phrase("I dobro.", 11.0, 12.0),
        _phrase("Treca recenica.", 12.5, 16.0),
    ]
    transcript = Transcript(
        sentences=sentences,
        source_video="lesson.mp4",
        language="hr",
        model_size="test",
    )
    disr = [DisruptionRegion(start=8.0, end=8.5, peak_db=-30.0, floor_db=-72.0)]

    monkeypatch.setattr(
        decisions,
        "detect_duplicates",
        lambda _sentences, _cfg, **_kwargs: [
            DuplicateFlag(
                idx=1,
                reason=FlagReason.DUPLICATE,
                confidence=0.8,
                note="ordinary text-derived duplicate",
            )
        ],
    )
    monkeypatch.setattr(decisions, "detect_asides", lambda *_args, **_kwargs: [])

    flags = decisions.detect_all_flags(transcript, [], disr, Settings())

    assert len(flags) == 1
    assert flags[0].idx == 1
    assert flags[0].reason == FlagReason.FALSE_START
    assert flags[0].note.startswith("Audio false start:")
    assert "Text flag:" in flags[0].note


def test_stt_parser_captures_audio_events_separately() -> None:
    from ai_video_editor.transcription.elevenlabs_stt import _parse_stt_tokens

    raw = [
        {"type": "word", "text": "Zdravo", "start": 0.0, "end": 0.5},
        {"type": "spacing", "text": " ", "start": 0.5, "end": 0.6},
        {"type": "audio_event", "text": "(cough)", "start": 0.6, "end": 1.2},
        {"type": "word", "text": "svima", "start": 1.2, "end": 1.7},
    ]
    words, events = _parse_stt_tokens(raw)
    assert [w.text for w in words] == ["Zdravo", "svima"]
    assert [e.text for e in events] == ["(cough)"]
    assert events[0].start == 0.6 and events[0].end == 1.2


def test_transcript_events_roundtrip_and_default_empty() -> None:
    # Backward compatibility: a transcript JSON without "events" still loads.
    legacy = '{"sentences": [], "source_video": "v.mp4", "language": "hr", "model_size": "x"}'
    t = Transcript.model_validate_json(legacy)
    assert t.events == []

    t2 = Transcript(
        sentences=[],
        source_video="v.mp4",
        language="hr",
        model_size="x",
        events=[AudioEvent(text="(cough)", start=1.0, end=1.5)],
    )
    reloaded = Transcript.model_validate_json(t2.model_dump_json())
    assert reloaded.events[0].text == "(cough)"
