from pathlib import Path


def test_gitignore_contains_release_safety_rules():
    root = Path(__file__).resolve().parents[2]
    path = root / ".gitignore"
    text = path.read_text(encoding="utf-8")
    assert "```" not in text, ".gitignore must not contain Markdown fences"
    required = [
        ".env",
        ".env.*",
        "!.env.example",
        "*.db",
        "*.sqlite",
        "*.sqlite3",
        "__pycache__/",
        "*.pyc",
        ".pytest_cache/",
        ".venv/",
        "venv/",
        "node_modules/",
        "dist/",
        "backend/data/*",
        "!backend/data/.gitkeep",
        "backups/*",
        "!backups/.gitkeep",
        "imports/*",
        "!imports/.gitkeep",
        "exports/*",
        "!exports/.gitkeep",
        "logs/*",
        "!logs/.gitkeep",
    ]
    missing = [item for item in required if item not in text]
    assert not missing, f"Missing required .gitignore entries: {missing}"
