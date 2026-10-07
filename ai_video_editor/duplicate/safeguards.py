"""Conservative conflict resolution for cuts with a retained replacement."""
from __future__ import annotations

from collections.abc import Sequence
from ai_video_editor.duplicate.models import DuplicateFlag, KeptSpan, RejectedCut, WordTrim
from ai_video_editor.transcription.models import Sentence


def protect_kept_spans(
    flags: list[DuplicateFlag],
    sentences: list[Sentence],
    *,
    protected: Sequence[KeptSpan] = (),
    rejected: list[RejectedCut] | None = None,
) -> list[DuplicateFlag]:
    # Resolve simultaneously, independent of flag ordering. For A -> B -> C,
    # keep B as well as C rather than silently redirect A to a different take.
    anchors = [*protected, *(span for flag in flags for span in flag.kept_spans)]
    accepted = []
    for flag in flags:
        sentence = sentences[flag.idx]
        cuts = flag.word_trims or [WordTrim(start=sentence.start, end=sentence.end)]
        conflict = next((
            span for span in anchors
            if any(cut.start < span.end and cut.end > span.start for cut in cuts)
        ), None)
        if conflict is not None:
            if rejected is not None:
                rejected.append(RejectedCut(
                    flag=flag,
                    reason=f"Would delete retained replacement in sentence [{conflict.sentence_index}]: {conflict.text}",
                ))
        else:
            accepted.append(flag)
    return accepted
