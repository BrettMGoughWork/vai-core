---
name: stdlib.gzip.decompress
description: Decompress a gzip file or base64-encoded gzip data

primitives:
  - stdlib.gzip.decompress

inputs:
  file:
    type: string
    required: false
    default: ""
  data:
    type: string
    required: false
    default: ""

outputs:
  text:
    type: string
  compressed_size:
    type: integer
  decompressed_size:
    type: integer

steps:
  - call: stdlib.gzip.decompress
    args:
      file: "{{ file }}"
      data: "{{ data }}"

metadata:
  tags: ["compression", "gzip"]
  input_types:
    file: string
    data: string
  output_types:
    text: string
    compressed_size: integer
    decompressed_size: integer
  side_effects: ["file_write"]
  safety_level: "low"
  cost_estimate:
    latency: 5
    resources: "medium"
  determinism: "deterministic"
  prerequisites: []
---
