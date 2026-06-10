---
name: search.web
description: Search the web using a search provider and return structured results

primitives:
  - stdlib.search.web

inputs:
  query:
    type: string
    required: true
  num_results:
    type: number
    required: false
    default: 10

outputs:
  results:
    type: array
  query:
    type: string

steps:
  - call: stdlib.search.web
    args:
      query: "{{ query }}"
      num_results: "{{ num_results }}"

metadata:
  tags: ["search", "web"]
  input_types:
    query: string
    num_results: number
  output_types:
    results: array
    query: string
  side_effects: ["network"]
  safety_level: "medium"
  cost_estimate:
    latency: 1
    resources: "medium"
  determinism: "impure"
  prerequisites: []
---
