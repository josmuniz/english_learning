import json
import uuid
import re
import asyncio
import httpx
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from backend import quiz as quiz_engine
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="English Learning API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DICT_API      = "https://api.dictionaryapi.dev/api/v2/entries/en"
TRANS_API     = "https://api.mymemory.translated.net/get"
DATAMUSE_API  = "https://api.datamuse.com/words"
DATA_FILE     = Path(__file__).parent.parent / "data" / "words.json"


# ── IPA → Spanish phonetic approximation ─────────────────────────────────────
# Maps common IPA symbols to Spanish-readable equivalents
_IPA_MAP = [
    # Digraphs first (order matters)
    ("ɜː",  "er"),  ("ɪə",  "ia"),  ("ʊə",  "ua"),  ("eɪ",  "ei"),
    ("aɪ",  "ai"),  ("ɔɪ",  "oi"),  ("aʊ",  "au"),  ("əʊ",  "ou"),
    ("iː",  "i"),   ("uː",  "u"),   ("ɑː",  "a"),   ("ɔː",  "o"),
    ("tʃ",  "ch"),  ("dʒ",  "y"),
    # Single vowels
    ("æ",   "a"),   ("ə",   "e"),   ("ɪ",   "i"),   ("ʊ",   "u"),
    ("ʌ",   "a"),   ("ɛ",   "e"),   ("ɐ",   "a"),   ("ɑ",   "a"),   ("ɒ",   "o"),
    # Single consonants
    ("ð",   "d"),   ("θ",   "z"),   ("ʃ",   "sh"),  ("ʒ",   "y"),
    ("ŋ",   "ng"),  ("ɹ",   "r"),   ("ɾ",   "r"),   ("j",   "y"),
    ("w",   "w"),   ("h",   "j"),   ("ɡ",   "g"),   ("ʔ",   ""),
    # Stress / length markers
    ("ˈ",   "-"),   ("ˌ",   ""),    ("ː",   ""),
]

