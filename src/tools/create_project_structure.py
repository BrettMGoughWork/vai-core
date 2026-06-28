"""Tool that creates the project folder structure for a DevSquad sprint."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

PROJECTS_ROOT = Path(os.environ.get("DEVSQUAD_PROJECTS_ROOT", "/projects"))

DIRECTORIES = [
    "src",
    "tests",
    "migrations",
    "artifacts/v1",
]

METADATA_TEMPLATE = {
    "status": "initializing",
    "current_stage": "prd",
    "stages": {
        "prd": {"status": "pending", "started": None, "completed": None},
        "solution": {"status": "pending", "started": None, "completed": None},
        "delivery_plan": {"status": "pending", "started": None, "completed": None},
        "implementation": {"status": "pending", "started": None, "completed": None},
        "review": {"status": "pending", "started": None, "completed": None},
        "acceptance": {"status": "pending", "started": None, "completed": None},
    },
    "version": 1,
}


def execute(project_id: str, title: str = "") -> dict:
    """Create the project directory structure and metadata file."""
    project_dir = PROJECTS_ROOT / project_id

    if project_dir.exists():
        return {"status": "error", "error": f"Project {project_id} already exists"}

    # Create directories
    for dir_path in DIRECTORIES:
        (project_dir / dir_path).mkdir(parents=True, exist_ok=True)

    # Write metadata
    now = datetime.now(timezone.utc).isoformat()
    metadata = {
        **METADATA_TEMPLATE,
        "project_id": project_id,
        "title": title,
        "created_at": now,
        "updated_at": now,
    }
    (project_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    return {
        "status": "success",
        "project_id": project_id,
        "project_dir": str(project_dir),
    }
