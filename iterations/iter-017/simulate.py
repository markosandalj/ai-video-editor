"""iter-017 offline simulation: audio-driven false-start rule.

For every fixture, compute acoustic disruptions, apply the audio false-start
rule to the currently-KEPT sentences, and score each newly-flagged sentence
against the human ground truth (same monotonic alignment the decision-eval uses):

  recovered (TP)  = pipeline kept, human cut, rule now cuts  -> good
  false positive  = human kept,             rule now cuts    -> bad

Disruptions are cached to /tmp so rule-threshold sweeps don't re-decode audio.
Run:  uv run python iterations/iter-017/simulate.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ai_video_editor.audio.disruption import detect_disruptions
from ai_video_editor.audio.models import DisruptionRegion
from ai_video_editor.config.settings import DisruptionConfig, FalseStartAudioConfig
from ai_video_editor.duplicate.false_start_audio import detect_audio_false_starts
from ai_video_editor.duplicate.edl import EditDecisionList
from ai_video_editor.qa.decision_eval import MATCH_THRESHOLD, _cut_reason
from ai_video_editor.qa.ground_truth import _align_monotonic
from ai_video_editor.transcription.models import Transcript

FIX = Path("tests/fixtures")
CACHE = Path("/tmp/iter017_disr")
CACHE.mkdir(exist_ok=True)


def names() -> list[str]:
    return sorted(p.name[: -len("-raw.transcript.json")] for p in FIX.glob("*-raw.transcript.json"))


def disruptions_for(name: str, raw: Transcript, dcfg: DisruptionConfig) -> list[DisruptionRegion]:
    key = f"{name}__f{dcfg.frame_ms}_h{dcfg.hop_ms}_p{dcfg.noise_floor_pct}_t{dcfg.threshold_db}"
    cache_file = CACHE / f"{key}.json"
    if cache_file.exists():
        return [DisruptionRegion(**d) for d in json.loads(cache_file.read_text())]
    video = FIX / f"{name}-raw.mp4"
    if not video.exists():
        return []
    disr = detect_disruptions(video, raw.sentences, dcfg)
    cache_file.write_text(json.dumps([d.model_dump() for d in disr]))
    return disr


def run(dcfg: DisruptionConfig, fcfg: FalseStartAudioConfig, *, verbose: bool = False) -> dict:
    tp = fp = 0
    hits: list[tuple[str, int, str, bool]] = []
    for name in names():
        raw_t = FIX / f"{name}-raw.transcript.json"
        edl_p = FIX / f"{name}-raw.edl.json"
        gt_t = FIX / f"{name}-edited.qa-transcript.json"
        if not (raw_t.exists() and edl_p.exists() and gt_t.exists()):
            continue
        raw = Transcript.model_validate_json(raw_t.read_text())
        edl = EditDecisionList.model_validate_json(edl_p.read_text())
        gt = Transcript.model_validate_json(gt_t.read_text())

        human_kept = {pi for pi, _, _ in _align_monotonic(raw.sentences, gt.sentences, MATCH_THRESHOLD)}
        currently_cut = {i for i, s in enumerate(raw.sentences) if _cut_reason(s, edl)[0]}

        disr = disruptions_for(name, raw, dcfg)
        flags = detect_audio_false_starts(raw.sentences, disr, currently_cut, fcfg)
        for f in flags:
            recovered = f.idx not in human_kept
            tp += int(recovered)
            fp += int(not recovered)
            hits.append((name, f.idx, raw.sentences[f.idx].text, recovered))

    if verbose:
        for name, idx, text, recovered in hits:
            tag = "RECOVER" if recovered else "FALSE+ "
            print(f"  {tag} {name:<28} [{idx}] {text!r}")
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    return {"tp": tp, "fp": fp, "precision": prec, "hits": hits}


if __name__ == "__main__":
    dcfg = DisruptionConfig()
    print("=== DEFAULT config (gap>=4.0, after<=2.5, words<=4, require_disruption=True, thr=18dB) ===")
    res = run(dcfg, FalseStartAudioConfig(), verbose=True)
    print(f"\nRecovered (TP)={res['tp']}  False+ (FP)={res['fp']}  precision={res['precision']:.3f}")

    if "--sweep" in sys.argv:
        print("\n=== SWEEP ===")
        print(f"{'gap>=':>6} {'after<=':>7} {'words<=':>7} {'reqDisr':>7} {'thr':>4} {'TP':>4} {'FP':>4} {'prec':>6}")
        for thr in (15.0, 18.0, 22.0):
            d = DisruptionConfig(threshold_db=thr)
            for gap in (3.0, 4.0, 5.0):
                for after in (2.0, 2.5, 3.5):
                    for mw in (3, 4):
                        for req in (True, False):
                            f = FalseStartAudioConfig(
                                min_gap_before_s=gap, max_gap_after_s=after,
                                max_words=mw, require_disruption=req,
                            )
                            r = run(d, f)
                            print(f"{gap:>6} {after:>7} {mw:>7} {str(req):>7} {thr:>4} "
                                  f"{r['tp']:>4} {r['fp']:>4} {r['precision']:>6.3f}")
