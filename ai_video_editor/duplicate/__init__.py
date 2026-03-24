from ai_video_editor.duplicate.models import DuplicateFlag, DuplicatePair, SimilarityScore
from ai_video_editor.duplicate.lexical import compute_lexical_similarity
from ai_video_editor.duplicate.semantic import compute_semantic_similarity
from ai_video_editor.duplicate.windowed import windowed_pairs
from ai_video_editor.duplicate.gemini_verify import (
    verify_duplicates_with_gemini,
    detect_false_starts_with_gemini,
)
from ai_video_editor.duplicate.pipeline import detect_duplicates
from ai_video_editor.duplicate.edl import EditDecision, EditDecisionList, build_edl
from ai_video_editor.duplicate.debug import save_debug_files

__all__ = [
    "DuplicateFlag",
    "DuplicatePair",
    "SimilarityScore",
    "compute_lexical_similarity",
    "compute_semantic_similarity",
    "windowed_pairs",
    "verify_duplicates_with_gemini",
    "detect_false_starts_with_gemini",
    "detect_duplicates",
    "EditDecision",
    "EditDecisionList",
    "build_edl",
    "save_debug_files",
]
