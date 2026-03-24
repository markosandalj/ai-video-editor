from __future__ import annotations

from pathlib import Path

from loguru import logger

from ai_video_editor.duplicate.edl import EditAction, EditDecisionList
from ai_video_editor.transcription.models import Sentence, Transcript, Word


def _apply_edl_to_transcript(
    transcript: Transcript,
    edl: EditDecisionList,
) -> Transcript:
    """
    Build a new Transcript containing only the sentences that fall inside
    keep regions, with timestamps recalculated to be continuous (as if the
    cut sections were physically removed from the video).
    """
    keep_regions = [d for d in edl.decisions if d.action == EditAction.KEEP]
    if not keep_regions:
        return transcript.model_copy(update={"sentences": []})

    cumulative = 0.0
    region_shifts: list[tuple[float, float, float]] = []
    for region in keep_regions:
        shift = region.start - cumulative
        region_shifts.append((region.start, region.end, shift))
        cumulative += region.end - region.start

    edited: list[Sentence] = []
    for r_start, r_end, shift in region_shifts:
        for s in transcript.sentences:
            if s.start >= r_start and s.end <= r_end:
                new_words = [
                    Word(
                        text=w.text,
                        start=round(w.start - shift, 4),
                        end=round(w.end - shift, 4),
                    )
                    for w in s.words
                ]
                edited.append(Sentence(
                    words=new_words,
                    text=s.text,
                    start=round(s.start - shift, 4),
                    end=round(s.end - shift, 4),
                ))

    return transcript.model_copy(update={"sentences": edited})


def save_debug_files(
    video_path: Path,
    transcript: Transcript,
    edl: EditDecisionList,
) -> dict[str, Path]:
    """
    Write three debug files alongside the video:

    1. ``<stem>.transcript.txt``  — full transcript as a plain-text block
    2. ``<stem>_edited.transcript.json`` — transcript after EDL cuts, timestamps recalculated
    3. ``<stem>_edited.transcript.txt``  — plain-text block of the edited transcript

    Returns a dict mapping short names to their paths.
    """
    stem = video_path.stem
    parent = video_path.parent

    full_txt_path = parent / f"{stem}.transcript.txt"
    full_text = " ".join(s.text for s in transcript.sentences)
    full_txt_path.write_text(full_text, encoding="utf-8")

    edited_transcript = _apply_edl_to_transcript(transcript, edl)

    edited_json_path = parent / f"{stem}_edited.transcript.json"
    edited_json_path.write_text(
        edited_transcript.model_dump_json(indent=2),
        encoding="utf-8",
    )

    edited_txt_path = parent / f"{stem}_edited.transcript.txt"
    edited_text = " ".join(s.text for s in edited_transcript.sentences)
    edited_txt_path.write_text(edited_text, encoding="utf-8")

    logger.info(
        "Debug files saved: {} sentences full, {} sentences after EDL cuts",
        len(transcript.sentences),
        len(edited_transcript.sentences),
    )

    return {
        "transcript_txt": full_txt_path,
        "edited_json": edited_json_path,
        "edited_txt": edited_txt_path,
    }
