from __future__ import annotations

from loguru import logger
from pydantic import BaseModel, Field, field_validator

from ai_video_editor.duplicate.models import SimilarityScore
from ai_video_editor.llm import (
    LangChainModelConfig,
    build_chat_model,
    default_cutting_model_config,
)
from ai_video_editor.transcription.models import Sentence


def _clamp_unit_interval(value: float) -> float:
    return max(0.0, min(1.0, value))


DUPLICATE_PROMPT = """Jesi li ekspert za analizu govornog jezika na hrvatskom. Tvoj zadatak je odlučiti jesu li parovi rečenica iz video lekcije **ponavljanja** (govornik je rekao istu stvar dva puta, jednom pogrešno pa zatim ispravno).

ODGOVOR: Vrati isključivo validan json koji odgovara zadanoj structured-output shemi. Ne koristi Markdown, code blockove ni dodatni tekst.

PRAVILA:
- "Duplikat" znači da je govornik ponovio istu misao — NE da su rečenice slične po temi
- Ako govornik objašnjava istu temu ali dodaje nove informacije, to NISU duplikati
- Ako je jedna rečenica nastavak prethodne misli, to NIJE duplikat
- Kratki frazni obrasci poput pozdrava ili uvodnih fraza ("Dobro, idemo dalje") JESU duplikati samo ako se ponavljaju uzastopno

KORISTI KONTEKST I VRIJEME:
- Uz svaki par dani su SUSJEDNE rečenice (prije/poslije) i VREMENSKI RAZMAK između dvije verzije.
- Mali razmak (par sekundi) + lažni početak između = ponovljeni pokušaj (snimanje) → vjerojatno DUPLIKAT.
- Velik razmak (mnogo rečenica / dugo vrijeme) = govornik se vraća na temu radi PODSJETNIKA → NIJE duplikat, ZADRŽI obje.

Za svaki par navedi:
- is_duplicate: true/false
- confidence: 0.0-1.0 (koliko si siguran)
- reasoning: kratko objašnjenje na hrvatskom
- preferred_index: AKO je duplikat, navedi indeks rečenice koju treba ZADRŽATI. Pravilo odabira:
  1. Zadano zadrži KASNIJU verziju (veći indeks) — govornik ponavlja upravo zato da ispravi ili poboljša raniju izvedbu
  2. Odaberi RANIJU verziju SAMO ako je kasnija OČITO lošija: prekinuta, nedovršena, s više poštapalica ili s manje sadržaja

Parovi rečenica za analizu:
{pairs_text}"""

FALSE_START_PROMPT = """Analiziraj sljedeći blok rečenica iz video lekcije na hrvatskom. Ove rečenice se nalaze IZMEĐU dva ponavljanja — govornik je rekao istu stvar prije i poslije ovog bloka.

ODGOVOR: Vrati isključivo validan json koji odgovara zadanoj structured-output shemi. Ne koristi Markdown, code blockove ni dodatni tekst.

Tvoj zadatak: odluči koje od ovih rečenica su **lažni počeci, nedovršene misli ili filler** koji se mogu izbaciti, a koje su **stvarni sadržaj** koji treba zadržati.

PRAVILA:
- "Lažni početak" = govornik je počeo rečenicu pa odustao i krenuo ispočetka
- "Filler" = poštapalice bez sadržaja ("znači", "evo", "dakle" same za sebe)
- Ako rečenica nosi novu informaciju ili objašnjenje, to NIJE filler — ZADRŽI je
- Budi konzervativan: ako nisi siguran, označi kao "zadrži"

Rečenice (s indeksima):
{block_text}

Kontekst — rečenica PRIJE bloka:
{before}

Kontekst — rečenica NAKON bloka:
{after}"""


