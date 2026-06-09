---
name: stdlib.text.replace
description: Replace occurrences of a substring within a string

primitives:
  - stdlib.text.replace

inputs:
  text:
    type: string
    required: true
  old:
    type: string
    required: true
  new:
    type: string
    required: true
  count:
    type: number
    required: false

outputs:
  text:
    type: string
  replaced:
    type: number

steps:
  - call: stdlib.text.replace
    args:
      text: "{{ text }}"
      old: "{{ old }}"
      new: "{{ new }}"
      count: "{{ count }}"

metadata:
  tags: ["text", "string"]
  input_types:
    text: string
    old: string
    new: string
    count: number
  output_types:
    text: string
    replaced: number
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "pure"
  prerequisites: []
---
