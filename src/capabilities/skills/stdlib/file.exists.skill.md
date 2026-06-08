---
name: stdlib.file.exists
description: Check if a file exists

primitives:
  - stdlib.file.exists

inputs:
  path:
    type: string
    required: true

outputs:
  exists: bool
  ok: bool

steps:
  - call: stdlib.file.exists
    args:
      path: "{{ path }}"

metadata:
  tags: ['file']
  input_types:
    path: string
  output_types:
    exists: bool
    ok: bool
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "pure"
  prerequisites: []
---
