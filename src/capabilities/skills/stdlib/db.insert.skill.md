---
name: stdlib.db.insert
description: Insert one or more rows into a database table

primitives:
  - stdlib.db.insert

inputs:
  table:
    type: string
    required: true
  rows:
    type: list
    required: true

outputs:
  inserted:
    type: integer
  lastrowid:
    type: integer

steps:
  - call: stdlib.db.insert
    args:
      table: "{{ table }}"
      rows: "{{ rows }}"

metadata:
  tags: ["database", "sql"]
  input_types:
    table: string
    rows: list
  output_types:
    inserted: integer
    lastrowid: integer
  side_effects: ["write"]
  safety_level: "high"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "impure"
  prerequisites: ["stdlib.db.connect"]
---
