---
name: stdlib.csv.write
description: Write rows to a CSV file

primitives:
  - stdlib.csv.write

inputs:
  path:
    type: string
    required: true
  rows:
    type: list
    required: true

outputs:
  ok: bool

steps:
  - call: stdlib.csv.write
    args:
      path: "{{ path }}"
      rows: "{{ rows }}"

metadata:
  tags: ['csv']
  input_types:
    path: string
    rows: list
  output_types:
    ok: bool
  side_effects: ["filesystem"]
  safety_level: "medium"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "pure"
  prerequisites: []
---