def ipa_to_spanish(ipa: str) -> str:
    s = ipa.strip("/[]")
    for src, tgt in _IPA_MAP:
        s = s.replace(src, tgt)
    s = re.sub(r"[^\w\-]", "", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s.lower() or ipa


# ── Storage ───────────────────────────────────────────────────────────────────

def load_words() -> list:
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return []


def save_words(words: list):
    DATA_FILE.write_text(json.dumps(words, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Models ────────────────────────────────────────────────────────────────────

class WordRequest(BaseModel):
    word: str
    lang: str = "en"   # "en" | "es"

class WordUpdateRequest(BaseModel):
    word_es: str | None = None
    quiz_enabled: bool | None = None
    pronunciation_es: str | None = None
    ipa: str | None = None
    synonym_en: str | None = None
    synonym_es: str | None = None
    antonym_en: str | None = None
    antonym_es: str | None = None
    example_en: str | None = None
    example_es: str | None = None

class ValidateRequest(BaseModel):
    word_en: str
    sentence: str

class QuizAnswerRequest(BaseModel):
    word_id: str
    type: str        # mc_word | mc_phrase | cloze | typing
    direction: str   # es_to_en | en_to_es
    answer: str


# ── Helpers ───────────────────────────────────────────────────────────────────

MAX_EXAMPLE_WORDS = 10

def pick_example(candidates: list[str]) -> str:
    """Primer ejemplo con ≤10 palabras; si ninguno cumple, recorta el primero."""
    candidates = [c.strip() for c in candidates if c and c.strip()]
    if not candidates:
        return ""
    for c in candidates:
        if len(c.split()) <= MAX_EXAMPLE_WORDS:
            return c
    return " ".join(candidates[0].split()[:MAX_EXAMPLE_WORDS]) + "…"


async def fetch_dictionary(word: str, client: httpx.AsyncClient) -> dict:
    r = await client.get(f"{DICT_API}/{word}", timeout=10)
    if r.status_code != 200:
        raise HTTPException(404, f'No se encontró "{word}" en el diccionario')
    entries = r.json()
    entry = entries[0]

    # Collect all meanings across entries
    all_meanings = []
    for e in entries:
        all_meanings.extend(e.get("meanings", []))

    # Pick first meaning with a definition
    meaning = next((m for m in all_meanings if m.get("definitions")), all_meanings[0] if all_meanings else {})
    defn = meaning.get("definitions", [{}])[0]

    # Find an example sentence — prefer the first one with ≤10 words
    candidates = []
    if defn.get("example"):
        candidates.append(defn["example"])
    for m in all_meanings:
        for d in m.get("definitions", []):
            if d.get("example"):
                candidates.append(d["example"])
    example_en = pick_example(candidates)
    # Fallback example using the word itself
    if not example_en:
        part = meaning.get("partOfSpeech", "word")
        if part == "noun":
            example_en = f"The {entry['word']} was remarkable."
        elif part == "verb":
            example_en = f"She decided to {entry['word']} every day."
        elif part == "adjective":
            example_en = f"It was a very {entry['word']} experience."
        else:
            example_en = f"Learning about {entry['word']} is important."

    # synonyms/antonyms fetched separately via Datamuse — leave empty here
    synonyms: list[str] = []
    antonyms: list[str] = []

    # IPA phonetic
    ipa = entry.get("phonetic", "")
    if not ipa:
        for ph in entry.get("phonetics", []):
            if ph.get("text"):
                ipa = ph["text"]
                break

    return {
        "word_en":      entry["word"].lower(),
        "type":         meaning.get("partOfSpeech", "word"),
        "ipa":          ipa,
        "definition_en": defn.get("definition", "")[:120],
        "example_en":   example_en,
        "synonym_raw":  "",   # filled by Datamuse in add_word
        "antonym_raw":  "",   # filled by Datamuse in add_word
    }


async def datamuse_word(word: str, rel: str, client: httpx.AsyncClient) -> str:
    """Fetch best synonym (rel_syn) or antonym (rel_ant) from Datamuse.
    Takes the highest-scored single word of 3-10 chars from top-10 results."""
    try:
        r = await client.get(DATAMUSE_API, params={"rel_" + rel: word, "max": 10}, timeout=8)
        results = r.json()
        if not results:
            return ""
        candidates = [
            w["word"] for w in results
            if " " not in w["word"] and 3 <= len(w["word"]) <= 10
        ]
        return candidates[0] if candidates else ""
    except Exception:
        return ""


async def translate(text: str, client: httpx.AsyncClient, src="en", tgt="es") -> str:
    if not text:
        return ""
    try:
        r = await client.get(TRANS_API, params={"q": text, "langpair": f"{src}|{tgt}"}, timeout=8)
        data = r.json()
        translated = data["responseData"]["translatedText"]
        # MyMemory sometimes returns the original if it can't translate
        return translated if translated.lower() != text.lower() else ""
    except Exception:
        return ""


# ── Helpers for add_word ─────────────────────────────────────────────────────

def _is_duplicate(entry: str, words: list) -> bool:
    return any(entry == w.get("word_en", "").lower()
               or entry == w.get("word_es", "").lower()
               for w in words)


# ── Phrase helper ─────────────────────────────────────────────────────────────

async def _add_phrase(word_en: str, word_es: str | None, words: list) -> dict:
    """Camino frase. word_es None → traducir EN→ES con fallback a la frase."""
    if word_es is None:
        async with httpx.AsyncClient() as client:
            word_es = await translate(word_en, client)

    data = {
        "id":           str(uuid.uuid4()),
        "created_at":   datetime.now().isoformat(),
        "word_en":      word_en,
        "word_es":      word_es or word_en,
        "type":         "phrase",
        "ipa":          "",
        "pronunciation_es": "",
        "synonym_en":   "", "synonym_es": "",
        "antonym_en":   "", "antonym_es": "",
        "definition_en": "", "definition_es": "",
        "example_en":   "", "example_es": "",
        "times_practiced": 0,
        "times_correct":   0,
    }
    words.append(data)
    save_words(words)
    return data


# ── English pipeline ─────────────────────────────────────────────────────────

async def _build_english_entry(word_en: str, words: list,
                               word_es_override: str | None = None) -> dict:
    """Pipeline inglés completo (dictionary + datamuse + traducciones)."""
    async with httpx.AsyncClient() as client:
        # 1. Dictionary lookup
        d = await fetch_dictionary(word_en, client)

        # 2. Synonyms/antonyms from Datamuse + translations in parallel
        (
            word_es, definition_es, example_es,
            synonym_en, antonym_en,
        ) = await asyncio.gather(
            translate(d["word_en"], client),
            translate(d["definition_en"], client),
            translate(d["example_en"], client),
            datamuse_word(d["word_en"], "syn", client),
            datamuse_word(d["word_en"], "ant", client),
        )

        # 3. Translate synonym and antonym to Spanish
        synonym_es, antonym_es = await asyncio.gather(
            translate(synonym_en, client),
            translate(antonym_en, client),
        )

        # 3. Build pronunciation strings
        pronunciation_es = ipa_to_spanish(d["ipa"]) if d["ipa"] else ""

        # For example sentence, build word-by-word phonetic hint (first 6 words)
        example_pron = ""
        if d["example_en"]:
            ex_words = d["example_en"].split()[:8]
            # Simple heuristic: just show the IPA if we have it for the main word,
            # and note "pronunciación similar al español" for the phrase
            example_pron = f'"{d["example_en"][:60]}…"' if len(d["example_en"]) > 60 else ""

    data = {
        "id":           str(uuid.uuid4()),
        "created_at":   datetime.now().isoformat(),
        "word_en":      d["word_en"],
        "word_es":      word_es_override or word_es or word_en,
        "type":         d["type"],
        "ipa":          d["ipa"],
        "pronunciation_es": pronunciation_es,
        "synonym_en":   synonym_en,
        "synonym_es":   synonym_es,
        "antonym_en":   antonym_en,
        "antonym_es":   antonym_es,
        "definition_en": d["definition_en"],
        "definition_es": definition_es,
        "example_en":   d["example_en"],
        "example_es":   example_es,
        "times_practiced": 0,
        "times_correct":   0,
    }

    words.append(data)
    save_words(words)
    return data


# ── Spanish pipeline ───────────────────────────────────────────────────────────

async def _add_from_spanish(entry_es: str, words: list) -> dict:
    """Entrada en español: traducir a inglés y decidir camino por la forma del word_en."""
    async with httpx.AsyncClient() as client:
        translated = await translate(entry_es, client, src="es", tgt="en")
    word_en = translated.strip().lower()
    if not word_en:
        raise HTTPException(400, "No se pudo traducir; intenta escribirla en inglés")
    if any(word_en == w.get("word_en", "").lower() for w in words):
        raise HTTPException(409, "Esa palabra ya está en tu vocabulario")

    if " " in word_en:
        return await _add_phrase(word_en, entry_es, words)
    return await _build_english_entry(word_en, words, word_es_override=entry_es)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/api/words")
async def add_word(req: WordRequest):
    if req.lang not in ("en", "es"):
        raise HTTPException(422, "lang inválido (en|es)")
    word = req.word.strip().lower()
    if not word:
        raise HTTPException(400, "La palabra no puede estar vacía")
    if len(word) > 80:
        raise HTTPException(400, "Máximo 80 caracteres")

    words = load_words()
    if _is_duplicate(word, words):
        raise HTTPException(409, "Esa palabra ya está en tu vocabulario")

    if req.lang == "es":
        return await _add_from_spanish(word, words)

    if " " in word:
        return await _add_phrase(word, None, words)
    return await _build_english_entry(word, words)


@app.get("/api/words")
async def get_words():
    return load_words()


@app.delete("/api/words/{word_id}")
async def delete_word(word_id: str):
    words = load_words()
    new = [w for w in words if w["id"] != word_id]
    if len(new) == len(words):
        raise HTTPException(404, "Palabra no encontrada")
    save_words(new)
    return {"ok": True}


@app.patch("/api/words/{word_id}")
async def update_word(word_id: str, req: WordUpdateRequest):
    updates = {k: (v.strip() if isinstance(v, str) else v)
               for k, v in req.model_dump(exclude_none=True).items()}

    words = load_words()
    target = next((w for w in words if w["id"] == word_id), None)
    if target is None:
        raise HTTPException(404, "Palabra no encontrada")

    for field in ("example_en", "example_es"):
        if field in updates and len(updates[field].split()) > MAX_EXAMPLE_WORDS:
            raise HTTPException(422, "El ejemplo no puede superar 10 palabras")
    if "word_es" in updates:
        if not updates["word_es"]:
            raise HTTPException(422, "La traducción no puede estar vacía")
        dup = updates["word_es"].lower()
        if any(w["id"] != word_id and dup == w.get("word_es", "").lower() for w in words):
            raise HTTPException(409, "Esa traducción ya existe en tu vocabulario")

    target.update(updates)
    save_words(words)
    return target


@app.post("/api/validate")
async def validate_sentence(req: ValidateRequest):
    """
    Simple heuristic validation:
    - Word present in sentence: +40 pts
    - Sentence has subject + verb structure: +30 pts
    - Reasonable length (5-25 words): +20 pts
    - Starts with capital, ends with punctuation: +10 pts
    """
    s = req.sentence.strip()
    word = req.word_en.lower()
    score = 0
    issues = []

    uses_word = word in s.lower()
    if uses_word:
        score += 40
    else:
        issues.append(f'no contiene la palabra "{word}"')

    words_count = len(s.split())
    if 5 <= words_count <= 30:
        score += 20
    elif words_count < 5:
        issues.append("la oración es muy corta")
    else:
        issues.append("la oración es muy larga")

    if s and s[0].isupper():
        score += 5
    if s and s[-1] in ".!?":
        score += 5

    has_verb = any(s.lower().split().__contains__(v) for v in
                   ["is","are","was","were","have","has","had","do","does","did",
                    "will","would","can","could","should","may","might","must",
                    "seem","feel","look","go","make","take","get","know","think"])
    if has_verb:
        score += 30

    correct = score >= 60
    if correct:
        feedback = f'¡Bien hecho! Tu oración usa "{word}" correctamente.'
    else:
        feedback = f'Intenta mejorar: {", ".join(issues) if issues else "revisa la gramática"}.'

    return {
        "correct": correct,
        "score": min(score, 100),
        "feedback_es": feedback,
        "improved_en": None,
        "uses_word_correctly": uses_word,
    }


@app.get("/api/quiz/next")
async def quiz_next(types: str = "mc_word,mc_phrase,cloze,typing",
                    direction: str = "both"):
    requested = [t.strip() for t in types.split(",")
                 if t.strip() in quiz_engine.ALL_TYPES]
    if not requested:
        raise HTTPException(422, "types no contiene ningún tipo válido")
    if direction not in ("es_to_en", "en_to_es", "both"):
        raise HTTPException(422, "direction inválida")
    words = load_words()
    if not words:
        raise HTTPException(404, "El vocabulario está vacío")
    # Solo se preguntan las habilitadas; el vocabulario completo sigue sirviendo
    # de pool para distractores.
    pool = [w for w in words if w.get("quiz_enabled", True)]
    if not pool:
        raise HTTPException(404, "No hay palabras habilitadas para el quiz")
    word = quiz_engine.pick_word(pool)
    qtype = quiz_engine.choose_type(word, words, requested)
    return quiz_engine.build_question(word, qtype, direction, words)


@app.post("/api/quiz/answer")
async def quiz_answer(req: QuizAnswerRequest):
    if req.type not in quiz_engine.ALL_TYPES:
        raise HTTPException(422, "type inválido")
    if req.direction not in ("es_to_en", "en_to_es"):
        raise HTTPException(422, "direction inválida")
    words = load_words()
    word = next((w for w in words if w["id"] == req.word_id), None)
    if not word:
        raise HTTPException(404, "Palabra no encontrada")

    expected, synonym = quiz_engine.expected_answer(word, req.type, req.direction)
    is_correct = quiz_engine.is_match(req.answer, expected, synonym)

    for w in words:
        if w["id"] == req.word_id:
            w["times_practiced"] = w.get("times_practiced", 0) + 1
            if is_correct:
                w["times_correct"] = w.get("times_correct", 0) + 1
    save_words(words)

    return {"correct": is_correct, "correct_answer": expected, "word": word}


# ── Static frontend (must be last) ────────────────────────────────────────────
_frontend = Path(__file__).parent.parent / "frontend"
app.mount("/", StaticFiles(directory=str(_frontend), html=True), name="static")
