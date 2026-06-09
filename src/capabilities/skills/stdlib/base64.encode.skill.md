---
name: stdlib.base64.encode
description: Encode a string or file content to base64

primitives:
  - stdlib.base64.encode

inputs:
  data:
    type: string
    required: false
  file:
    type: string
    required: false

outputs:
  encoded:
    type: string
  original_size:
    type: integer
  encoded_size:
    type: integer

steps:
  - call: stdlib.base64.encode
    args:
      data: "{{ data }}"
      file: "{{ file }}"

metadata:
  tags: ["encoding", "base64"]
  input_types:
    data: string
    file: string
  output_types:
    encoded: string
    original_size: integer
    encoded_size: integer
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "deterministic"
  prerequisites: []
---
