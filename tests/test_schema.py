import copy

import pytest

from shared.profile_schema import block_jumps, find_placeholders, substitute, validate_profile

GOOD = {
    "name": "portfreigabe-an",
    "description": "Test",
    "base_url": "http://192.168.178.1",
    "timeout_ms": 15000,
    "steps": [
        {"op": "goto", "value": "/"},
        {"op": "fill", "selector": "#pw", "value": "${SWITCHER_PASSWORD}"},
        {"op": "click", "selector": "#login"},
        {"op": "wait_ms", "value": "500"},
        {"op": "expect_checked", "selector": "#box", "comment": "Prüfung"},
    ],
}


def variant(**changes):
    data = copy.deepcopy(GOOD)
    data.update(changes)
    return data


def test_good_profile_is_valid():
    assert validate_profile(GOOD) == []


@pytest.mark.parametrize("name", ["", "Groß", "-x", "_x", "a b", "a/b", "../x", "x" * 65])
def test_bad_names(name):
    assert validate_profile(variant(name=name))


def test_unknown_top_level_field():
    assert validate_profile(variant(evil=True))


def test_unknown_op_and_script_op_not_available():
    for op in ("evaluate", "execute_js", "run"):
        data = variant(steps=[{"op": op, "value": "alert(1)"}])
        assert any("unbekannte Operation" in e for e in validate_profile(data))


def test_required_fields():
    errors = validate_profile(variant(steps=[{"op": "click"}]))
    assert any("selector fehlt" in e for e in errors)


def test_unused_field_rejected():
    errors = validate_profile(variant(steps=[{"op": "click", "selector": "#a", "value": "x"}]))
    assert any("nicht benutzt" in e for e in errors)


def test_variables_only_in_fill_value():
    bad_goto = variant(steps=[{"op": "goto", "value": "/?p=${SWITCHER_PASSWORD}"}])
    assert any("nur bei fill" in e for e in validate_profile(bad_goto))
    bad_selector = variant(steps=[{"op": "click", "selector": "#${SWITCHER_USER}"}])
    assert any("Selektor" in e for e in validate_profile(bad_selector))


def test_variable_name_must_start_with_ss():
    data = variant(steps=[{"op": "fill", "selector": "#a", "value": "${HOME}"}])
    assert any("nicht erlaubt" in e for e in validate_profile(data))


@pytest.mark.parametrize("value", ["abc", "0", "-5", "30001", "1.5"])
def test_wait_ms_bounds(value):
    assert validate_profile(variant(steps=[{"op": "wait_ms", "value": value}]))


@pytest.mark.parametrize(
    "value", ["login", "javascript:alert(1)", "//evil.example/x", "/\\evil.example", "/a\nb", "/\t/evil.example"]
)
def test_goto_needs_path_or_http_url(value):
    assert validate_profile(variant(steps=[{"op": "goto", "value": value}]))


@pytest.mark.parametrize("base", ["192.168.178.1", "ftp://x", "javascript:1", ""])
def test_base_url_must_be_http(base):
    assert validate_profile(variant(base_url=base))


@pytest.mark.parametrize("timeout", [0, 999, 60001, "15000", True])
def test_timeout_bounds(timeout):
    assert validate_profile(variant(timeout_ms=timeout))


def test_empty_and_too_many_steps():
    assert validate_profile(variant(steps=[]))
    assert validate_profile(variant(steps=[{"op": "goto", "value": "/"}] * 101))


def test_not_an_object():
    assert validate_profile([]) == ["Profil muss ein JSON-Objekt sein."]


def test_placeholders_found():
    data = variant(steps=[{"op": "click", "selector": "TODO: Button"}, {"op": "goto", "value": "/"}])
    assert find_placeholders(data) == ["Schritt 1: selector ist noch ein TODO-Platzhalter."]
    assert find_placeholders(GOOD) == []


def test_substitute():
    env = {"SWITCHER_PASSWORD": "geheim"}
    assert substitute("pw=${SWITCHER_PASSWORD}!", env) == "pw=geheim!"
    with pytest.raises(KeyError):
        substitute("${SWITCHER_MISSING}", env)
    with pytest.raises(KeyError):
        substitute("${HOME}", {"HOME": "/root"})
    with pytest.raises(KeyError):
        substitute("${SWITCHER_PASSWORD}", {"SWITCHER_PASSWORD": ""})


# ---------- Wenn-Blöcke ----------


def with_steps(*steps):
    return variant(steps=[{"op": "goto", "value": "/"}, *steps])


def test_if_else_block_is_valid():
    data = with_steps(
        {"op": "if_text", "value": "aktiv"},
        {"op": "click", "selector": "#a"},
        {"op": "else"},
        {"op": "click", "selector": "#b"},
        {"op": "end_if"},
    )
    assert validate_profile(data) == []


def test_else_is_optional_and_if_text_may_have_a_scope():
    data = with_steps(
        {"op": "if_text", "selector": "#bereich", "value": "aktiv"},
        {"op": "click", "selector": "#a"},
        {"op": "end_if"},
        {"op": "if_visible", "selector": "#x"},
        {"op": "end_if"},
    )
    assert validate_profile(data) == []


@pytest.mark.parametrize(
    "steps,fragment",
    [
        ([{"op": "else"}], "außerhalb"),
        ([{"op": "end_if"}], "außerhalb"),
        ([{"op": "if_text", "value": "x"}], "end_if fehlt"),
        ([{"op": "if_text", "value": "x"}, {"op": "else"}, {"op": "else"}, {"op": "end_if"}], "schon ein else"),
        ([{"op": "if_text", "value": "x"}, {"op": "if_visible", "selector": "#a"}, {"op": "end_if"}], "Verschachtelte"),
        ([{"op": "if_text", "value": "x"}, {"op": "end_if"}, {"op": "else"}], "außerhalb"),
    ],
)
def test_broken_blocks_are_rejected(steps, fragment):
    errors = validate_profile(with_steps(*steps))
    assert errors and any(fragment in e for e in errors)


@pytest.mark.parametrize(
    "step",
    [
        {"op": "if_text"},  # value fehlt
        {"op": "if_visible"},  # selector fehlt
        {"op": "if_visible", "selector": "#a", "value": "x"},  # value nicht benutzt
        {"op": "else", "selector": "#a"},
        {"op": "end_if", "value": "x"},
        {"op": "if_text", "value": "${SWITCHER_PASSWORD}"},  # Variablen nur bei fill
        {"op": "if_text", "value": "x", "selector": "${SWITCHER_USER}"},
    ],
)
def test_bad_condition_fields_are_rejected(step):
    assert validate_profile(with_steps(step, {"op": "end_if"}))


def test_block_jumps():
    steps = [
        {"op": "click", "selector": "#0"},
        {"op": "if_text", "value": "x"},  # 1
        {"op": "click", "selector": "#2"},
        {"op": "else"},  # 3
        {"op": "click", "selector": "#4"},
        {"op": "end_if"},  # 5
        {"op": "if_visible", "selector": "#6"},  # 6
        {"op": "click", "selector": "#7"},
        {"op": "end_if"},  # 8
    ]
    assert block_jumps(steps) == {1: 4, 3: 6, 6: 9}
