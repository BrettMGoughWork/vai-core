---
name: stdlib.sys.tempfile
description: Create a temporary file and return its absolute path, optionally with content

primitives:
  - stdlib.sys.tempfile

inputs:
  suffix:
    type: string
    required: false
  prefix:
    type: string
    required: false
  directory:
    type: string
    required: false
  content:
    type: string
    required: false

outputs:
  path:
    type: string
  exists:
    type: boolean
  size_bytes:
    type: number

steps:
  - call: stdlib.sys.tempfile
    args:
      suffix: "{{ suffix }}"
      prefix: "{{ prefix }}"
      directory: "{{ directory }}"
      content: "{{ content }}"

metadata:
  tags: ["system", "file", "temporary"]
  input_types:
    suffix: string
    prefix: string
    directory: string
    content: string
  output_types:
    path: string
    exists: boolean
    size_bytes: number
  side_effects: ["filesystem"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "impure"
  prerequisites: []
---
