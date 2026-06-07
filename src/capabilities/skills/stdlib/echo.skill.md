---
name: stdlib.echo
description: Return input unchanged using the stdlib.echo primitive

primitives:
  - stdlib.echo

inputs:
  value:
    type: any
    required: true

outputs:
  value:
    type: any

steps:
  - call: stdlib.echo
    args:
      value: "{{ value }}"

metadata:
  tags: ["echo"]
  input_types:
    value: any
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
