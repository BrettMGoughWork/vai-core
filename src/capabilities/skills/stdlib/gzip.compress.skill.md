---
name: stdlib.gzip.compress
description: Compress a file or string data using gzip

primitives:
  - stdlib.gzip.compress

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
  output:
    type: string
  original_size:
    type: integer
  compressed_size:
    type: integer

steps:
  - call: stdlib.gzip.compress
    args:
      file: "{{ file }}"
      data: "{{ data }}"

metadata:
  tags: ["compression", "gzip"]
  input_types:
    file: string
    data: string
  output_types:
    output: string
    original_size: integer
    compressed_size: integer
  side_effects: ["file_write"]
  safety_level: "low"
  cost_estimate:
    latency: 5
    resources: "medium"
  determinism: "deterministic"
  prerequisites: []
---
