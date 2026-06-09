---
name: stdlib.doc.detecttype
description: Detect the document type from a file path

primitives:
  - stdlib.doc.detecttype

inputs:
  path:
    type: string
    required: true

outputs:
  extension:
    type: string
  mime_type:
    type: string
  category:
    type: string
  is_binary:
    type: boolean

steps:
  - call: stdlib.doc.detecttype
    args:
      path: "{{ path }}"

metadata:
  tags: ["document", "file"]
  input_types:
    path: string
  output_types:
    extension: string
    mime_type: string
    category: string
    is_binary: boolean
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "pure"
  prerequisites: []
---