class DuplicateVerdict(BaseModel):
    """Gemini's judgment on a single sentence pair."""
    pair_id: int = Field(..., description="Zero-based index into the input pairs list")
    is_duplicate: bool
    confidence: float
    reasoning: str
    preferred_index: int | None = Field(
        default=None,
        description="Index of the sentence to KEEP (the better version). Only set when is_duplicate=true.",
    )

    @field_validator("confidence", mode="after")
    @classmethod
    def _clamp_confidence(cls, value: float) -> float:
        return _clamp_unit_interval(value)


class DuplicateVerdicts(BaseModel):
    """Container for batch duplicate verdicts."""
    verdicts: list[DuplicateVerdict] = Field(default_factory=list)


class FalseStartVerdict(BaseModel):
    """Gemini's judgment on which sentences in a block are filler/false starts."""
    filler_indices: list[int] = Field(
        default_factory=list,
        description="Indices of sentences that are filler/false starts (relative to the block)",
    )
    reasoning: str = ""


def _get_llm(llm_config: LangChainModelConfig | None = None):
    return build_chat_model(llm_config or default_cutting_model_config())


def _context_lines(
    sentences: list[Sentence],
    center_a: int,
    center_b: int,
    context_window: int,
) -> str:
    """Render the sentences surrounding a candidate pair, marking the pair members."""
    if context_window <= 0:
        return ""
    lo = max(0, min(center_a, center_b) - context_window)
    hi = min(len(sentences), max(center_a, center_b) + context_window + 1)
    out: list[str] = []
    for j in range(lo, hi):
        mark = ""
        if j == center_a:
            mark = " <<< A"
        elif j == center_b:
            mark = " <<< B"
        out.append(f'    [{j}] "{sentences[j].text}"{mark}')
    return "\n".join(out)


def verify_duplicates_with_gemini(
    pairs: list[SimilarityScore],
    sentences: list[Sentence],
    *,
    context_window: int = 2,
    llm_config: LangChainModelConfig | None = None,
) -> list[DuplicateVerdict]:
    """
    Ask Gemini whether borderline sentence pairs are real duplicates.

    *pairs* contains ``(idx_a, idx_b)`` references into *sentences*.
    Each pair is shown with its neighbouring sentences and the time gap between
    the two members so the model can separate a retake from a recap.
    Returns one ``DuplicateVerdict`` per input pair.
    """
    if not pairs:
        return []

    # Keep prompts small enough for Gemini to reliably answer at scale. The
    # expanded fixture set can produce 100+ borderline pairs for a single long
    # lecture; one giant structured-output request regularly hits 504 deadlines.
    max_pairs_per_call = 40
    if len(pairs) > max_pairs_per_call:
        logger.info(
            "Gemini duplicate verification: batching {} pairs into chunks of {}",
            len(pairs),
            max_pairs_per_call,
        )
        verdicts: list[DuplicateVerdict] = []
        for start in range(0, len(pairs), max_pairs_per_call):
            chunk = pairs[start : start + max_pairs_per_call]
            chunk_verdicts = verify_duplicates_with_gemini(
                chunk,
                sentences,
                context_window=context_window,
                llm_config=llm_config,
            )
            for verdict in chunk_verdicts:
                verdict.pair_id += start
            verdicts.extend(chunk_verdicts)
        return verdicts

    lines: list[str] = []
    for k, p in enumerate(pairs):
        a, b = sentences[p.idx_a], sentences[p.idx_b]
        gap = abs(b.start - a.end) if b.start >= a.end else abs(a.start - b.end)
        block = f"Par {k} (vremenski razmak ≈ {gap:.1f}s):\n"
        block += f'  A (rečenica {p.idx_a}): "{a.text}"\n'
        block += f'  B (rečenica {p.idx_b}): "{b.text}"'
        ctx = _context_lines(sentences, p.idx_a, p.idx_b, context_window)
        if ctx:
            block += f"\n  Kontekst:\n{ctx}"
        lines.append(block)

    prompt = DUPLICATE_PROMPT.format(pairs_text="\n\n".join(lines))

    llm = _get_llm(llm_config)
    structured = llm.with_structured_output(DuplicateVerdicts)

    logger.info("Gemini duplicate verification: {} pairs", len(pairs))
    result: DuplicateVerdicts = structured.invoke(prompt)

    logger.info(
        "Gemini returned {} verdicts ({} duplicates)",
        len(result.verdicts),
        sum(1 for v in result.verdicts if v.is_duplicate),
    )
    return result.verdicts


