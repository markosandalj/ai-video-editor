"""
Run the full pipeline on test-2-raw.mp4:
  1. Audio extraction + noise reduction
  2. ElevenLabs transcription + grammar correction
  3. Silence detection + keep regions
  4. Duplicate detection (lexical → semantic → Gemini)
  5. EDL generation

Prints detailed results and saves EDL JSON alongside the video.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent.parent
VIDEO = ROOT / "tests" / "fixtures" / "test-2-raw.mp4"

logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level:<7} | {message}")


def main() -> None:
    from ai_video_editor.audio import compute_keep_regions, detect_silences, extract_audio, reduce_noise
    from ai_video_editor.config import Settings
    from ai_video_editor.duplicate.edl import build_edl
    from ai_video_editor.duplicate.pipeline import detect_duplicates
    from ai_video_editor.transcription.cache import load_cached_transcript, save_transcript
    from ai_video_editor.transcription.pipeline import transcribe_with_elevenlabs_and_grammar

    settings = Settings()

    if not VIDEO.is_file():
        logger.error("Video not found: {}", VIDEO)
        sys.exit(1)

    logger.info("=== STEP 1: Audio extraction & noise reduction ===")
    meta = extract_audio(VIDEO, settings)
    denoised = reduce_noise(meta, settings)

    logger.info("=== STEP 2: Silence detection & keep regions ===")
    silences = detect_silences(denoised, settings)
    keeps = compute_keep_regions(silences, denoised.duration_s, settings)
    logger.info("{} silence regions, {} keep regions", len(silences), len(keeps))

    logger.info("=== STEP 3: Transcription (ElevenLabs + grammar) ===")
    cached = load_cached_transcript(VIDEO)
    if cached is not None:
        transcript = cached
        logger.info("Using cached transcript ({} sentences)", len(transcript.sentences))
    else:
        transcript = transcribe_with_elevenlabs_and_grammar(denoised, VIDEO, settings)
        save_transcript(VIDEO, transcript)

    logger.info("Transcript: {} sentences, {} words", len(transcript.sentences), transcript.word_count)
    for i, s in enumerate(transcript.sentences):
        logger.info("  [{}] {:.1f}s-{:.1f}s: {}", i, s.start, s.end, s.text[:80])

    logger.info("=== STEP 4: Duplicate detection ===")
    flags = detect_duplicates(transcript.sentences, settings.duplicate_detection)

    if flags:
        logger.info("Flagged {} sentences for removal:", len(flags))
        for f in flags:
            s = transcript.sentences[f.idx]
            tier = f.related_pair.tier if f.related_pair else "n/a"
            logger.info(
                "  [{}] {} (tier={}, conf={:.2f}): {}",
                f.idx, f.reason.value, tier, f.confidence, s.text[:60],
            )
    else:
        logger.info("No duplicates detected.")

    logger.info("=== STEP 5: EDL generation ===")
    edl = build_edl(transcript, keeps, flags)

    logger.info("EDL summary:")
    logger.info("  Total duration: {:.1f}s", edl.total_duration)
    logger.info("  Keep duration:  {:.1f}s", edl.keep_duration)
    logger.info("  Cut duration:   {:.1f}s", edl.cut_duration)
    logger.info("  Decisions:      {}", len(edl.decisions))

    for d in edl.decisions:
        logger.info(
            "  {:>6.1f}s - {:>6.1f}s  {:4}  {}",
            d.start, d.end, d.action.value, d.reason.value,
        )

    edl_path = VIDEO.with_suffix(".edl.json")
    edl_path.write_text(edl.model_dump_json(indent=2), encoding="utf-8")
    logger.info("EDL saved: {}", edl_path)

    transcript_path = VIDEO.with_suffix(".transcript.json")
    logger.info("Transcript saved: {}", transcript_path)

    logger.info("=== STEP 6: Debug files ===")
    from ai_video_editor.duplicate.debug import save_debug_files
    debug_paths = save_debug_files(VIDEO, transcript, edl)
    for name, path in debug_paths.items():
        logger.info("  {}: {}", name, path.name)

    logger.info("=== DONE ===")


if __name__ == "__main__":
    main()
