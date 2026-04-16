import pytest

from ai_accounts_core.login.cli_orchestrator import CliOrchestrator, strip_ansi


def test_strip_ansi_cursor_positioning():
    assert strip_ansi("hello\x1b[Hworld") == "hello\nworld"
    assert strip_ansi("hello\x1b[5Gworld") == "hello world"


def test_strip_ansi_erase():
    assert strip_ansi("one\x1b[Jtwo") == "one\ntwo"


def test_strip_ansi_csi_sgr():
    assert strip_ansi("\x1b[31mred\x1b[0m") == "red"


@pytest.mark.asyncio
async def test_orchestrator_runs_echo_and_captures_output(tmp_path):
    orch = CliOrchestrator(
        argv=["/bin/echo", "hello"],
        env={},
        cwd=tmp_path,
    )
    chunks: list[str] = []
    await orch.start()
    async for chunk in orch.read_output():
        chunks.append(chunk)
    await orch.wait()
    joined = "".join(chunks)
    assert "hello" in joined
    assert orch.exit_code == 0


@pytest.mark.asyncio
async def test_orchestrator_accepts_stdin(tmp_path):
    orch = CliOrchestrator(
        argv=["/bin/sh", "-c", "read x; echo got=$x"],
        env={},
        cwd=tmp_path,
    )
    await orch.start()
    await orch.write(b"world\n")
    buf = ""
    async for chunk in orch.read_output():
        buf += chunk
        if "got=world" in buf:
            break
    await orch.wait()
    assert "got=world" in buf
    assert orch.exit_code == 0


@pytest.mark.asyncio
async def test_orchestrator_terminate(tmp_path):
    import asyncio

    orch = CliOrchestrator(
        argv=["/bin/sh", "-c", "sleep 30"],
        env={},
        cwd=tmp_path,
    )
    await orch.start()
    # Brief pause to let the child exec sleep before SIGTERM lands,
    # otherwise pty.fork() can race on busy systems.
    await asyncio.sleep(0.05)
    await orch.terminate()
    await orch.wait()
    assert orch.exit_code is not None
    assert orch.exit_code != 0