WHICH_TO_KEEP_PROMPT = """Ti si ekspert za analizu govornog jezika na hrvatskom. Ove rečenice su potvrđeni duplikati — govornik je rekao istu stvar dva puta. Odaberi BOLJU verziju za zadržati.

ODGOVOR: Vrati isključivo validan json koji odgovara zadanoj structured-output shemi. Ne koristi Markdown, code blockove ni dodatni tekst.

Kriteriji (ovim redoslijedom):
1. Potpunija misao (više informativnog sadržaja, cjelovitije objašnjenje) — u edukacijskim lekcijama dulja, potpunija verzija je obično vrjednija
2. Čišća izvedba (manje poštapalica, oklijevanja, nedovršenih riječi)
3. Ako su jednake kvalitete, preferiraj KASNIJU verziju (govornik obično ispravlja/poboljšava)

Parovi:
{pairs_text}"""

WHICH_TO_KEEP_PROMPT_CLEAN = """Ti si ekspert za analizu govornog jezika na hrvatskom. Ove rečenice su potvrđeni duplikati — govornik je rekao istu stvar dva puta. Odaberi BOLJU verziju za zadržati.

ODGOVOR: Vrati isključivo validan json koji odgovara zadanoj structured-output shemi. Ne koristi Markdown, code blockove ni dodatni tekst.

Kriteriji (ovim redoslijedom):
1. Čišća izvedba (manje poštapalica, oklijevanja, nedovršenih riječi)
2. Potpunija misao (više informativnog sadržaja)
3. Ako su jednake kvalitete, preferiraj KASNIJU verziju (govornik obično ispravlja/poboljšava)

Parovi:
{pairs_text}"""


class KeepDecision(BaseModel):
    """Gemini's pick for which sentence to keep in a confirmed duplicate pair."""
    pair_id: int = Field(..., description="Zero-based index into the input pairs list")
    keep_index: int = Field(..., description="Sentence index of the version to KEEP")
    reasoning: str = ""


class KeepDecisions(BaseModel):
    """Batch of keep/cut decisions."""
    decisions: list[KeepDecision] = Field(default_factory=list)


def pick_best_version_with_gemini(
    pairs: list[DuplicatePair],
    sentences: list[Sentence],
    *,
    prefer_completeness: bool = True,
    llm_config: LangChainModelConfig | None = None,
) -> dict[int, int]:
    """
    For each confirmed duplicate pair, ask Gemini which sentence is the
    better version to keep.

    Returns a dict mapping ``idx_cut`` → ``preferred_keep_index``.  If
    Gemini's preference differs from the current ``idx_keep``, the caller
    should swap them.
    """
    if not pairs:
        return {}

    lines: list[str] = []
    for k, p in enumerate(pairs):
        a_text = sentences[p.idx_keep].text if p.idx_keep < len(sentences) else "?"
        b_text = sentences[p.idx_cut].text if p.idx_cut < len(sentences) else "?"
        lines.append(
            f"Par {k}:\n"
            f"  Rečenica {p.idx_keep}: \"{a_text}\"\n"
            f"  Rečenica {p.idx_cut}: \"{b_text}\""
        )

    template = WHICH_TO_KEEP_PROMPT if prefer_completeness else WHICH_TO_KEEP_PROMPT_CLEAN
    prompt = template.format(pairs_text="\n\n".join(lines))

    llm = _get_llm(llm_config)
    structured = llm.with_structured_output(KeepDecisions)

    logger.info("Gemini 'which to keep' decision: {} pairs", len(pairs))
    result: KeepDecisions = structured.invoke(prompt)

    mapping: dict[int, int] = {}
    swaps = 0
    for d in result.decisions:
        if d.pair_id >= len(pairs):
            continue
        pair = pairs[d.pair_id]
        valid_indices = {pair.idx_keep, pair.idx_cut}
        if d.keep_index in valid_indices:
            mapping[pair.idx_cut] = d.keep_index
            if d.keep_index != pair.idx_keep:
                swaps += 1
                logger.info(
                    "Gemini swapped keep/cut: pair {} — keep sentence {} instead of {} ({})",
                    d.pair_id, d.keep_index, pair.idx_keep, d.reasoning[:60],
                )

    logger.info("Gemini keep decisions: {}/{} swapped from original", swaps, len(pairs))
    return mapping


