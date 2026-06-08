---
name: stdlib.html.select
description: Select elements from a DOM using a CSS selector

primitives:
  - stdlib.html.select

inputs:
  dom:
    type: object
    required: true
  selector:
    type: string
    required: true

outputs:
  matches: list

steps:
  - call: stdlib.html.select
    args:
      dom: "{{ dom }}"
      selector: "{{ selector }}"

metadata:
  tags: ['html']
  input_types:
    dom: object
    selector: string
  output_types:
    matches: list
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "pure"
  prerequisites: []
---
