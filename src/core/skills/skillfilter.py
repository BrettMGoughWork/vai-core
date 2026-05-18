from src.skills.skill import Skill
from src.skills.skillmetadata import SkillMetadata


class SkillFilter:
    """
    Minimal deterministic skill filtering based on metadata.
    Reduces the full skill registry to a candidate set.
    """

    def filter(self, skills: list[Skill], user_message: str) -> list[Skill]:
        """
        Filter skills based on metadata and user message.
        
        Args:
            skills: List of skills to filter.
            user_message: The user's input message.
        
        Returns:
            Filtered list of candidate skills.
        """
        candidates = []
        
        # Extract domain keywords from user message
        message_lower = user_message.lower()
        
        for skill in skills:
            # Domain match: keep skills whose metadata.domains overlap with the message
            if skill.metadata.domains:
                domain_match = any(
                    domain.lower() in message_lower
                    for domain in skill.metadata.domains
                )
                if not domain_match:
                    continue
            
            # Safety: exclude skills with incompatible safety_tags (assume none for now)
            # Placeholder: all skills are considered safe
            
            # Input compatibility: placeholder check (return all for now)
            # Placeholder: all skills are considered compatible
            
            candidates.append(skill)
        
        return candidates
