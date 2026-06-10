---
name: stdlib.search_urls
description: Execute a web search and return normalised results (title, url, snippet)

primitives:
  - stdlib.search

inputs:
  query:
    type: string
    required: true
  max_results:
    type: number
    required: false
    default: 10

outputs:
  results:
    type: array
  query:
    type: string
  elapsed_ms:
    type: integer

steps:
  - call: stdlib.search
    args:
      query: "{{ query }}"
      max_results: "{{ max_results }}"

metadata:
  tags: ["search", "web"]
  input_types:
    query: string
    max_results: number
  output_types:
    results: array
    query: string
    elapsed_ms: integer
  side_effects: ["network"]
  safety_level: "low"
  cost_estimate:
    latency: 15
    resources: "medium"
  determinism: "non-deterministic"
  prerequisites: []
---
