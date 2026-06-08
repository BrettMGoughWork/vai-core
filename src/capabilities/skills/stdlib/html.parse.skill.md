---
name: stdlib.html.parse
description: Parse HTML text into a DOM

primitives:
  - stdlib.html.parse

inputs:
  text:
    type: string
    required: true

outputs:
  dom: object

steps:
  - call: stdlib.html.parse
    args:
      text: "{{ text }}"

metadata:
  tags: ['html']
  input_types:
    text: string
  output_types:
    dom: object
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "pure"
  prerequisites: []
---
