---
name: stdlib.db.describetable
description: Describe the schema of a database table

primitives:
  - stdlib.db.describetable

inputs:
  table:
    type: string
    required: true

outputs:
  table:
    type: string
  columns:
    type: list

steps:
  - call: stdlib.db.describetable
    args:
      table: "{{ table }}"

metadata:
  tags: ["database", "schema"]
  input_types:
    table: string
  output_types:
    table: string
    columns: list
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "pure"
  prerequisites: ["stdlib.db.connect"]
---
