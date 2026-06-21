"""
Context bridge — package delegator conversation into delegate prompt
and inject delegate response back on resume.

Responsibilities
----------------
1. **Build delegate prompt**: Takes the delegating agent's conversation
   history + current user message + deferral prompt and produces a
   single, structured prompt for the delegate agent.
2. **Inject delegate response**: On resume, injects the delegate's
   final response into the delegating agent's conversation history so
   it appears as context for the next turn.

The context bridge is deliberately simple for D1.  Future iterations
may summarise long delegate conversations to prevent context blow-up.
"""

from __future__ import annotations

from typing import Any, Dict, List


class ContextBridge:
    """Builds delegate prompts and injects delegate responses."""

    @staticmethod
    def build_delegate_prompt(
        *,
        delegator_id: str,
        delegator_name: str,
        user_message: str,
        deferral_prompt: str,
        conversation_history: List[Dict[str, Any]] | None = None,
    ) -> str:
        """Build a prompt for the delegate agent.

        Parameters
        ----------
        delegator_id:
            The delegating agent's ID.
        delegator_name:
            Human-readable name of the delegating agent.
        user_message:
            The original user message that triggered the deferral.
        deferral_prompt:
            Instructions from the delegating agent about what to do.
        conversation_history:
            Optional conversation history from the delegating agent.

        Returns
        -------
        str:
            A structured prompt for the delegate agent.
        """
        parts: List[str] = [
            f"[Delegated from {delegator_name} ({delegator_id})]",
            "",
        ]

        if deferral_prompt:
            parts.append(f"Request: {deferral_prompt}")
            parts.append("")

        if conversation_history:
            parts.append("Original conversation context:")
            for turn in conversation_history[-6:]:  # Keep last 6 turns
                role = turn.get("role", "unknown")
                content = turn.get("content", "")
                if content:
                    # Truncate long messages
                    short = content[:500] + ("..." if len(content) > 500 else "")
                    parts.append(f"  [{role}]: {short}")
            parts.append("")

        parts.append(f"Original user request: {user_message}")

        return "\n".join(parts)

    @staticmethod
    def build_delegate_result_context(
        *,
        delegate_id: str,
        delegate_name: str,
        response_text: str,
        success: bool,
    ) -> str:
        """Build a context message to inject back into the delegator.

        Parameters
        ----------
        delegate_id:
            The delegate agent's ID.
        delegate_name:
            Human-readable name of the delegate agent.
        response_text:
            The delegate's final response text.
        success:
            Whether the delegate completed successfully.

        Returns
        -------
        str:
            A context message for the delegating agent's conversation.
        """
        status = "completed successfully" if success else "failed"
        parts: List[str] = [
            f"[Delegate {delegate_name} ({delegate_id}) {status}]",
            "",
            response_text[:2000],  # Truncate very long responses
        ]
        if len(response_text) > 2000:
            parts.append("... [response truncated]")
        return "\n".join(parts)


def build_delegate_prompt(
    *,
    delegator_id: str,
    delegator_name: str,
    user_message: str,
    deferral_prompt: str,
    conversation_history: List[Dict[str, Any]] | None = None,
) -> str:
    """Convenience function — see ``ContextBridge.build_delegate_prompt()``."""
    return ContextBridge.build_delegate_prompt(
        delegator_id=delegator_id,
        delegator_name=delegator_name,
        user_message=user_message,
        deferral_prompt=deferral_prompt,
        conversation_history=conversation_history,
    )
