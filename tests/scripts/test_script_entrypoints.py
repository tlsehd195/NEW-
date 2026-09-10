"""Category: Script Entrypoint Test -- every CLI script under scripts/
must propagate its own main()'s return code as its actual process exit
code.

Health-check finding (Session 36 continued, follow-on from the
"위험도 높은 순으로" external-review remediation pass): a scheduled
check of the "Paper Trading Daily Cycle" GitHub Actions workflow found
its ingestion step's real return code was always 0 -- green -- even on
a run where `scripts/ingest_real_market_data.py`'s own `main()` had
deliberately computed `return 1` for a non-SUCCESS ingestion status.
The cause: the file's `if __name__ == "__main__":` guard called
`main()` bare, discarding that return value entirely (Python defaults
to process exit 0 unless something explicitly raises `SystemExit`
otherwise). A real `PARTIAL_SUCCESS` ingestion was therefore invisible
in CI -- found only by reading a live workflow run's raw logs, since
this repository's test suite never makes real network calls and so
never exercises this script's `__main__` block end to end. Every
sibling script (`run_paper_trading_cycle.py`, the other `ingest_*.py`
scripts) already uses `sys.exit(main())` / `raise SystemExit(main())`;
this one file was the sole outlier, now fixed to match.

This is a static, AST-based scan (no subprocess, no network) precisely
so it covers every script under scripts/, not just the one instance
this session happened to find -- the same class of bug in any other
script would fail this test too.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"


def _script_paths() -> list[Path]:
    return sorted(_SCRIPTS_DIR.glob("*.py"))


def _calls_main(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "main"


def _is_main_guard(test: ast.expr) -> bool:
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value == "__main__"
    )


def _guard_propagates_mains_exit_code(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if not (isinstance(node, ast.If) and _is_main_guard(node.test)):
            continue
        for stmt in node.body:
            # sys.exit(main()) / os._exit(main()) style
            if (
                isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Call)
                and isinstance(stmt.value.func, ast.Attribute)
                and stmt.value.func.attr == "exit"
                and stmt.value.args
                and _calls_main(stmt.value.args[0])
            ):
                return True
            # raise SystemExit(main())
            if (
                isinstance(stmt, ast.Raise)
                and isinstance(stmt.exc, ast.Call)
                and isinstance(stmt.exc.func, ast.Name)
                and stmt.exc.func.id == "SystemExit"
                and stmt.exc.args
                and _calls_main(stmt.exc.args[0])
            ):
                return True
        return False  # found the __main__ guard but no compliant exit call inside it
    return False  # no `if __name__ == "__main__":` guard at all


class TestEveryScriptPropagatesMainsExitCode:
    @pytest.mark.parametrize("path", _script_paths(), ids=lambda p: p.name)
    def test_main_return_code_reaches_the_process_exit_code(self, path: Path) -> None:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        has_main_function = any(
            isinstance(node, ast.FunctionDef) and node.name == "main" for node in ast.iter_child_nodes(tree)
        )
        if not has_main_function:
            pytest.skip(f"{path.name} has no module-level main() to propagate")
        assert _guard_propagates_mains_exit_code(tree), (
            f"{path.name}'s `if __name__ == '__main__':` guard must call "
            f"`sys.exit(main())` or `raise SystemExit(main())` -- a bare `main()` "
            f"call silently discards a non-zero return code, making a real CI/cron "
            f"failure show as a green checkmark (see this file's module docstring)"
        )
