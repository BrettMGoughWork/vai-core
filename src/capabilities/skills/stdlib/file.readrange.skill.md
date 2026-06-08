---
name: stdlib.file.readrange
description: Read a byte range from a file

primitives:
  - stdlib.file.readrange

inputs:
  path:
    type: string
    required: true
  start:
    type: integer
    required: true
  end:
    type: integer
    required: true

outputs:
  content: string

steps:
  - call: stdlib.file.readrange
    args:
      path: "{{ path }}"
      start: "{{ start }}"
      end: "{{ end }}"

metadata:
  tags: ['file', 'read']
  input_types:
    path: string
    start: integer
    end: integer
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
