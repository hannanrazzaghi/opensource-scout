from pathlib import Path

from opensource_scout.domain.enums import ValidationStatus
from opensource_scout.workflows.implementation import validate_contribution


async def test_passing_command_is_marked_passed(tmp_path: Path) -> None:
    results = await validate_contribution(tmp_path, {"ok": ("echo", "hi")}, contribution_id="c1")
    assert results[0].status == ValidationStatus.PASSED
    assert results[0].exit_code == 0


async def test_failing_command_is_marked_failed(tmp_path: Path) -> None:
    results = await validate_contribution(tmp_path, {"broken": ("false",)}, contribution_id="c1")
    assert results[0].status == ValidationStatus.FAILED


async def test_missing_executable_is_marked_unavailable(tmp_path: Path) -> None:
    results = await validate_contribution(
        tmp_path, {"missing": ("this-does-not-exist-xyz",)}, contribution_id="c1"
    )
    assert results[0].status == ValidationStatus.UNAVAILABLE
    assert results[0].command.startswith("missing:")


async def test_each_result_names_its_command(tmp_path: Path) -> None:
    results = await validate_contribution(
        tmp_path,
        {"test": ("echo", "a"), "lint": ("echo", "b")},
        contribution_id="c1",
    )
    names = {r.command.split(":")[0] for r in results}
    assert names == {"test", "lint"}


async def test_no_commands_returns_empty_list(tmp_path: Path) -> None:
    results = await validate_contribution(tmp_path, {}, contribution_id="c1")
    assert results == []
