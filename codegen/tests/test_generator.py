"""Unit tests of the generator: naming rules, type mapping and examples.

Run with `pytest codegen/tests` (from the repository root, in the Python venv).
The generated code itself is covered by the Rust and Python test suites.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import examples as ex  # noqa: E402
import naming  # noqa: E402
import python_out  # noqa: E402
import rust_out  # noqa: E402
import spec  # noqa: E402
from spec import T  # noqa: E402


@pytest.mark.parametrize(
    ("raw", "snake", "pascal"),
    [
        ("firstName", "first_name", "FirstName"),
        ("get-persons-id", "get_persons_id", "GetPersonsId"),
        ("HTMLTemplate", "html_template", "HTMLTemplate"),
        ("2fa", "f_2fa", "T2fa"),
        ("@deprecated", "deprecated", "Deprecated"),
    ],
)
def test_snake_and_pascal(raw: str, snake: str, pascal: str) -> None:
    assert naming.snake(raw) == snake
    assert naming.pascal(raw) == pascal


def test_identifiers_avoid_keywords() -> None:
    assert naming.py_ident("from") == "from_"
    assert naming.py_ident("model_dump") == "model_dump_"  # Pydantic attribute
    assert naming.rust_ident("type") == "r#type"
    assert naming.rust_ident("self") == "self_"
    assert naming.keyword_safe("match") == "match_"


def test_unique_numbers_collisions() -> None:
    taken: set[str] = set()
    assert [naming.unique(n, taken) for n in ("name", "name", "event_services", "event_services")] == [
        "name",
        "name2",
        "event_services",
        "event_services_2",
    ]


@pytest.mark.parametrize(
    ("segment", "split"),
    [
        ("agendatemplates", "agenda_templates"),
        ("masterdata", "master_data"),
        ("possiblepersonsforservice", "possible_persons_for_service"),
        ("get_privacypolicy", "get_privacy_policy"),
        ("persons", "persons"),  # a single word
        ("absences", "absences"),  # not in the word list: unchanged
        ("eubpsubmission", "eubpsubmission"),  # only partly known: unchanged
    ],
)
def test_split_words(segment: str, split: str) -> None:
    assert naming.split_words(segment) == split


def test_clean_doc_drops_placeholders_and_html() -> None:
    assert naming.clean_doc("TODO 200") == ""
    assert naming.clean_doc("a<br>b <b>c</b>") == "a\nb c"


def schemas(components: dict | None = None) -> spec.Schemas:
    return spec.Schemas(components or {})


def test_enums_keep_their_values() -> None:
    s = schemas()
    t = s.type_of({"type": "string", "enum": ["csv", "xlsx", None]}, "Format")
    assert t == spec.opt(T("str", values=("csv", "xlsx")))
    assert s.type_of({"enum": [1, 2]}, "Level") == T("int", values=(1, 2))
    assert s.type_of({"type": "boolean", "enum": [True]}, "Flag") == T("bool")
    assert spec.allowed_doc(T("list", (T("str", values=("a", "b")),))) == "Allowed values: `a`, `b`."


def test_python_enum_annotations() -> None:
    t = T("str", values=("csv", "xlsx"))
    assert python_out.py_type(t) == "str"
    assert python_out.py_type(t, enums="strict") == "_t.Literal['csv', 'xlsx']"
    assert python_out.py_type(t, enums="open") == "_t.Union[_t.Literal['csv', 'xlsx'], str]"
    # Literal values that look like model names are not prefixed with `models.`
    assert python_out.model_type_for_resources(T("str", values=("Person",)), "strict") == "_t.Literal['Person']"
    assert python_out.model_type_for_resources(T("model", name="Person")) == "models.Person"


def test_objects_become_models_named_after_components() -> None:
    person = {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}
    s = schemas({"Person": person})
    assert s.type_of(dict(person), "Whatever") == T("model", name="Person")
    assert s.models["Person"].fields[0].required
    inline = s.type_of({"type": "object", "properties": {"x": {"type": "string"}}}, "PostThingsBody")
    assert inline == T("model", name="PostThingsBody")


def test_unions_flatten_and_collect_null() -> None:
    t = spec.union([T("int"), T("null"), spec.union([T("str"), T("int")])])
    assert t == spec.opt(T("union", (T("int"), T("str"))))
    assert spec.union([T("int"), spec.ANY]) == spec.ANY


def test_rust_types() -> None:
    assert rust_out.rust_type(spec.opt(T("list", (T("int"),)))) == "Option<Vec<i64>>"
    assert rust_out.rust_type(T("union", (T("date"), T("datetime")))) == "crate::DateOrDateTime"
    assert rust_out.rust_type(T("union", (T("int"), T("str")))) == "serde_json::Value"
    assert rust_out.rust_type(T("model", name="Person"), prefix="models::") == "models::Person"


def test_rustdoc_escapes_spec_text_but_not_code() -> None:
    assert rust_out.rustdoc_safe("see [eventId] and https://x.org.") == r"see \[eventId\] and <https://x.org>."
    assert rust_out.rustdoc_safe("`startTimes`[`eventId`]") == r"`startTimes`\[`eventId`\]"
    assert rust_out.rustdoc_safe("Use [`Self::list_with`] or `a[0]`") == "Use [`Self::list_with`] or `a[0]`"
    assert rust_out.rust_doc("```\nlet v = vec![1];\n```", "") == ["/// ```", "/// let v = vec![1];", "/// ```"]


def test_deprecation_hint_finds_the_replacement() -> None:
    assert spec.deprecation_hint("Legacy alias. Use `format` instead.") == "Use `format` instead."
    assert spec.deprecation_hint("Use `format`") == "Use `format`"
    assert spec.deprecation_hint("Returns all fields.") == ""


def op_spec(paths: dict) -> list[spec.Op]:
    return spec.collect_ops({"paths": paths}, schemas())


def test_names_follow_the_path() -> None:
    ok = {"200": {"content": {"application/json": {"schema": {"properties": {"data": {"type": "array"}}}}}}}
    one = {"200": {"content": {"application/json": {"schema": {"properties": {"data": {"type": "object"}}}}}}}
    param = [{"in": "path", "name": "personId", "required": True, "schema": {"type": "integer"}}]
    ops = op_spec(
        {
            "/persons": {"get": {"operationId": "get-persons", "responses": ok}},
            "/persons/{personId}": {"get": {"operationId": "get-persons-id", "parameters": param, "responses": one}},
            "/persons/{personId}/groups": {"get": {"operationId": "get-groups", "parameters": param, "responses": ok}},
            "/persons/{personId}/invite": {"post": {"operationId": "invite", "parameters": param, "responses": {}}},
            "/agendatemplates": {"post": {"operationId": "create-template", "responses": {}}},
        }
    )
    names = {op.op_id: (".".join(op.chain), op.name) for op in ops}
    assert names == {
        "get-persons": ("persons", "list"),
        "get-persons-id": ("persons", "get"),
        "get-groups": ("persons", "list_groups"),
        "invite": ("persons", "invite"),
        "create-template": ("agenda_templates", "create"),
    }
    assert spec.check_names(ops) == []


def test_name_conflicts_are_reported() -> None:
    ops = op_spec(
        {
            "/a": {"get": {"operationId": "one", "responses": {}}},
            "/a/": {"get": {"operationId": "two", "responses": {}}},
        }
    )
    assert spec.check_names(ops) == ["a.get: GET /a (one), GET /a/ (two)"]


def test_array_query_parameters_get_brackets() -> None:
    (op,) = op_spec(
        {
            "/persons": {
                "get": {
                    "operationId": "get-persons",
                    "parameters": [{"in": "query", "name": "ids", "schema": {"type": "array", "items": {"type": "integer"}}}],
                    "responses": {},
                }
            }
        }
    )
    assert op.params[0].name == "ids[]"


def test_example_values_respect_enums() -> None:
    s = schemas()
    assert ex.json_example(s, T("str", values=("active", "waiting")), "status") == "active"
    assert ex.json_example(s, T("str", values=("active",)), "status", example="bogus") == "active"
    assert ex.json_example(s, T("str"), "email") == "anna@example.org"
    assert ex.json_example(s, T("str"), "url") == "https://example.org"
