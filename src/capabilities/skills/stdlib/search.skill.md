---
name: stdlib.search
description: Execute a web search and return normalised results (title, url, snippet)

primitives:
  - stdlib.search

inputs:
  query:
    type: string
    required: true

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

metadata:
  tags: ["search", "web"]
  input_types:
    query: string
  output_types:
    results: array
  side_effects: ["network"]
  safety_level: "low"
  cost_estimate:
    latency: 15
    resources: "medium"
  determinism: "non-deterministic"
  prerequisites: []
---
