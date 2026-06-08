---
name: stdlib.yaml.parse
description: Parse YAML text into a value

primitives:
  - stdlib.yaml.parse

inputs:
  text:
    type: string
    required: true

outputs:
  value: any

steps:
  - call: stdlib.yaml.parse
    args:
      text: "{{ text }}"

metadata:
  tags: ['yaml']
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
