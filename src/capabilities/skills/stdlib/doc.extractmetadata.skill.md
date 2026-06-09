---
name: stdlib.doc.extractmetadata
description: Extract file metadata including size, timestamps, and permissions

primitives:
  - stdlib.doc.extractmetadata

inputs:
  path:
    type: string
    required: true

outputs:
  path:
    type: string
  filename:
    type: string
  size_bytes:
    type: number
  created_at:
    type: string
  modified_at:
    type: string
  is_file:
    type: boolean
  is_directory:
    type: boolean
  permissions:
    type: string

steps:
  - call: stdlib.doc.extractmetadata
    args:
      path: "{{ path }}"

metadata:
  tags: ["document", "file", "metadata"]
  input_types:
    path: string
  output_types:
    path: string
    filename: string
    size_bytes: number
    created_at: string
    modified_at: string
    is_file: boolean
    is_directory: boolean
    permissions: string
  side_effects: ["filesystem"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "impure"
  prerequisites: []
---
