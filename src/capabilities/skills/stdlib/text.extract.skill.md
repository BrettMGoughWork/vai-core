---
name: stdlib.text.extract
description: Extract substrings from text using a regex pattern

primitives:
  - stdlib.text.extract

inputs:
  text:
    type: string
    required: true
  pattern:
    type: string
    required: true
  flags:
    type: number
    required: false
    default: 0
  group:
    type: any
    required: false
    default: ~

outputs:
  matches:
    type: list
  count:
    type: number

steps:
  - call: stdlib.text.extract
    args:
      text: "{{ text }}"
      pattern: "{{ pattern }}"
      flags: "{{ flags }}"
      group: "{{ group }}"

metadata:
  tags: ["text", "regex"]
  input_types:
    text: string
    pattern: string
    flags: number
    group: any
  output_types:
    matches: list
    count: number
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "pure"
  prerequisites: []
---
