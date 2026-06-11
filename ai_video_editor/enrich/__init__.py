"""Transcript metadata enrichment (clean, standalone LLM pass)."""

from ai_video_editor.enrich.cache import (
    enrichment_cache_path_for,
    load_cached_enrichment,
    save_enrichment,
)
from ai_video_editor.enrich.models import (
    DEFAULT_GREEN_THRESHOLD,
    DEFAULT_RESTORE_THRESHOLD,
    SCHEMA_VERSION,
    EnrichmentResult,
    EnrichmentStatus,
    EnrichmentTag,
    SentenceEnrichment,
    derive_status,
    reconcile_word_salience,
)
from ai_video_editor.enrich.arbiter import apply_enrichment_arbiter
from ai_video_editor.enrich.runner import enrich_transcript, restatus_against_edl

__all__ = [
    "DEFAULT_GREEN_THRESHOLD",
    "DEFAULT_RESTORE_THRESHOLD",
    "SCHEMA_VERSION",
    "EnrichmentResult",
    "EnrichmentStatus",
    "EnrichmentTag",
    "SentenceEnrichment",
    "derive_status",
    "reconcile_word_salience",
    "enrich_transcript",
    "apply_enrichment_arbiter",
    "restatus_against_edl",
    "enrichment_cache_path_for",
    "load_cached_enrichment",
    "save_enrichment",
]
