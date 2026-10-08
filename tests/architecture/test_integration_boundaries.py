import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# Every directory holding application code, which must reach external services only via providers.
SCANNED_ROOTS = (REPO_ROOT / "app", REPO_ROOT / "ingestion")
# Prefixes, so distribution-specific packages (langchain_aws, llama_index_core, ...) are caught too.
FORBIDDEN_MODULE_PREFIXES = ("boto3", "botocore", "langchain", "llama_index")
# `ingestion/` is a standalone entry point, not a caller of the API. It builds its providers once in
# `main()` and passes them down explicitly, which is what keeps a batch job off a provider cache —
# and a Bedrock call ceiling — sized for a 30 s Lambda invocation.
FORBIDDEN_IMPORT_PREFIXES_IN_INGESTION = ("app.api",)


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
    for source_path in sorted(path for root in SCANNED_ROOTS for path in root.rglob("*.py")):
        if _is_allowed_provider_file(source_path):
            continue
        forbidden_imports = {
            module
            for module in _imported_top_level_modules(source_path)
            if module.startswith(FORBIDDEN_MODULE_PREFIXES)
        }
        if forbidden_imports:
            violations.append(f"{source_path.relative_to(REPO_ROOT)}: imports {sorted(forbidden_imports)}")

    assert not violations, "Direct SDK/framework imports found outside *_provider.py files:\n" + "\n".join(
        violations
    )


def _imported_modules(source_path: Path) -> set[str]:
    """Every imported module as its full dotted path, unlike the first-segment-only helper above.

    `from app.api import deps` and `from app.api.deps import get_embedder` both have to be caught,
    and the first segment of either is just "app".
    """
    tree = ast.parse(source_path.read_text(), filename=str(source_path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_ingestion_does_not_resolve_providers_through_the_api_dependency_layer():
    """A gate, because no existing test would notice if ingestion started using the API's deps.

    The ten tests in `tests/ingestion/test_ingest.py` all drive `ingest_document` / `ingest_all`
    with injected providers and never call `main()`, so the import is the only observable seam —
    and sharing the request path's cached, Lambda-sized providers with a long batch job is exactly
    the kind of coupling that is invisible until a large ingest behaves oddly.
    """
    violations = []
    for source_path in sorted((REPO_ROOT / "ingestion").rglob("*.py")):
        forbidden_imports = {
            module
            for module in _imported_modules(source_path)
            if module.startswith(FORBIDDEN_IMPORT_PREFIXES_IN_INGESTION)
        }
        if forbidden_imports:
            violations.append(f"{source_path.relative_to(REPO_ROOT)}: imports {sorted(forbidden_imports)}")

    assert not violations, (
        "ingestion/ must build its own providers at its entry point rather than resolving them "
        "through the API dependency layer:\n" + "\n".join(violations)
    )