def detect_false_starts_with_gemini(
    block_sentences: list[Sentence],
    before_sentence: Sentence | None,
    after_sentence: Sentence | None,
    *,
    llm_config: LangChainModelConfig | None = None,
) -> FalseStartVerdict:
    """
    Given a block of sentences between a confirmed duplicate pair, ask Gemini
    which ones are filler or false starts that can be removed.
    """
    if not block_sentences:
        return FalseStartVerdict(filler_indices=[], reasoning="Empty block")

    block_lines = "\n".join(
        f"  [{i}] \"{s.text}\"" for i, s in enumerate(block_sentences)
    )
    before = f"\"{before_sentence.text}\"" if before_sentence else "(početak transkripta)"
    after = f"\"{after_sentence.text}\"" if after_sentence else "(kraj transkripta)"

    prompt = FALSE_START_PROMPT.format(
        block_text=block_lines,
        before=before,
        after=after,
    )

    llm = _get_llm(llm_config)
    structured = llm.with_structured_output(FalseStartVerdict)

    logger.info("Gemini false-start detection: {} sentences in block", len(block_sentences))
    result: FalseStartVerdict = structured.invoke(prompt)

    logger.info(
        "Gemini flagged {} false starts out of {} block sentences",
        len(result.filler_indices),
        len(block_sentences),
    )
    return result


STUTTER_PROMPT = """Analiziraj sljedeću rečenicu iz video lekcije na hrvatskom. Rečenica sadrži ponovljene riječi/fraze koje ukazuju na mucanje ili lažni početak.

ODGOVOR: Vrati isključivo validan json koji odgovara zadanoj structured-output shemi. Ne koristi Markdown, code blockove ni dodatni tekst.

Tvoj zadatak: prepoznaj koje RIJEČI su dio mucanja (ponovljeni/nedovršeni dio) i koje treba IZBACITI, a koje su dio čistog izlaganja i treba ih ZADRŽATI.

PRAVILA:
- Govornik obično počne frazu, zastane ili pogriješi, pa kaže istu stvar čišće — IZBACI prvi (pogrešni) pokušaj
- Ako govornik koristi ponavljanje namjerno za naglašavanje — ZADRŽI sve
- Budi konzervativan: ako nisi siguran, ZADRŽI sve (is_stutter=false)
- word_indices_to_cut su indeksi (0-based) riječi koje treba izbaciti

Riječi s indeksima:
{words_indexed}

Kontekst — rečenica PRIJE:
{before}

Kontekst — rečenica NAKON:
{after}"""


class StutterVerdict(BaseModel):
    """Gemini's judgment on stuttering with word-level precision."""
    is_stutter: bool = Field(..., description="True if the sentence contains actual stuttering (not intentional repetition)")
    word_indices_to_cut: list[int] = Field(
        default_factory=list,
        description="0-based indices of words to remove (the stuttered/repeated portion)",
    )
    confidence: float
    reasoning: str = ""

    @field_validator("confidence", mode="after")
    @classmethod
    def _clamp_confidence(cls, value: float) -> float:
        return _clamp_unit_interval(value)


