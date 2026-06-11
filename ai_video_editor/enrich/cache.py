from __future__ import annotations

from pathlib import Path

from loguru import logger

from ai_video_editor.enrich.models import EnrichmentResult


def enrichment_cache_path_for(video_path: Path) -> Path:
    return video_path.with_suffix(".enrichment.json")


def load_cached_enrichment(video_path: Path) -> EnrichmentResult | None:
    path = enrichment_cache_path_for(video_path)
    if not path.exists():
        return None
    logger.info("Loading cached enrichment: {}", path.name)
    return EnrichmentResult.model_validate_json(path.read_text(encoding="utf-8"))


def save_enrichment(video_path: Path, result: EnrichmentResult) -> Path:
    path = enrichment_cache_path_for(video_path)
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Saved enrichment cache: {}", path.name)
    return path
