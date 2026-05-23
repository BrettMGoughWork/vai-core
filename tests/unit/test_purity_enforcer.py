import pytest
from src.core.planning.purity_enforcer import enforce_cognitive_purity
from src.core.types.errors.ValidationError import ValidationError
from dataclasses import dataclass, FrozenInstanceError

@pytest.fixture
def pure_dict():
    return {"a": 1, "b": [2, 3], "c": {"d": "x"}}

@pytest.fixture
def forbidden_dict():
    return {"tool": 42}

@pytest.fixture
def unserializable_dict():
    return {"a": set([1, 2, 3])}

def test_enforce_purity_accepts_json_pure(pure_dict):
    result = enforce_cognitive_purity(pure_dict)
    assert result == pure_dict

def test_enforce_purity_rejects_forbidden_keys(forbidden_dict):
    with pytest.raises(ValidationError):
        enforce_cognitive_purity(forbidden_dict)

def test_enforce_purity_rejects_unserializable_types(unserializable_dict):
    with pytest.raises(ValidationError):
        enforce_cognitive_purity(unserializable_dict)

@dataclass(frozen=True)
class FrozenExample:
    x: int

def test_frozen_dataclass_immutable():
    obj = FrozenExample(1)
    with pytest.raises(FrozenInstanceError):
        obj.x = 2
