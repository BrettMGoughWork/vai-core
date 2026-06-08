---
name: stdlib.json.set
description: Set a value on a JSON object by key

primitives:
  - stdlib.json.set

inputs:
  obj:
    type: object
    required: true
  key:
    type: string
    required: true
  value:
    type: any
    required: true

outputs:
  obj: object

steps:
  - call: stdlib.json.set
    args:
      obj: "{{ obj }}"
      key: "{{ key }}"
      value: "{{ value }}"

metadata:
  tags: ['json']
  input_types:
    obj: object
    key: string
    value: any
  output_types:
    obj: object
  side_effects: ["none"]
  safety_level: "low"
  cost_estimate:
    latency: 1
    resources: "low"
  determinism: "pure"
  prerequisites: []
---
