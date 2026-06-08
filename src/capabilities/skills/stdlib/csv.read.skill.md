---
name: stdlib.csv.read
description: Read rows from a CSV file

primitives:
  - stdlib.csv.read

inputs:
  path:
    type: string
    required: true

outputs:
  rows: list
  ok: bool

steps:
  - call: stdlib.csv.read
    args:
      path: "{{ path }}"

metadata:
  tags: ['csv']
  input_types:
    path: string
  output_types:
    rows: list
    ok: bool
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "pure"
  prerequisites: []
---
