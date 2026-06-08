---
name: stdlib.file.readtail
description: Read last N lines of a file

primitives:
  - stdlib.file.readtail

inputs:
  path:
    type: string
    required: true
  lines:
    type: integer
    required: true

outputs:
  content: string

steps:
  - call: stdlib.file.readtail
    args:
      path: "{{ path }}"
      lines: "{{ lines }}"

metadata:
  tags: ['file', 'read']
  input_types:
    path: string
    lines: integer
  output_types:
    content: string
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "pure"
  prerequisites: []
---
