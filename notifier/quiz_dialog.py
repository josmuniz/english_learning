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
    if q.get("hint"):
        header += f"\n(Tipo: {q['hint']})"
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


def build_add_lang_dialog() -> str:
    return ('display dialog "¿En qué idioma vas a escribir?" '
            'buttons {"Cancelar", "Español", "Inglés"} default button "Inglés" '
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


# ── Capa I/O ──────────────────────────────────────────────────────────

def log(status, detail=""):
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()} | {status} | {detail}\n")
    except OSError:
        pass


def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API_BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode())


def run_osascript(script) -> str:
    r = subprocess.run(["osascript", "-e", script],
                       capture_output=True, text=True, timeout=900)
    return r.stdout


def acquire_lock() -> bool:
    if LOCK_FILE.exists() and time.time() - LOCK_FILE.stat().st_mtime < LOCK_STALE_S:
        return False
    LOCK_FILE.write_text(str(int(time.time())))
    return True


# ── Orquestación ──────────────────────────────────────────────────────

def offer_add_word():
    lang_out = parse_dialog_output(run_osascript(build_add_lang_dialog()))
    if lang_out["action"] != "button":
        return
    lang = "es" if lang_out["button"] == "Español" else "en"

    out = parse_dialog_output(run_osascript(build_add_dialog()))
    entry = (out.get("text") or "").strip() if out["action"] == "button" else ""
    if not entry:
        return
    try:
        created = api("POST", "/api/words", {"word": entry, "lang": lang})
        run_osascript(build_info_dialog(f"✓ {created['word_en']} → {created['word_es']}"))
        log("added", entry)
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode()).get("detail", str(e))
        except Exception:
            detail = str(e)
        run_osascript(build_info_dialog(f"No se pudo agregar: {detail}"))
        log("add-error", detail)
    except (urllib.error.URLError, OSError) as e:
        log("add-error", str(e))


def main() -> int:
    if not acquire_lock():
        log("skip", "lock activo")
        return 0
    try:
        try:
            q = api("GET", "/api/quiz/next")
        except (urllib.error.URLError, OSError) as e:
            log("error", f"backend no disponible: {e}")
            return 0

        out = parse_dialog_output(run_osascript(build_question_dialog(q)))
        if out["action"] == "skip":
            log("skip", q["prompt"])
            return 0
        answer = out["choice"] if out["action"] == "choice" else (out.get("text") or "")
        answer = answer.strip()
        if not answer:
            log("skip", "respuesta vacía")
            return 0

        try:
            res = api("POST", "/api/quiz/answer",
                      {"word_id": q["word_id"], "type": q["type"],
                       "direction": q["direction"], "answer": answer})
        except (urllib.error.URLError, OSError) as e:
            log("error", f"answer falló: {e}")
            return 0
        log("ok" if res["correct"] else "wrong", f"{q['prompt']} -> {answer}")

        result = parse_dialog_output(run_osascript(build_result_dialog(res)))
        if result.get("button") == "+ Agregar":
            offer_add_word()
        return 0
    finally:
        LOCK_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
