import shutil

import pytest

from ai_accounts_core.login.cli_orchestrator import CliOrchestrator


@pytest.mark.asyncio
async def test_real_echo_via_orchestrator(tmp_path):
    """Verify the PTY path works with a real subprocess."""
    orch = CliOrchestrator(argv=["/bin/echo", "hello-from-pty"], env={}, cwd=tmp_path)
    await orch.start()
    output = []
    async for chunk in orch.read_output():
        output.append(chunk)
    exit_code = await orch.wait()
    assert exit_code == 0
    assert any("hello-from-pty" in c for c in output)


@pytest.mark.asyncio
async def test_real_interactive_cat(tmp_path):
    """Verify write + read works with a real interactive process."""
    orch = CliOrchestrator(argv=["/bin/cat"], env={}, cwd=tmp_path)
    await orch.start()
    await orch.write(b"ping\n")
    chunks = []
    async for chunk in orch.read_output():
        chunks.append(chunk)
        if "ping" in chunk:
            break
    await orch.terminate()
    await orch.wait()
    assert any("ping" in c for c in chunks)


@pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not installed")
@pytest.mark.asyncio
async def test_real_claude_version(tmp_path):
    """Verify claude --version runs successfully (if installed)."""
    orch = CliOrchestrator(argv=["claude", "--version"], env={}, cwd=tmp_path)
    await orch.start()
    output = []
    async for chunk in orch.read_output():
        output.append(chunk)
    exit_code = await orch.wait()
    assert exit_code == 0
    joined = "".join(output).lower()
    assert "claude" in joined or "v" in joined
