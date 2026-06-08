---
name: stdlib.file.delete
description: Delete a file

primitives:
  - stdlib.file.delete

inputs:
  path:
    type: string
    required: true

outputs:
  ok: bool

steps:
  - call: stdlib.file.delete
    args:
      path: "{{ path }}"

metadata:
  tags: ['file']
  input_types:
    path: string
  output_types:
    ok: bool
  side_effects: ["filesystem"]
  safety_level: "medium"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "pure"
  prerequisites: []
---
