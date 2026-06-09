---
name: stdlib.proc.ps
description: List running processes with optional name filter and limit

primitives:
  - stdlib.proc.ps

inputs:
  name_filter:
    type: string
    required: false
  limit:
    type: integer
    required: false

outputs:
  processes:
    type: list
  count:
    type: integer

steps:
  - call: stdlib.proc.ps
    args:
      name_filter: "{{ name_filter }}"
      limit: "{{ limit }}"

metadata:
  tags: ["process", "system"]
  input_types:
    name_filter: string
    limit: integer
  output_types:
    processes: list
    count: integer
  side_effects: ["system_query"]
  safety_level: "low"
  cost_estimate:
    latency: 10
    resources: "medium"
  determinism: "impure"
  prerequisites: []
---
