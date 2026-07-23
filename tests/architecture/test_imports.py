import subprocess
import sys
from pathlib import Path


def test_import_linter_contracts_pass():
    lint_imports = Path(sys.executable).with_name("lint-imports.exe")
    if not lint_imports.exists():
        lint_imports = Path(sys.executable).with_name("lint-imports")

    result = subprocess.run(
        [str(lint_imports)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
