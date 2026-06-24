"""Unit tests for the council YAML loader."""

from pathlib import Path

import pytest
import yaml

from src.agent.council.loader import load_council_definition
from src.domain.council import CouncilDefinition


class TestLoadCouncilDefinition:
    """load_council_definition() parses a single YAML file."""

    def test_load_general_nominal(self, tmp_path: Path) -> None:
        """Minimal 3-member council parses correctly."""
        yaml_path = tmp_path / "general-nominal.yaml"
        yaml_path.write_text(
            yaml.dump({
                "council_id": "general-nominal",
                "name": "General Nominal Council",
                "description": "Universal council for ambiguous decisions.",
                "arbitrator_agent_id": "balanced-adjudicator",
                "member_agent_ids": ["strategist", "critic", "risk-assessor"],
            })
        )
        defn = load_council_definition(yaml_path)

        assert defn.council_id == "general-nominal"
        assert defn.name == "General Nominal Council"
        assert defn.arbitrator_agent_id == "balanced-adjudicator"
        assert defn.member_agent_ids == ("strategist", "critic", "risk-assessor")
        assert defn.max_analysis_tokens == 2000  # default
        assert defn.max_counter_tokens == 1500  # default
        assert defn.require_consensus is False

    def test_load_dev_squad(self, tmp_path: Path) -> None:
        """5-member council loads with correct arbitrator."""
        yaml_path = tmp_path / "dev-squad.yaml"
        yaml_path.write_text(
            yaml.dump({
                "council_id": "dev-squad",
                "name": "Dev Squad Council",
                "arbitrator_agent_id": "tech-lead-adjudicator",
                "member_agent_ids": [
                    "architect",
                    "product-manager",
                    "software-engineer",
                    "quality-analyst",
                    "delivery-lead",
                ],
            })
        )
        defn = load_council_definition(yaml_path)

        assert defn.council_id == "dev-squad"
        assert defn.arbitrator_agent_id == "tech-lead-adjudicator"
        assert len(defn.member_agent_ids) == 5

    def test_missing_required_field(self, tmp_path: Path) -> None:
        """Missing council_id raises ValueError."""
        yaml_path = tmp_path / "bad.yaml"
        yaml_path.write_text(
            yaml.dump({
                "name": "Bad Council",
                "arbitrator_agent_id": "arb",
                "member_agent_ids": ["m1"],
            })
        )
        with pytest.raises(ValueError, match="required field.*council_id"):
            load_council_definition(yaml_path)

    def test_empty_member_list(self, tmp_path: Path) -> None:
        """Empty member_agent_ids raises ValueError."""
        yaml_path = tmp_path / "empty.yaml"
        yaml_path.write_text(
            yaml.dump({
                "council_id": "empty",
                "name": "Empty Council",
                "arbitrator_agent_id": "arb",
                "member_agent_ids": [],
            })
        )
        with pytest.raises(ValueError, match="member_agent_ids must be non-empty"):
            load_council_definition(yaml_path)

    def test_not_a_mapping(self, tmp_path: Path) -> None:
        """YAML that is a list raises ValueError."""
        yaml_path = tmp_path / "list.yaml"
        yaml_path.write_text(yaml.dump(["a", "b", "c"]))
        with pytest.raises(ValueError, match="must be a mapping"):
            load_council_definition(yaml_path)


class TestCouncilsFromDirectory:
    """load_councils_from_directory() scans a directory."""

    def test_skips_bad_files(self, tmp_path: Path) -> None:
        """Directory containing one valid + one invalid file loads the valid one."""
        # Valid
        (tmp_path / "good.yaml").write_text(
            yaml.dump({
                "council_id": "good",
                "name": "Good",
                "arbitrator_agent_id": "arb",
                "member_agent_ids": ["m1"],
            })
        )
        # Invalid (missing council_id)
        (tmp_path / "bad.yaml").write_text(
            yaml.dump({
                "name": "Bad",
                "arbitrator_agent_id": "arb",
                "member_agent_ids": ["m1"],
            })
        )

        from src.agent.council.loader import load_councils_from_directory
        defns = load_councils_from_directory(tmp_path)
        assert len(defns) == 1
        assert defns[0].council_id == "good"

    def test_non_existent_directory(self) -> None:
        """Non-existent directory returns empty list."""
        from src.agent.council.loader import load_councils_from_directory
        defns = load_councils_from_directory("/tmp/non-existent-dir-12345")
        assert defns == []
