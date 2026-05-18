from .folder_boundaries import FolderBoundariesRule
from .no_llm import NoLLMRule
from .corestep_purity import CoreStepPurityRule
from .substrate_purity import SubstratePurityRule
from .event_envelope import EventEnvelopeRule
from .type_invariants import TypeInvariantsRule

def load_rules():
    return [
        FolderBoundariesRule(),
        NoLLMRule(),
        CoreStepPurityRule(),
        SubstratePurityRule(),
        EventEnvelopeRule(),
        TypeInvariantsRule(),
    ]