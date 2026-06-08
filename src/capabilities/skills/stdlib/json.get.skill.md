---
name: stdlib.json.get
description: Get a value from a JSON object by key

primitives:
  - stdlib.json.get

inputs:
  obj:
    type: object
    required: true
  key:
    type: string
    required: true

outputs:
  value: any

steps:
  - call: stdlib.json.get
    args:
      obj: "{{ obj }}"
      key: "{{ key }}"

metadata:
  tags: ['json']
  input_types:
    obj: object
    key: string
  output_types:
    value: any
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "pure"
  prerequisites: []
---
