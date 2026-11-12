"""Uji impor: jalur scan tidak boleh mengimpor kode eksperimen (AC-3).

Jalur scan: scan, dqprofile, uncertainty, recovery, dan pemuat artefak (`artifact`, dipisah dari
kode pelatihan `metamodel` di Phase 3). Kode eksperimen: corpus, corrupt, evaluate.
"""

import ast
import subprocess
import sys
from pathlib import Path

SCAN_PATH = ["scan", "dqprofile", "uncertainty", "recovery", "artifact"]
# `experiment` mengimpor corpus dan corrupt, sehingga jalur scan juga tidak boleh mengimpornya.
# `metamodel` adalah kode pelatihan; jalur scan hanya memuat artefak (AC-4, execution-plan Phase 3).
EXPERIMENT = ["corpus", "corrupt", "evaluate", "experiment", "metamodel"]
PACKAGE_DIR = Path(__file__).resolve().parent.parent / "ceteris"


def _imported_names(path: Path) -> set[str]:
    """Kumpulkan nama modul `ceteris.*` yang diimpor, termasuk impor di dalam fungsi."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = ("ceteris." * (node.level > 0)) + (node.module or "")
            names.add(base)
            names.update(f"{base}.{alias.name}".strip(".") for alias in node.names)
    return names


def test_ac3_scan_path_source_has_no_experiment_imports() -> None:
    forbidden = {f"ceteris.{name}" for name in EXPERIMENT}
    for module in SCAN_PATH:
        found = _imported_names(PACKAGE_DIR / f"{module}.py") & forbidden
        assert not found, f"ceteris.{module} mengimpor kode eksperimen: {sorted(found)}"


def test_ac3_scan_path_runtime_does_not_load_experiment_modules() -> None:
    """Menangkap impor transitif yang lolos dari pemeriksaan sumber."""
    code = (
        "import sys\n"
        f"for m in {SCAN_PATH!r}:\n"
        "    __import__(f'ceteris.{m}')\n"
        f"loaded = [m for m in {EXPERIMENT!r} if f'ceteris.{{m}}' in sys.modules]\n"
        "print(','.join(loaded))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "", f"modul eksperimen termuat: {result.stdout.strip()}"
