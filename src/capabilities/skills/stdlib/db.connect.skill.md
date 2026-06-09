---
name: stdlib.db.connect
description: Connect to a SQLite database file

primitives:
  - stdlib.db.connect

inputs:
  path:
    type: string
    required: true

outputs:
  connected:
    type: boolean
  path:
    type: string

steps:
  - call: stdlib.db.connect
    args:
      path: "{{ path }}"

metadata:
  tags: ["database", "sqlite"]
  input_types:
    path: string
  output_types:
    connected: boolean
    path: string
  side_effects: ["state"]
  safety_level: "medium"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "impure"
  prerequisites: []
---
