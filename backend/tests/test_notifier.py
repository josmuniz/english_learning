import pytest
import urllib.error

from notifier import quiz_dialog as nd


def test_applescript_escape():
    assert nd.applescript_escape('say "hi" \\ ok') == 'say \\"hi\\" \\\\ ok'


def test_build_question_dialog_mc():
    q = {"type": "mc_word", "direction": "en_to_es", "prompt": "strong",
         "prompt_secondary": "(strang)", "hint": "adjective",
         "options": ["fuerte", 'feliz "x"', "casa", "preciosa"]}
    s = nd.build_question_dialog(q)
    assert "choose from list" in s
    assert '"fuerte"' in s and 'feliz \\"x\\"' in s
    assert "¿Qué significa en español?" in s
    assert "(strang)" in s
    assert "(Tipo: adjective)" in s


def test_build_question_dialog_typing():
    q = {"type": "typing", "direction": "es_to_en",
         "prompt": "palabra", "prompt_secondary": ""}
    s = nd.build_question_dialog(q)
    assert "display dialog" in s and "default answer" in s
    assert '"Saltar", "Responder"' in s


def test_parse_choose_from_list():
    assert nd.parse_dialog_output("false") == {"action": "skip"}
    assert nd.parse_dialog_output("") == {"action": "skip"}
    assert nd.parse_dialog_output("fuerte\n") == {"action": "choice", "choice": "fuerte"}


def test_parse_display_dialog():
    r = nd.parse_dialog_output("button returned:Responder, text returned:hola, mundo")
    assert r == {"action": "button", "button": "Responder", "text": "hola, mundo"}
    assert nd.parse_dialog_output("button returned:Saltar")["action"] == "skip"
    assert nd.parse_dialog_output("button returned:Cancelar")["action"] == "skip"
    assert nd.parse_dialog_output("button returned:, gave up:true")["action"] == "skip"
    r2 = nd.parse_dialog_output("button returned:OK, gave up:false")
    assert r2 == {"action": "button", "button": "OK", "text": None}


def test_build_result_dialog():
    ok = nd.build_result_dialog({"correct": True, "correct_answer": "fuerte"})
    assert "¡Correcto!" in ok and '"+ Agregar", "OK"' in ok and "giving up after 60" in ok
    bad = nd.build_result_dialog({"correct": False, "correct_answer": "fuerte"})
    assert "Incorrecto" in bad and "fuerte" in bad


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(nd, "LOCK_FILE", tmp_path / "lock")
    monkeypatch.setattr(nd, "LOG_FILE", tmp_path / "log")
    return tmp_path


def test_main_backend_down_exits_silently(sandbox, monkeypatch):
    scripts = []
    monkeypatch.setattr(nd, "run_osascript", lambda s: scripts.append(s) or "")

    def failing_api(method, path, body=None):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(nd, "api", failing_api)
    assert nd.main() == 0
    assert scripts == []                    # ningún diálogo
    assert not (sandbox / "lock").exists()  # lock liberado


def test_main_lock_fresh_skips(sandbox, monkeypatch):
    (sandbox / "lock").write_text("1")
    called = []
    monkeypatch.setattr(nd, "api", lambda *a, **k: called.append(a))
    assert nd.main() == 0
    assert called == []


def test_main_full_flow_mc(sandbox, monkeypatch):
    api_calls = []

    def fake_api(method, path, body=None):
        api_calls.append((method, path, body))
        if path == "/api/quiz/next":
            return {"word_id": "id-1", "type": "mc_word", "direction": "en_to_es",
                    "prompt": "strong", "prompt_secondary": "", "hint": "adjective",
                    "options": ["fuerte", "feliz", "casa", "linda"]}
        return {"correct": True, "correct_answer": "fuerte", "word": {}}

    outputs = iter(["fuerte", "button returned:OK, gave up:false"])
    scripts = []

    def fake_osascript(script):
        scripts.append(script)
        return next(outputs)

    monkeypatch.setattr(nd, "api", fake_api)
    monkeypatch.setattr(nd, "run_osascript", fake_osascript)
    assert nd.main() == 0
    assert api_calls[1] == ("POST", "/api/quiz/answer",
                            {"word_id": "id-1", "type": "mc_word",
                             "direction": "en_to_es", "answer": "fuerte"})
    assert len(scripts) == 2  # pregunta + resultado (sin "+ Agregar")


