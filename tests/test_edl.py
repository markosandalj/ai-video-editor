from __future__ import annotations

import pytest

from ai_video_editor.audio.models import KeepRegion
from ai_video_editor.duplicate.edl import EditAction, EditDecisionList, EditReason, build_edl
from ai_video_editor.duplicate.models import DuplicateFlag, FlagReason, WordTrim
from ai_video_editor.transcription.models import Sentence, Transcript, Word


def _make_transcript(sentences: list[Sentence]) -> Transcript:
    return Transcript(
        sentences=sentences,
        source_video="test.mp4",
        language="hr",
        model_size="test",
    )


class TestEditDecisionList:
    def test_no_flags_keeps_everything(self, simple_duplicate_pair):
        transcript = _make_transcript(simple_duplicate_pair)
        keep_regions = [KeepRegion(start=0.0, end=5.0)]
        edl = build_edl(transcript, keep_regions, [])

        keep_decisions = [d for d in edl.decisions if d.action == EditAction.KEEP]
        assert len(keep_decisions) >= 1
        assert edl.keep_duration > 0

    def test_flagged_sentence_excluded(self, simple_duplicate_pair):
        transcript = _make_transcript(simple_duplicate_pair)
        keep_regions = [KeepRegion(start=0.0, end=5.0)]
        flags = [DuplicateFlag(idx=0, reason=FlagReason.DUPLICATE)]

        edl = build_edl(transcript, keep_regions, flags)
        keep_decisions = [d for d in edl.decisions if d.action == EditAction.KEEP]

        for decision in keep_decisions:
            assert not (decision.start <= 0.0 and decision.end >= 2.0), (
                "Flagged sentence [0] (0.0-2.0) should not be in a keep segment"
            )

    def test_partial_trim_preserves_source_metadata(self):
        sentence = Sentence(
            text="Firstly youngsters s Firstly youngsters spend more time",
            start=0.0,
            end=4.0,
            words=[
                Word(text=text, start=i * 0.5, end=(i + 1) * 0.5)
                for i, text in enumerate(
                    "Firstly youngsters s Firstly youngsters spend more time".split()
                )
            ],
        )
        transcript = _make_transcript([sentence])
        flag = DuplicateFlag(
            idx=0,
            reason=FlagReason.STUTTER,
            confidence=0.73,
            note="Ponavljanje na početku rečenice",
            word_trims=[WordTrim(start=0.0, end=1.5)],
        )

        edl = build_edl(
            transcript,
            [KeepRegion(start=0.0, end=4.0)],
            [flag],
        )

        cut = next(d for d in edl.decisions if d.action == EditAction.CUT)
        assert (cut.start, cut.end) == pytest.approx((0.0, 1.5))
        assert cut.reason == EditReason.FALSE_START
        assert cut.confidence == pytest.approx(0.73)
        assert cut.note == "Ponavljanje na početku rečenice"

    def test_mixed_gap_separates_flagged_speech_from_real_silence(self):
        sentences = [
            Sentence(
                text=text,
                start=start,
                end=end,
                words=[Word(text=text, start=start, end=end)],
            )
            for text, start, end in [
                ("Prva", 0.0, 1.0),
                ("Pogrešna", 2.0, 3.0),
                ("Zadnja", 4.0, 5.0),
            ]
        ]
        transcript = _make_transcript(sentences)
        flag = DuplicateFlag(
            idx=1,
            reason=FlagReason.DUPLICATE,
            confidence=0.81,
            note="Ponovljena misao",
        )

        edl = build_edl(
            transcript,
            [KeepRegion(start=0.0, end=5.0)],
            [flag],
        )

        cuts = [d for d in edl.decisions if d.action == EditAction.CUT]
        assert [
            (d.start, d.end, d.reason, d.confidence, d.note) for d in cuts
        ] == [
            (1.0, 2.0, EditReason.SILENCE, 1.0, ""),
            (2.0, 3.0, EditReason.DUPLICATE, 0.81, "Ponovljena misao"),
            (3.0, 4.0, EditReason.SILENCE, 1.0, ""),
        ]

    def test_serializable_to_json(self, simple_duplicate_pair):
        transcript = _make_transcript(simple_duplicate_pair)
        edl = build_edl(transcript, [], [])
        json_str = edl.model_dump_json()
        restored = EditDecisionList.model_validate_json(json_str)
        assert len(restored.decisions) == len(edl.decisions)

    def test_empty_transcript(self):
        transcript = _make_transcript([])
        edl = build_edl(transcript, [], [])
        assert len(edl.decisions) == 0

    def test_chronological_order(self, croatian_transcript_with_duplicates):
        transcript = _make_transcript(croatian_transcript_with_duplicates)
        keep_regions = [KeepRegion(start=0.0, end=53.0)]
        edl = build_edl(transcript, keep_regions, [])
        starts = [d.start for d in edl.decisions]
        assert starts == sorted(starts)

    def test_non_overlapping(self, croatian_transcript_with_duplicates):
        transcript = _make_transcript(croatian_transcript_with_duplicates)
        keep_regions = [KeepRegion(start=0.0, end=53.0)]
        edl = build_edl(transcript, keep_regions, [])
        for current, following in zip(edl.decisions, edl.decisions[1:]):
            assert current.end <= following.start + 0.01
