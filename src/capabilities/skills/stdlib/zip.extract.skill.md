---
name: stdlib.zip.extract
description: Extract files from a zip archive to a destination directory

primitives:
  - stdlib.zip.extract

inputs:
  archive:
    type: string
    required: true
  destination:
    type: string
    required: false

outputs:
  extracted_to:
    type: string
  files_extracted:
    type: integer
  file_list:
    type: list

steps:
  - call: stdlib.zip.extract
    args:
      archive: "{{ archive }}"
      destination: "{{ destination }}"

metadata:
  tags: ["compression", "archive"]
  input_types:
    archive: string
    destination: string
  output_types:
    extracted_to: string
    files_extracted: integer
    file_list: list
  side_effects: ["file_write"]
  safety_level: "low"
  cost_estimate:
    latency: 5
    resources: "medium"
  determinism: "deterministic"
  prerequisites: []
---
