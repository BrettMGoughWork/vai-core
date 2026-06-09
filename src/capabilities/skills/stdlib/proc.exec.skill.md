---
name: stdlib.proc.exec
description: Execute a shell command and capture stdout, stderr, and exit code

primitives:
  - stdlib.proc.exec

inputs:
  cmd:
    type: string
    required: true
  timeout:
    type: integer
    required: false

outputs:
  stdout:
    type: string
  stderr:
    type: string
  exit_code:
    type: integer

steps:
  - call: stdlib.proc.exec
    args:
      cmd: "{{ cmd }}"
      timeout: "{{ timeout }}"

metadata:
  tags: ["process", "execution"]
  input_types:
    cmd: string
    timeout: integer
  output_types:
    stdout: string
    stderr: string
    exit_code: integer
  side_effects: ["process_spawn"]
  safety_level: "high"
  cost_estimate:
    latency: 5
    resources: "medium"
  determinism: "impure"
  prerequisites: []
---
