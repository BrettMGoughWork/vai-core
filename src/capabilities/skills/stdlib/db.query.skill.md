---
name: stdlib.db.query
description: Execute a read-only SQL SELECT query

primitives:
  - stdlib.db.query

inputs:
  query:
    type: string
    required: true
  params:
    type: list
    required: false

outputs:
  rows:
    type: list
  row_count:
    type: integer

steps:
  - call: stdlib.db.query
    args:
      query: "{{ query }}"
      params: "{{ params }}"

metadata:
  tags: ["database", "sql"]
  input_types:
    query: string
    params: list
  output_types:
    rows: list
    row_count: integer
  side_effects: ["none"]
  safety_level: "medium"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "impure"
  prerequisites: ["stdlib.db.connect"]
---
