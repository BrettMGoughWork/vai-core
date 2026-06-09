---
name: stdlib.text.normalize
description: Normalize text by trimming, collapsing whitespace, and optionally lowering case

primitives:
  - stdlib.text.normalize

inputs:
  text:
    type: string
    required: true
  lowercase:
    type: boolean
    required: false
  strip_punctuation:
    type: boolean
    required: false

outputs:
  text:
    type: string
  length:
    type: number

steps:
  - call: stdlib.text.normalize
    args:
      text: "{{ text }}"
      lowercase: "{{ lowercase }}"
      strip_punctuation: "{{ strip_punctuation }}"

metadata:
  tags: ["text", "string"]
  input_types:
    text: string
    lowercase: boolean
    strip_punctuation: boolean
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
