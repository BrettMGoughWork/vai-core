from .deadcode_markers import deadcode_ignore

def validate_structural(obj, schema) -> None:
    """
    Placeholder for structural validator.
    
    The real implementation lived in the planning/validation layer,
    but for 2.3.6a the runtime only needs this to exist and be callable..
    """
    from src.capabilities.runtime.validator import validate_structural as _validate_structural
    return _validate_structural(obj, schema)

def validate_pure_structure(plan) -> None:
    """
    Placeholder for pure structure validator.
    
    The real implementation lived in the planning/validation layer,
    but for 2.3.6a the runtime only needs this to exist and be callable..
    """
    from src.core.planning.safety.purity_validation import validate_pure_structure as _validate_pure_structure
    return _validate_pure_structure(plan)