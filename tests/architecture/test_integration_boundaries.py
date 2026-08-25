import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2] / "app"
# Prefixes, so distribution-specific packages (langchain_aws, llama_index_core, ...) are caught too.
FORBIDDEN_MODULE_PREFIXES = ("boto3", "botocore", "langchain", "llama_index")


def _imported_top_level_modules(source_path: Path) -> set[str]:
    tree = ast.parse(source_path.read_text(), filename=str(source_path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def _is_allowed_provider_file(path: Path) -> bool:
    return path.name.endswith("_provider.py") and path.parent.parent.name == "integrations"


def test_no_module_outside_provider_files_imports_a_raw_sdk_or_framework():
    violations = []
    for source_path in APP_ROOT.rglob("*.py"):
        if _is_allowed_provider_file(source_path):
            continue
        forbidden_imports = {
            module
            for module in _imported_top_level_modules(source_path)
            if module.startswith(FORBIDDEN_MODULE_PREFIXES)
        }
        if forbidden_imports:
            violations.append(f"{source_path.relative_to(APP_ROOT)}: imports {sorted(forbidden_imports)}")

    assert not violations, "Direct SDK/framework imports found outside *_provider.py files:\n" + "\n".join(
        violations
    )
