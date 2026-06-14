import pytest
from ai_accounts_core.login.cli_orchestrator import (
    CliOrchestrator,
    parse_menu_options,
    strip_ansi,
)


def test_strip_ansi_cursor_positioning():
    assert strip_ansi("hello\x1b[Hworld") == "hello\nworld"
    assert strip_ansi("hello\x1b[5Gworld") == "hello world"


def test_strip_ansi_erase():
    assert strip_ansi("one\x1b[Jtwo") == "one\ntwo"


def test_strip_ansi_csi_sgr():
    assert strip_ansi("\x1b[31mred\x1b[0m") == "red"


def test_parse_menu_options_dotted_form():
    """Original ``❯ 1. label`` shape must keep parsing."""
    lines = [
        "❯ 1. Auto (match terminal)",
        "  2. Dark mode ✔",
        "  3. Light mode",
    ]
    opts = parse_menu_options(lines)
    assert [(o.number, o.label) for o in opts] == [
        (1, "Auto (match terminal)"),
        (2, "Dark mode ✔"),
        (3, "Light mode"),
    ]


def test_parse_menu_options_dotless_with_separator():
    """Claude CLI v2.1.119+ dropped the ``.`` after the digit on the
    login-method menu (``❯ 1 Claude account · Pro, Max, ...``).  The
    parser must still recognise these because we anchor on the ``·``
    separator that distinguishes a menu line from a diff hunk."""
    lines = [
        "❯ 1 Claude account with subscription · Pro, Max, Team, or Enterprise",
        "  2 Anthropic Console account · API usage billing",
        "  3 3rd-party platform · Amazon Bedrock, Microsoft Foundry, or Vertex AI",
    ]
    opts = parse_menu_options(lines)
    assert [(o.number, o.label, o.description) for o in opts] == [
        (1, "Claude account with subscription", "Pro, Max, Team, or Enterprise"),
        (2, "Anthropic Console account", "API usage billing"),
        (3, "3rd-party platform", "Amazon Bedrock, Microsoft Foundry, or Vertex AI"),
    ]


def test_parse_menu_options_does_not_match_diff_hunks():
    """The dotless branch requires a ``·`` separator, so plain
    ``N word`` lines from diffs / code dumps must NOT be parsed as
    options.  Regression guard for the original ``2 - console.log``
    false-positive."""
    lines = [
        '  2 - console.log("Hello")',
        " 1  function foo()",
        "    3 something else without a separator",
    ]
    assert parse_menu_options(lines) == []


def test_parse_menu_options_dedupes_repeats():
    """Menu redraws emit the same option multiple times — keep first.

    A real interactive menu highlights its active row with a selection
    cursor (``❯``); without one ``parse_menu_options`` treats the lines as
    numbered prose and returns nothing (see d600c43), so the dedup case is
    exercised with the cursor present.
    """
    lines = [
        "❯ 1. First label",
        "  1. First label (redraw)",
        "  2. Second label",
    ]
    opts = parse_menu_options(lines)
    assert [(o.number, o.label) for o in opts] == [
        (1, "First label"),
        (2, "Second label"),
    ]


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
