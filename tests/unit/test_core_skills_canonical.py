from src.capabilities.canonical import canonicalise_args, canonicalize_args


def test_canonicalise_args_trims_and_coerces_values():
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
            "score": {"type": "number"},
            "active": {"type": "boolean"},
        },
    }
    raw = {
        "name": "  Alice   Smith  ",
        "age": " 42 ",
        "score": " 98.5 ",
        "active": "YES",
    }

    out = canonicalise_args(schema, raw)

    assert out == {
        "name": "Alice Smith",
        "age": 42,
        "score": 98.5,
        "active": True,
    }


def test_canonicalize_alias_matches_canonicalise():
    schema = {"type": "object", "properties": {"text": {"type": "string"}}}
    raw = {"text": "  hello   world  "}

    assert canonicalize_args(schema, raw) == canonicalise_args(schema, raw)
