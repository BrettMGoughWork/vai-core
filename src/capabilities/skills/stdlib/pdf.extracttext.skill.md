---
name: stdlib.pdf.extracttext
description: Extract text from a PDF file

primitives:
  - stdlib.pdf.extracttext

inputs:
  path:
    type: string
    required: true

outputs:
  text: string

steps:
  - call: stdlib.pdf.extracttext
    args:
      path: "{{ path }}"

metadata:
  tags: ['pdf']
  input_types:
    path: string
  output_types:
    text: string
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "pure"
  prerequisites: []
---
