"""Diálogo nativo macOS para el quiz forzado. Solo stdlib.

Helpers puros (testeables sin GUI) + capa I/O (api/run_osascript) + main().
"""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

API_BASE = "http://localhost:8003"
LOCK_FILE = Path("/tmp/elearn-quiz.lock")
LOCK_STALE_S = 600
LOG_FILE = Path.home() / "Library" / "Logs" / "elearn-quiz.log"
TITLE = "English Learning"

PROMPT_LABEL = {
    ("mc_word", "es_to_en"): "¿Cómo se dice en inglés?",
    ("mc_word", "en_to_es"): "¿Qué significa en español?",
    ("mc_phrase", "es_to_en"): "¿Cuál es la frase en inglés?",
    ("mc_phrase", "en_to_es"): "¿Qué significa esta frase?",
    ("cloze", "es_to_en"): "Completa la frase:",
    ("typing", "es_to_en"): "Escribe la traducción en inglés:",
    ("typing", "en_to_es"): "Escribe la traducción en español:",
}


# ── Helpers puros ─────────────────────────────────────────────────────

def applescript_escape(s) -> str:
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def question_label(q) -> str:
    return PROMPT_LABEL.get((q["type"], q["direction"]), "Responde:")


def build_question_dialog(q) -> str:
    header = f"{question_label(q)}\n\n{q['prompt']}"
    if q.get("prompt_secondary"):
        header += f"  {q['prompt_secondary']}"
    header = applescript_escape(header)
    if q.get("options"):
        items = ", ".join(f'"{applescript_escape(o)}"' for o in q["options"])
        return (f'choose from list {{{items}}} with title "{TITLE}" '
                f'with prompt "{header}" OK button name "Responder" '
                f'cancel button name "Saltar"')
    return (f'display dialog "{header}" default answer "" '
            f'buttons {{"Saltar", "Responder"}} default button "Responder" '
            f'with title "{TITLE}"')


def build_result_dialog(res) -> str:
    if res["correct"]:
        text = f"✅ ¡Correcto!\n\n{res['correct_answer']}"
    else:
        text = f"❌ Incorrecto.\n\nEra: {res['correct_answer']}"
    return (f'display dialog "{applescript_escape(text)}" '
            f'buttons {{"+ Agregar", "OK"}} default button "OK" '
            f'with title "{TITLE}" giving up after 60')


def build_add_dialog() -> str:
    return ('display dialog "Nueva palabra o frase en inglés:" default answer "" '
            'buttons {"Cancelar", "Agregar"} default button "Agregar" '
            f'with title "{TITLE}" giving up after 120')


def build_info_dialog(text) -> str:
    return (f'display dialog "{applescript_escape(text)}" buttons {{"OK"}} '
            f'default button "OK" with title "{TITLE}" giving up after 30')


def parse_dialog_output(raw) -> dict:
    out = raw.strip()
    if not out or out == "false":
        return {"action": "skip"}
    if out.startswith("button returned:"):
        body = out[len("button returned:"):]
        gave_up = False
        if ", gave up:" in body:
            body, gave = body.rsplit(", gave up:", 1)
            gave_up = gave.strip() == "true"
        text = None
        if ", text returned:" in body:
            button, text = body.split(", text returned:", 1)
        else:
            button = body
        if gave_up or button in ("", "Saltar", "Cancelar"):
            return {"action": "skip"}
        return {"action": "button", "button": button, "text": text}
    return {"action": "choice", "choice": out}
