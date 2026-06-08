---
name: stdlib.file.search
description: Search for a pattern in a file

primitives:
  - stdlib.file.search

inputs:
  path:
    type: string
    required: true
  pattern:
    type: string
    required: true

outputs:
  matches: list
  ok: bool

steps:
  - call: stdlib.file.search
    args:
      path: "{{ path }}"
      pattern: "{{ pattern }}"

metadata:
  tags: ['file', 'search']
  input_types:
    path: string
    pattern: string
  output_types:
    matches: list
    ok: bool
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 2
    resources: "low"
  determinism: "pure"
  prerequisites: []
---
