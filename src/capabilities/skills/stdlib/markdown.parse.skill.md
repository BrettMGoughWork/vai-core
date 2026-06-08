---
name: stdlib.markdown.parse
description: Parse Markdown text into an AST

primitives:
  - stdlib.markdown.parse

inputs:
  text:
    type: string
    required: true

outputs:
  ast: object

steps:
  - call: stdlib.markdown.parse
    args:
      text: "{{ text }}"

metadata:
  tags: ['markdown']
  input_types:
    text: string
  output_types:
    ast: object
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "pure"
  prerequisites: []
---
