import pytest
from src.core.planning.cognitive_normaliser import normalise_cognitive_structure
from src.core.types.validation.purity_validation import validate_pure_structure
from src.core.types.errors.ValidationError import ValidationError

@pytest.fixture
def unsorted_dict():
    return {"b": 2, "a": 1, "c": {"z": 0, "y": 1}}

@pytest.fixture
def nested_list_dict():
    return {"a": [3, 2, 1], "b": {"c": [2, 1]}}

@pytest.fixture
def impure_dict():
    return {"a": set([1, 2, 3])}

@pytest.fixture
def forbidden_key_dict():
    return {42: "not a string key"}

def test_normalise_sorts_keys(unsorted_dict):
    result = normalise_cognitive_structure(unsorted_dict)
    assert list(result.keys()) == sorted(result.keys())

def test_normalise_recursively_normalises(nested_list_dict):
    result = normalise_cognitive_structure(nested_list_dict)
    assert isinstance(result["b"]["c"], list)
    assert result["b"]["c"] == [2, 1]

def test_normalise_preserves_list_order(nested_list_dict):
    result = normalise_cognitive_structure(nested_list_dict)
    assert result["a"] == [3, 2, 1]

def test_normalise_is_deterministic(unsorted_dict):
    r1 = normalise_cognitive_structure(unsorted_dict)
    r2 = normalise_cognitive_structure({"a": 1, "b": 2, "c": {"y": 1, "z": 0}})
    assert r1 == r2

def test_normalise_rejects_impure_types(impure_dict):
    with pytest.raises(ValidationError):
        normalise_cognitive_structure(impure_dict)

def test_normalise_rejects_non_string_keys(forbidden_key_dict):
    with pytest.raises(ValidationError):
        normalise_cognitive_structure(forbidden_key_dict)

def test_normalise_scalar_passthrough():
    for scalar in [1, 3.14, "foo", True, None]:
        assert normalise_cognitive_structure(scalar) == scalar

def test_normalise_validates_json_purity(unsorted_dict):
    # Should not raise
    validate_pure_structure(normalise_cognitive_structure(unsorted_dict))
