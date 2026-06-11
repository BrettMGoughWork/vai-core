# deadcode_ignore — I6 false positive: helper class, not a test
class ToolPromptBuilder:
    """
    MVP: build DeepSeek system prompt from tool schema.
    """

    @staticmethod
    def build_schema_prompt(schema: dict) -> str:
        lines = [
            "You are a deterministic tool-calling model.",
            "",
            "Your ONLY job is to choose ONE tool from the list below and return a JSON object:",
            '{ "tool": "<tool_name>", "args": { ... } }',
            "",
            "Rules:",
            "- Always choose exactly ONE tool.",
            "- Never return plain text.",
            "- Never explain your reasoning.",
            "- Never plan.",
            "- Never call multiple tools.",
            "- Never invent tools.",
            "- Arguments must match the schema exactly.",
            "",
            "Available tools:"
        ]

        for tool, spec in schema.items():
            lines.append(f"- {tool}: {spec['description']}")
            for arg, meta in spec["args"].items():
                lines.append(f" - {arg}: {meta['type']}")

        lines.append("")
        lines.append("Return ONLY a JSON object. No prose.")

        return "\n".join(lines)