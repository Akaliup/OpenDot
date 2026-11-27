import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "commerceops"
BANNED = ("langgraph", "langchain", "openai", "anthropic", "pgvector")


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return found


def test_service_does_not_import_agents_or_vector_databases():
    for path in ROOT.rglob("*.py"):
        for name in _imports(path):
            assert not name.startswith(BANNED), f"{path} imports {name}"


def test_engines_stay_free_of_sql_and_floats():
    engine_dir = ROOT / "engines"
    for path in engine_dir.glob("*.py"):
        for name in _imports(path):
            assert not name.startswith(("sqlalchemy", "sqlite3", "fastapi"))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != "float", f"{path} calls float()"
