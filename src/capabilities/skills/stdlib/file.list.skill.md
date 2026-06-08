---
name: stdlib.file.list
description: List entries in a directory

primitives:
  - stdlib.file.list

inputs:
  path:
    type: string
    required: true

outputs:
  entries: list
  ok: bool

steps:
  - call: stdlib.file.list
    args:
      path: "{{ path }}"

metadata:
  tags: ['file', 'list']
  input_types:
    path: string
  output_types:
    entries: list
    ok: bool
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "pure"
  prerequisites: []
---