def verify_stutters_with_gemini(
    sentences: list[Sentence],
    stutter_indices: list[int],
    *,
    llm_config: LangChainModelConfig | None = None,
) -> list[tuple[int, StutterVerdict]]:
    """
    Send each stuttered sentence to Gemini for word-level trim guidance.

    Returns a list of (sentence_index, verdict) tuples.
    """
    if not stutter_indices:
        return []

    llm = _get_llm(llm_config)
    structured = llm.with_structured_output(StutterVerdict)
    results: list[tuple[int, StutterVerdict]] = []

    for idx in stutter_indices:
        sentence = sentences[idx]
        before = f'"{sentences[idx - 1].text}"' if idx > 0 else "(početak transkripta)"
        after = f'"{sentences[idx + 1].text}"' if idx < len(sentences) - 1 else "(kraj transkripta)"

        words_indexed = "\n".join(
            f"  [{i}] \"{w.text}\"" for i, w in enumerate(sentence.words)
        )

        prompt = STUTTER_PROMPT.format(
            words_indexed=words_indexed,
            before=before,
            after=after,
        )

        logger.info("Gemini stutter check: sentence {} (\"{}...\")", idx, sentence.text[:50])
        verdict: StutterVerdict = structured.invoke(prompt)
        results.append((idx, verdict))

        logger.info(
            "Gemini verdict: {} cut_words={} (confidence={:.0%}, reason={})",
            "STUTTER" if verdict.is_stutter else "KEEP",
            verdict.word_indices_to_cut,
            verdict.confidence,
            verdict.reasoning[:80],
        )

    stutter_count = sum(1 for _, v in results if v.is_stutter)
    logger.info("Gemini stutter verification: {}/{} confirmed as stutters", stutter_count, len(stutter_indices))
    return results


HOLISTIC_PROMPT = """Ti si profesionalni video editor za edukacijske video lekcije na hrvatskom jeziku. Pregledaj sljedeći transkript i označi rečenice koje su **nepotrebne** i mogu se izbaciti bez gubitka sadržaja.

ODGOVOR: Vrati isključivo validan json koji odgovara zadanoj structured-output shemi. Ne koristi Markdown, code blockove ni dodatni tekst.

PRAVILA:
- "Nepotrebna" znači da rečenica NE dodaje nikakvu novu informaciju koju kontekst već ne pokriva
- Kratke nedovršene rečenice poput "Evo, ja." ili "A ovaj..." su kandidati AKO ih slijedi potpunija verzija
- Trailing filler poput "Evo, znači, to znači da..." JEST nepotreban AKO sljedeća rečenica kaže istu stvar jasnije
- Ponovljena pitanja su nepotrebna AKO se isto pitanje pojavljuje negdje drugdje u tekstu
- NE brisi rečenice koje objašnjavaju, naglašavaju ili donose bilo kakvu novu informaciju
- Budi VRLO konzervativan — bolje je ostaviti nepotrebnu rečenicu nego izbaciti korisnu
- Za svaku označenu rečenicu navedi confidence (0.0-1.0) i kratko obrazloženje

Transkript (s indeksima originalnih rečenica):
{transcript_indexed}"""


class RedundancyFlag(BaseModel):
    """A single sentence flagged as redundant by Gemini."""
    sentence_index: int = Field(..., description="Original sentence index from the transcript")
    confidence: float
    reasoning: str = ""

    @field_validator("confidence", mode="after")
    @classmethod
    def _clamp_confidence(cls, value: float) -> float:
        return _clamp_unit_interval(value)


class RedundancyReview(BaseModel):
    """Gemini's holistic review of the transcript."""
    redundant_sentences: list[RedundancyFlag] = Field(default_factory=list)


