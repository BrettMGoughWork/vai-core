---
name: stdlib.db.update
description: Update rows in a database table

primitives:
  - stdlib.db.update

inputs:
  table:
    type: string
    required: true
  set:
    type: object
    required: true
  where:
    type: object
    required: true

outputs:
  updated:
    type: integer

steps:
  - call: stdlib.db.update
    args:
      table: "{{ table }}"
      set: "{{ set }}"
      where: "{{ where }}"

metadata:
  tags: ["database", "sql"]
  input_types:
    table: string
    set: object
    where: object
  output_types:
    updated: integer
  side_effects: ["write"]
  safety_level: "high"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "impure"
  prerequisites: ["stdlib.db.connect"]
---
