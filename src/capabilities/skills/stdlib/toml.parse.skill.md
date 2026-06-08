---
name: stdlib.toml.parse
description: Parse TOML text into a value

primitives:
  - stdlib.toml.parse

inputs:
  text:
    type: string
    required: true

outputs:
  value: any

steps:
  - call: stdlib.toml.parse
    args:
      text: "{{ text }}"

metadata:
  tags: ['toml']
  input_types:
    text: string
  output_types:
    value: any
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "pure"
  prerequisites: []
---