def holistic_redundancy_review(
    kept_sentences: list[tuple[int, Sentence]],
    *,
    llm_config: LangChainModelConfig | None = None,
) -> list[RedundancyFlag]:
    """
    Send the full kept transcript to Gemini for a holistic redundancy review.

    Args:
        kept_sentences: List of (original_index, Sentence) for sentences that will be kept.

    Returns:
        List of RedundancyFlag for sentences Gemini considers redundant.
    """
    if not kept_sentences:
        return []

    transcript_indexed = "\n".join(
        f"  [{idx}] \"{sent.text}\"" for idx, sent in kept_sentences
    )

    prompt = HOLISTIC_PROMPT.format(transcript_indexed=transcript_indexed)

    llm = _get_llm(llm_config)
    structured = llm.with_structured_output(RedundancyReview)

    logger.info("Holistic redundancy review: {} sentences", len(kept_sentences))
    result: RedundancyReview = structured.invoke(prompt)

    valid_indices = {idx for idx, _ in kept_sentences}
    flags = [f for f in result.redundant_sentences if f.sentence_index in valid_indices]

    for f in flags:
        logger.info(
            "Gemini redundancy flag: sentence {} (confidence={:.0%}, reason={})",
            f.sentence_index, f.confidence, f.reasoning[:80],
        )

    logger.info(
        "Holistic review: {}/{} flagged as redundant",
        len(flags), len(kept_sentences),
    )
    return flags


FRAGMENT_PROMPT = """Ti si profesionalni video editor. Pregledaj sljedeće kandidate za nepotpune fragmente u kontekstu okolnih rečenica.

ODGOVOR: Vrati isključivo validan json koji odgovara zadanoj structured-output shemi. Ne koristi Markdown, code blockove ni dodatni tekst.

Za SVAKI kandidat odgovori:
- should_cut: true AKO je fragment nepotpun/nedovršen i potpunija verzija postoji u okolnim rečenicama
- should_cut: false AKO fragment zapravo služi svrsi (naglasak, prijelaz, uvod)
- confidence: 0.0-1.0
- reasoning: kratko obrazloženje

VAŽNO: Rečenice koje završavaju s "..." ili "…" su JAKI signal da je govornik prekinuo misao i započeo ispočetka. Takve rečenice gotovo uvijek treba izbaciti jer slijedi potpunija verzija iste misli.

Kandidati:
{candidates_text}"""


class FragmentVerdict(BaseModel):
    """Gemini's judgment on a single fragment candidate."""
    sentence_index: int
    should_cut: bool = False
    confidence: float = 0.5
    reasoning: str = ""

    @field_validator("confidence", mode="after")
    @classmethod
    def _clamp_confidence(cls, value: float) -> float:
        return _clamp_unit_interval(value)


class FragmentReview(BaseModel):
    """Gemini's review of all fragment candidates."""
    verdicts: list[FragmentVerdict] = Field(default_factory=list)


def verify_fragments_with_gemini(
    candidate_indices: list[int],
    sentences: list[Sentence],
    context_window: int = 3,
    *,
    llm_config: LangChainModelConfig | None = None,
) -> list[FragmentVerdict]:
    """
    Send fragment candidates with surrounding context to Gemini for confirmation.
    """
    if not candidate_indices:
        return []

    parts: list[str] = []
    for idx in candidate_indices:
        lo = max(0, idx - context_window)
        hi = min(len(sentences), idx + context_window + 1)
        context_lines = []
        for j in range(lo, hi):
            marker = " <<< KANDIDAT" if j == idx else ""
            context_lines.append(f'  [{j}] "{sentences[j].text}"{marker}')
        parts.append("\n".join(context_lines))

    candidates_text = "\n\n---\n\n".join(parts)
    prompt = FRAGMENT_PROMPT.format(candidates_text=candidates_text)

    llm = _get_llm(llm_config)
    structured = llm.with_structured_output(FragmentReview)

    logger.info("Fragment verification: {} candidates", len(candidate_indices))
    result: FragmentReview = structured.invoke(prompt)

    valid = {idx for idx in candidate_indices}
    verdicts = [v for v in result.verdicts if v.sentence_index in valid]

    for v in verdicts:
        action = "CUT" if v.should_cut else "KEEP"
        logger.info(
            "Fragment verdict: sentence {} → {} (confidence={:.0%}, reason={})",
            v.sentence_index, action, v.confidence, v.reasoning[:80],
        )

    return verdicts
