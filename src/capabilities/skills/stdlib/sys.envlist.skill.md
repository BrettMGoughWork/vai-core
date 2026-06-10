---
name: stdlib.sys.envlist
description: List all environment variables, optionally filtered by prefix

primitives:
  - stdlib.sys.envlist

inputs:
  prefix:
    type: string
    required: false
    default: ""

outputs:
  variables:
    type: object
  count:
    type: number

steps:
  - call: stdlib.sys.envlist
    args:
      prefix: "{{ prefix }}"

metadata:
  tags: ["system", "environment"]
  input_types:
    prefix: string
  output_types:
    variables: object
    count: number
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "impure"
  prerequisites: []
---