def test_main_skip_does_not_post(sandbox, monkeypatch):
    api_calls = []

    def fake_api(method, path, body=None):
        api_calls.append(path)
        return {"word_id": "id-1", "type": "typing", "direction": "es_to_en",
                "prompt": "palabra1", "prompt_secondary": "", "hint": "noun"}

    monkeypatch.setattr(nd, "api", fake_api)
    monkeypatch.setattr(nd, "run_osascript", lambda s: "button returned:Saltar")
    assert nd.main() == 0
    assert api_calls == ["/api/quiz/next"]


def test_build_add_lang_dialog():
    s = nd.build_add_lang_dialog()
    assert '"Cancelar", "Español", "Inglés"' in s
    assert 'default button "Inglés"' in s and "giving up after 60" in s


def test_add_word_lang_cancel_aborts(sandbox, monkeypatch):
    api_calls = []

    def fake_api(method, path, body=None):
        api_calls.append((method, path, body))
        if path == "/api/quiz/next":
            return {"word_id": "id-1", "type": "typing", "direction": "es_to_en",
                    "prompt": "palabra1", "prompt_secondary": "", "hint": "noun"}
        return {"correct": True, "correct_answer": "word1", "word": {}}

    outputs = iter([
        "button returned:Responder, text returned:word1",   # pregunta
        "button returned:+ Agregar, gave up:false",          # resultado
        "button returned:Cancelar",                          # idioma → cancela
    ])
    monkeypatch.setattr(nd, "api", fake_api)
    monkeypatch.setattr(nd, "run_osascript", lambda s: next(outputs))
    assert nd.main() == 0
    assert not any(p == "/api/words" for _, p, _ in api_calls)


def test_add_word_flow(sandbox, monkeypatch):
    api_calls = []

    def fake_api(method, path, body=None):
        api_calls.append((method, path, body))
        if path == "/api/quiz/next":
            return {"word_id": "id-1", "type": "typing", "direction": "es_to_en",
                    "prompt": "palabra1", "prompt_secondary": "", "hint": "noun"}
        if path == "/api/quiz/answer":
            return {"correct": True, "correct_answer": "word1", "word": {}}
        return {"word_en": "break the ice", "word_es": "romper el hielo"}

    outputs = iter([
        "button returned:Responder, text returned:word1",      # pregunta typing
        "button returned:+ Agregar, gave up:false",             # resultado
        "button returned:Español",                              # idioma
        "button returned:Agregar, text returned:break the ice", # alta
        "button returned:OK",                                   # confirmación
    ])
    monkeypatch.setattr(nd, "api", fake_api)
    monkeypatch.setattr(nd, "run_osascript", lambda s: next(outputs))
    assert nd.main() == 0
    assert ("POST", "/api/words", {"word": "break the ice", "lang": "es"}) in api_calls


def test_main_404_sin_habilitadas_logs_skip(sandbox, monkeypatch):
    scripts = []
    monkeypatch.setattr(nd, "run_osascript", lambda s: scripts.append(s) or "")

    def api_404(method, path, body=None):
        raise urllib.error.HTTPError(path, 404, "Not Found", {}, None)

    monkeypatch.setattr(nd, "api", api_404)
    assert nd.main() == 0
    assert scripts == []                    # ningún diálogo
    log_text = (sandbox / "log").read_text(encoding="utf-8")
    assert "sin palabras habilitadas" in log_text
    assert "backend no disponible" not in log_text


def test_build_result_dialog_muestra_sonido_es_to_en():
    res = {"correct": True, "correct_answer": "sneaky",
           "word": {"pronunciation_es": "sniki"}}
    out = nd.build_result_dialog(res, direction="es_to_en")
    assert "sniki" in out
    # en_to_es: la respuesta es español, no corresponde pronunciación
    out2 = nd.build_result_dialog(res, direction="en_to_es")
    assert "sniki" not in out2
    # sin pronunciación: no agrega nada raro
    res3 = {"correct": False, "correct_answer": "sneaky", "word": {}}
    assert "()" not in nd.build_result_dialog(res3, direction="es_to_en")


def test_prompt_label_dialogue_next():
    q = {"type": "dialogue_next", "direction": "es_to_en",
         "prompt": "hey, how you doing?", "hint": "phrase",
         "options": ["a", "b", "c", "d"]}
    out = nd.build_question_dialog(q)
    assert "siguiente frase del diálogo" in out


def test_result_dialog_dialogue_next_sin_pronunciacion():
    res = {"correct": True, "correct_answer": "fine, thanks",
           "word": {"pronunciation_es": "jai jau ar yu"}}
    out = nd.build_result_dialog(res, direction="es_to_en", qtype="dialogue_next")
    assert "jai jau ar yu" not in out       # la pron es de la línea N, no de la respuesta
