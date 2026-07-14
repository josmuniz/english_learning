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
