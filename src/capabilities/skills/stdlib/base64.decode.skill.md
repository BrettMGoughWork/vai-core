---
name: stdlib.base64.decode
description: Decode base64-encoded data back to its original text

primitives:
  - stdlib.base64.decode

inputs:
  data:
    type: string
    required: true

outputs:
  text:
    type: string
  decoded_size:
    type: integer

steps:
  - call: stdlib.base64.decode
    args:
      data: "{{ data }}"

metadata:
  tags: ["encoding", "base64"]
  input_types:
    data: string
  output_types:
    text: string
    decoded_size: integer
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "deterministic"
  prerequisites: []
---
