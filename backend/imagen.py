"""Generación de escenas con Gemini. Módulo aislado para mockearlo en tests."""
import os
import base64
import httpx

GEMINI_MODEL = "gemini-3.1-flash-image-preview"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)


def api_key() -> str:
    return os.environ.get("GEMINI_API_KEY", "")


def build_prompt(word: dict) -> str:
    ctx = word.get("example_en", "")
    ctx_line = f' Context: "{ctx}".' if ctx else ""
    return (
        "A simple, clean, flat illustration that clearly depicts the meaning of "
        f'the English expression "{word["word_en"]}" (Spanish: "{word.get("word_es", "")}").'
        f"{ctx_line} Friendly colors, single clear scene, easy to understand at a "
        "glance. IMPORTANT: no text, no letters, no words anywhere in the image."
    )


async def generate_scene(word: dict) -> bytes:
    """Genera la escena y devuelve los bytes PNG. Lanza RuntimeError si falla."""
    key = api_key()
    if not key:
        raise RuntimeError("GEMINI_API_KEY no configurada")
    body = {
        "contents": [{"parts": [{"text": build_prompt(word)}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"aspectRatio": "4:3", "imageSize": "1K"},
        },
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(GEMINI_URL, json=body,
                              headers={"x-goog-api-key": key})
        if r.status_code != 200:
            raise RuntimeError(f"Gemini HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
    candidates = data.get("candidates", [])
    if not candidates:
        reason = data.get("promptFeedback", {}).get("blockReason", "sin candidatos")
        raise RuntimeError(f"Gemini no devolvió imagen: {reason}")
    content = candidates[0].get("content") or {}
    parts = content.get("parts", []) if isinstance(content, dict) else []
    for part in parts:
        if "inlineData" in part and isinstance(part.get("inlineData"), dict):
            if "data" in part["inlineData"]:
                return base64.b64decode(part["inlineData"]["data"])
    raise RuntimeError("Respuesta de Gemini sin inlineData")
