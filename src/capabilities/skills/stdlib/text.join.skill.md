---
name: stdlib.text.join
description: Join a list of strings into a single string using a delimiter

primitives:
  - stdlib.text.join

inputs:
  parts:
    type: list
    required: true
  delimiter:
    type: string
    required: false
    default: ", "

outputs:
  text:
    type: string
  length:
    type: number

steps:
  - call: stdlib.text.join
    args:
      parts: "{{ parts }}"
      delimiter: "{{ delimiter }}"

metadata:
  tags: ["text", "string"]
  input_types:
    parts: list
    delimiter: string
  output_types:
    text: string
    length: number
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "pure"
  prerequisites: []
---
