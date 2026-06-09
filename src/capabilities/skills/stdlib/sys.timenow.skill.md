---
name: stdlib.sys.timenow
description: Get the current system time in various formats

primitives:
  - stdlib.sys.timenow

inputs:
  format:
    type: string
    required: false
  timezone:
    type: string
    required: false

outputs:
  timestamp:
    type: number
  datetime:
    type: string
  formatted:
    type: string
  timezone:
    type: string

steps:
  - call: stdlib.sys.timenow
    args:
      format: "{{ format }}"
      timezone: "{{ timezone }}"

metadata:
  tags: ["system", "time"]
  input_types:
    format: string
    timezone: string
  output_types:
    timestamp: number
    datetime: string
    formatted: string
    timezone: string
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "impure"
  prerequisites: []
---
