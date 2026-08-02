from pathlib import Path

import pytest

from opensource_scout.execution.command import CommandRejectedError, CommandSpec, run_command


async def test_simple_command_succeeds(tmp_path: Path) -> None:
    result = await run_command(
        CommandSpec(executable="echo", args=("hi",), working_directory=tmp_path)
    )
    assert result.exit_code == 0
    assert "hi" in result.stdout


async def test_nonzero_exit_is_reported_not_raised(tmp_path: Path) -> None:
    result = await run_command(CommandSpec(executable="false", args=(), working_directory=tmp_path))
    assert result.exit_code != 0


@pytest.mark.parametrize("executable", ["sudo", "doas", "su"])
async def test_privileged_executables_are_blocked(tmp_path: Path, executable: str) -> None:
    with pytest.raises(CommandRejectedError):
        await run_command(
            CommandSpec(executable=executable, args=("x",), working_directory=tmp_path)
        )


async def test_ssh_key_path_argument_is_blocked(tmp_path: Path) -> None:
    with pytest.raises(CommandRejectedError):
        await run_command(
            CommandSpec(
                executable="cat", args=("/home/user/.ssh/id_rsa",), working_directory=tmp_path
            )
        )


async def test_aws_credentials_path_argument_is_blocked(tmp_path: Path) -> None:
    with pytest.raises(CommandRejectedError):
        await run_command(
            CommandSpec(
                executable="cat", args=("/home/user/.aws/credentials",), working_directory=tmp_path
            )
        )


async def test_privileged_flag_is_blocked(tmp_path: Path) -> None:
    with pytest.raises(CommandRejectedError):
        await run_command(
            CommandSpec(
                executable="docker", args=("run", "--privileged"), working_directory=tmp_path
            )
        )


async def test_git_force_push_is_blocked(tmp_path: Path) -> None:
    with pytest.raises(CommandRejectedError):
        await run_command(
            CommandSpec(executable="git", args=("push", "--force"), working_directory=tmp_path)
        )


async def test_git_reset_hard_is_blocked(tmp_path: Path) -> None:
    with pytest.raises(CommandRejectedError):
        await run_command(
            CommandSpec(executable="git", args=("reset", "--hard"), working_directory=tmp_path)
        )


async def test_unscoped_recursive_delete_is_blocked(tmp_path: Path) -> None:
    with pytest.raises(CommandRejectedError):
        await run_command(
            CommandSpec(executable="rm", args=("-rf", "/etc"), working_directory=tmp_path)
        )


async def test_recursive_delete_scoped_to_working_directory_is_allowed(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    result = await run_command(
        CommandSpec(executable="rm", args=("-rf", "scratch"), working_directory=tmp_path)
    )
    assert result.exit_code == 0
    assert not scratch.exists()


async def test_command_times_out(tmp_path: Path) -> None:
    result = await run_command(
        CommandSpec(
            executable="sleep", args=("5",), working_directory=tmp_path, timeout_seconds=0.2
        )
    )
    assert result.timed_out is True


async def test_output_is_redacted(tmp_path: Path) -> None:
    secret = "ghp_" + "a" * 36
    result = await run_command(
        CommandSpec(executable="echo", args=(secret,), working_directory=tmp_path)
    )
    assert secret not in result.stdout
