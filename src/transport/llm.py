import os
import json
from dotenv import load_dotenv
from openai import OpenAI

SYSTEM_PROMPT = """
You are a deterministic tool-calling model.

Your ONLY job is to choose ONE tool from the provided list and return a JSON object:
{
  "tool": "<tool_name>",
  "args": { ... }
}

Rules:
- Always choose exactly ONE tool.
- Never return plain text.
- Never explain your reasoning.
- Never plan.
- Never call multiple tools.
- Never call a tool recursively.
- Never invent tools.
- Arguments must match the schema exactly.
- If the user asks something you cannot do, call the "echo" tool with the user's text.

Available tools:
1. echo(text: str)
   - Repeat text back.

2. add(a: float, b: float)
   - Return the sum of two numbers.

Return ONLY a JSON object. No prose.
"""

class DeepSeekLLM:
    def __init__(self, model="deepseek-chat", schema_prompt=None):
        # Ensure local .env values are loaded in development/dev VM runs.
        load_dotenv(override=False)

        api_key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
        base_url = (os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1").strip()

        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is missing/empty (check your .env and how you load it).")

        # Optional: guard against the exact bug you're seeing
        if "\r" in api_key or "\n" in api_key:
            raise RuntimeError(f"DEEPSEEK_API_KEY contains newline characters: {api_key!r}")

        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self.model = model
        self.schema_prompt = schema_prompt

    def complete(self, user_input: str) -> dict:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.schema_prompt},
                {"role": "user", "content": user_input},
            ],
            temperature=0,
            max_tokens=200,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        return json.loads(content)