---
name: stdlib.file.glob
description: Find files matching a glob pattern

primitives:
  - stdlib.file.glob

inputs:
  pattern:
    type: string
    required: true

outputs:
  paths: list
  ok: bool

steps:
  - call: stdlib.file.glob
    args:
      pattern: "{{ pattern }}"

metadata:
  tags: ['file', 'glob']
  input_types:
    pattern: string
  output_types:
    paths: list
    ok: bool
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 2
    resources: "low"
  determinism: "pure"
  prerequisites: []
---
