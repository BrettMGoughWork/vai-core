---
name: stdlib.text.split
description: Split a string into a list of substrings by a delimiter

primitives:
  - stdlib.text.split

inputs:
  text:
    type: string
    required: true
  delimiter:
    type: string
    required: false
    default: ","
  maxsplit:
    type: number
    required: false
    default: -1

outputs:
  parts:
    type: list
  count:
    type: number

steps:
  - call: stdlib.text.split
    args:
      text: "{{ text }}"
      delimiter: "{{ delimiter }}"
      maxsplit: "{{ maxsplit }}"

metadata:
  tags: ["text", "string"]
  input_types:
    text: string
    delimiter: string
    maxsplit: number
  output_types:
    parts: list
    count: number
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "pure"
  prerequisites: []
---
