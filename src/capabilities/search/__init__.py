"""Search provider abstraction layer (PHASE 3.13.1).

This package contains the search provider protocol, concrete providers,
and the provider registry.  Provider identity (e.g. "tavily", "duckduckgo")
and API keys are NEVER exposed to the LLM — the LLM receives only
normalised results in the standard schema.
"""
