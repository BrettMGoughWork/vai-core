---
name: stdlib.zip.create
description: Create a zip archive from a list of source files or directories

primitives:
  - stdlib.zip.create

inputs:
  archive:
    type: string
    required: true
  sources:
    type: list
    required: true

outputs:
  archive:
    type: string
  files_added:
    type: integer
  size_bytes:
    type: integer

steps:
  - call: stdlib.zip.create
    args:
      archive: "{{ archive }}"
      sources: "{{ sources }}"

metadata:
  tags: ["compression", "archive"]
  input_types:
    archive: string
    sources: list
  output_types:
    archive: string
    files_added: integer
    size_bytes: integer
  side_effects: ["file_write"]
  safety_level: "low"
  cost_estimate:
    latency: 5
    resources: "medium"
  determinism: "deterministic"
  prerequisites: []
---
