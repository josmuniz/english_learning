"""Generación de escenas con IA. Módulo aislado para mockearlo en tests.

Proveedores (por prioridad de env):
  1. Qwen / DashScope-intl  — DASHSCOPE_API_KEY  (modelo z-image-turbo)
  2. Gemini                 — GEMINI_API_KEY     (gemini-3.1-flash-image-preview)
"""
import os
import base64
from urllib.parse import urlparse

import httpx

GEMINI_MODEL = "gemini-3.1-flash-image-preview"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

QWEN_MODEL = "qwen-image-2.0"
QWEN_URL = ("https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/"
            "multimodal-generation/generation")


def api_key() -> str:
    """Key del proveedor configurado (Qwen/DashScope tiene prioridad)."""
    return os.environ.get("DASHSCOPE_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")


def build_prompt(word: dict) -> str:
    # OJO: nunca citar frases entre comillas ni incluir el ejemplo — el modelo
    # las escribe dentro de la imagen (y regalaría la respuesta del quiz).
    meaning = word.get("definition_en", "") or word.get("word_es", "")
    that_is = f", that is: {meaning}" if meaning else ""
    return (
        "Wordless flat cartoon illustration. STRICT RULE: zero text, zero "
        "letters, zero numbers, zero captions anywhere in the image (no text). "
        "Draw only the situation, never write it. Scene to draw: a person "
        f"acting out the meaning of the English expression {word['word_en']}"
        f"{that_is}. Express it only through body language, facial expression, "
        "actions and objects. Simple shapes, friendly colors, one clear scene."
    )


async def generate_scene(word: dict) -> bytes:
    """Genera la escena y devuelve los bytes de imagen. RuntimeError si falla.

    Prioridad Qwen; si Qwen falla y Gemini está configurado, hace fallback."""
    has_qwen = bool(os.environ.get("DASHSCOPE_API_KEY"))
    has_gemini = bool(os.environ.get("GEMINI_API_KEY"))
    if not has_qwen and not has_gemini:
        raise RuntimeError("Sin API key de imágenes (DASHSCOPE_API_KEY o GEMINI_API_KEY)")
    if has_qwen:
        try:
            return await _generate_qwen(word)
        except Exception:
            if not has_gemini:
                raise
    return await _generate_gemini(word)


async def _generate_qwen(word: dict) -> bytes:
    key = os.environ["DASHSCOPE_API_KEY"]
    body = {
        "model": QWEN_MODEL,
        "input": {"messages": [
            {"role": "user", "content": [{"text": build_prompt(word)}]},
        ]},
        "parameters": {"size": "1024*768"},
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(QWEN_URL, json=body,
                              headers={"Authorization": f"Bearer {key}"})
        if r.status_code != 200:
            raise RuntimeError(f"Qwen HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        choices = (data.get("output") or {}).get("choices") or [{}]
        contents = (choices[0].get("message") or {}).get("content") or []
        url = next((c["image"] for c in contents
                    if isinstance(c, dict) and c.get("image")), "")
        if not url:
            raise RuntimeError("Respuesta de Qwen sin imagen")
        # la URL viene firmada desde el storage de Alibaba; no seguir otros hosts
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or not host.endswith(".aliyuncs.com"):
            raise RuntimeError("URL de imagen inesperada")
        img = await client.get(url)
        if img.status_code != 200:
            raise RuntimeError(f"Descarga de imagen falló: HTTP {img.status_code}")
        return img.content


async def _generate_gemini(word: dict) -> bytes:
    key = os.environ["GEMINI_API_KEY"]
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
