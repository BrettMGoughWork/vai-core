---
name: stdlib.proc.execsafe
description: Execute a command with safety constraints including blocklist and allowed commands

primitives:
  - stdlib.proc.execsafe

inputs:
  command:
    type: string
    required: true
  allowed_commands:
    type: list
    required: false
  timeout:
    type: integer
    required: false
    default: 30
  cwd:
    type: string
    required: false
    default: "."

outputs:
  stdout:
    type: string
  stderr:
    type: string
  returncode:
    type: integer
  success:
    type: boolean

steps:
  - call: stdlib.proc.execsafe
    args:
      command: "{{ command }}"
      allowed_commands: "{{ allowed_commands }}"
      timeout: "{{ timeout }}"
      cwd: "{{ cwd }}"

metadata:
  tags: ["process", "execution", "safety"]
  input_types:
    command: string
    allowed_commands: list
    timeout: integer
    cwd: string
  output_types:
    stdout: string
    stderr: string
    returncode: integer
    success: boolean
  side_effects: ["process_spawn"]
  safety_level: "medium"
  cost_estimate:
    latency: 5
    resources: "medium"
  determinism: "impure"
  prerequisites: []
---
