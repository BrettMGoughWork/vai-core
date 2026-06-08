---
name: stdlib.file.stat
description: Get file metadata (size, modified, created)

primitives:
  - stdlib.file.stat

inputs:
  path:
    type: string
    required: true

outputs:
  size: integer
  modified: string
  created: string
  ok: bool

steps:
  - call: stdlib.file.stat
    args:
      path: "{{ path }}"

metadata:
  tags: ['file']
  input_types:
    path: string
  output_types:
    size: integer
    modified: string
    created: string
    ok: bool
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "pure"
  prerequisites: []
---
