from pathlib import Path

from main import _load_llm_alias_map


def test_load_llm_alias_map_reads_default_and_models(tmp_path: Path):
    cfg = tmp_path / "llms.yaml"
    cfg.write_text(
        "default: deepseek-chat\n"
        "llms:\n"
        "  deepseek-chat:\n"
        '    model: "deepseek-chat"\n'
        "  deepseek-reasoner:\n"
        '    model: "deepseek-reasoner"\n',
        encoding="utf-8",
    )

    default_alias, alias_to_model = _load_llm_alias_map(cfg)

    assert default_alias == "deepseek-chat"
    assert alias_to_model["deepseek-chat"] == "deepseek-chat"
    assert alias_to_model["deepseek-reasoner"] == "deepseek-reasoner"
