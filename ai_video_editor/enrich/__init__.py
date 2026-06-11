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
from ai_video_editor.enrich.runner import enrich_transcript

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
    "enrichment_cache_path_for",
    "load_cached_enrichment",
    "save_enrichment",
]
