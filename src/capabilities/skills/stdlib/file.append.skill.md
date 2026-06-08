---
name: stdlib.file.append
description: Append content to a file

primitives:
  - stdlib.file.append

inputs:
  path:
    type: string
    required: true
  content:
    type: string
    required: true

outputs:
  ok: bool

steps:
  - call: stdlib.file.append
    args:
      path: "{{ path }}"
      content: "{{ content }}"

metadata:
  tags: ['file', 'write']
  input_types:
    path: string
    content: string
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
