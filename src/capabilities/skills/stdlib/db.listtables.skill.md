---
name: stdlib.db.listtables
description: List all tables in the database

primitives:
  - stdlib.db.listtables

inputs:
  filter:
    type: string
    required: false

outputs:
  tables:
    type: list

steps:
  - call: stdlib.db.listtables
    args: {}

metadata:
  tags: ["database"]
  input_types:
    filter: string
  output_types:
    tables: list
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "impure"
  prerequisites: ["stdlib.db.connect"]
---
