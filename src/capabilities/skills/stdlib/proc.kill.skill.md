---
name: stdlib.proc.kill
description: Kill a running process by its PID

primitives:
  - stdlib.proc.kill

inputs:
  pid:
    type: integer
    required: true
  signal:
    type: integer
    required: false

outputs:
  pid:
    type: integer
  signal:
    type: integer
  signal_name:
    type: string

steps:
  - call: stdlib.proc.kill
    args:
      pid: "{{ pid }}"
      signal: "{{ signal }}"

metadata:
  tags: ["process", "execution"]
  input_types:
    pid: integer
    signal: integer
  output_types:
    pid: integer
    signal: integer
    signal_name: string
  side_effects: ["process_kill"]
  safety_level: "high"
  cost_estimate:
    latency: 2
    resources: "low"
  determinism: "impure"
  prerequisites: []
---
