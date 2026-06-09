---
name: stdlib.db.delete
description: Delete rows from a database table

primitives:
  - stdlib.db.delete

inputs:
  table:
    type: string
    required: true
  where:
    type: object
    required: false

outputs:
  deleted:
    type: integer

steps:
  - call: stdlib.db.delete
    args:
      table: "{{ table }}"
      where: "{{ where }}"

metadata:
  tags: ["database", "sql"]
  input_types:
    table: string
    where: object
  output_types:
    deleted: integer
  side_effects: ["write"]
  safety_level: "high"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "impure"
  prerequisites: ["stdlib.db.connect"]
---
