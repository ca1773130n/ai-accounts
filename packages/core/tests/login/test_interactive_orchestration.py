"""Unit tests for interactive CLI orchestration helpers.

The full interactive loop (menu detection → prompt → arrow-navigation →
REPL idle → action command → URL → success) is exercised via manual E2E
against the claude CLI. These tests cover the pure parsing helpers +
regex patterns so regressions in Claude's TUI format or success markers
fail fast in CI.
"""

from __future__ import annotations

from ai_accounts_core.login.cli_orchestrator import (
    MenuOption,
    _LOGIN_SUCCESS_RE,
    _URL_IN_OUTPUT_RE,
    parse_menu_options,
)


def test_menu_single_option_with_caret():
    opts = parse_menu_options([" ❯ 1. Dark mode ✔"])
    assert len(opts) == 1
    assert opts[0].number == 1
    assert "Dark mode" in opts[0].label


def test_menu_multiple_options_theme_picker():
    lines = [
        " ❯ 1. Dark mode ✔",
        "   2. Light mode",
        "   3. Dark mode (colorblind-friendly)",
        "   4. Light mode (colorblind-friendly)",
    ]
    opts = parse_menu_options(lines)
    assert len(opts) == 4
    assert [o.number for o in opts] == [1, 2, 3, 4]
    assert opts[0].label.startswith("Dark mode")
    assert opts[3].label.startswith("Light mode")


def test_menu_option_with_description():
    opts = parse_menu_options(["● 3 Max plan · $100/month"])
    assert len(opts) == 1
    assert opts[0].number == 3
    assert opts[0].label == "Max plan"
    assert opts[0].description == "$100/month"


def test_menu_deduplicates_on_redraw():
    # Terminal repaint re-emits the menu. Dedupe by number, keep first.
    lines = [
        " ❯ 1. Dark mode ✔",
        "   2. Light mode",
        " ❯ 1. Dark mode ✔",
        "   2. Light mode",
    ]
    opts = parse_menu_options(lines)
    assert len(opts) == 2
    assert [o.number for o in opts] == [1, 2]


def test_menu_ignores_non_numbered_lines():
    lines = [
        "Welcome to Claude Code!",
        "Choose a theme:",
        " ❯ 1. Dark mode",
        "   2. Light mode",
        "Press Enter to continue",
    ]
    opts = parse_menu_options(lines)
    assert [o.number for o in opts] == [1, 2]


def test_menu_ignores_diff_lines_without_bullet_or_dot():
    # Regression: Claude's theme preview shows diff lines like these. The
    # bullet-less, dot-less form must not parse as menu options or the
    # interactive loop emits a spurious TextPrompt mid-flow.
    lines = [
        "  1  function greet() {",
        "  2 -  console.log(\"Hello, World!\");",
        "  2 +  console.log(\"Hello, Claude!\");",
        "  3  }",
    ]
    assert parse_menu_options(lines) == []


def test_menu_plan_picker_like_claude():
    # Real output from ``claude /login`` on the account-type picker.
    lines = [
        " Claude Code can be used with your Claude subscription",
        "",
        " ❯ 1. Claude account with subscription (Pro, Max, Team, or Enterprise)",
        "   2. Anthropic Console account (API usage billing)",
    ]
    opts = parse_menu_options(lines)
    assert [o.number for o in opts] == [1, 2]
    assert "Claude account" in opts[0].label
    assert "Anthropic Console" in opts[1].label


def test_menu_empty_returns_empty():
    assert parse_menu_options([]) == []
    assert parse_menu_options(["no menu here", "just prose"]) == []


def test_menu_option_dataclass_shape():
    opt = MenuOption(number=1, label="Dark", description=None)
    assert opt.number == 1
    assert opt.label == "Dark"
    assert opt.description is None


def test_login_success_matches_common_phrases():
    phrases = [
        "Successfully authenticated!",
        "You are now logged in as user@example.com",
        "login successful",
        "Login complete.",
        "Signed in with GitHub",
        "Account added",
        "Account connected",
        "Authentication complete",
    ]
    for s in phrases:
        assert _LOGIN_SUCCESS_RE.search(s), f"should match: {s!r}"


def test_login_success_ignores_failure_phrases():
    phrases = [
        "login failed",
        "unable to authenticate",
        "Please run claude /login",
        "error: auth denied",
    ]
    for s in phrases:
        assert not _LOGIN_SUCCESS_RE.search(s), f"should not match: {s!r}"


def test_url_in_output_matches_https_oauth_url():
    m = _URL_IN_OUTPUT_RE.search(
        "Open this URL: https://claude.ai/oauth/authorize?code=abc in your browser."
    )
    assert m is not None
    assert m.group(0) == "https://claude.ai/oauth/authorize?code=abc"


def test_url_in_output_matches_http_localhost():
    m = _URL_IN_OUTPUT_RE.search("callback at http://localhost:54321/cb?state=1 waits")
    assert m is not None
    assert m.group(0) == "http://localhost:54321/cb?state=1"


def test_url_in_output_strips_quotes_and_brackets():
    m = _URL_IN_OUTPUT_RE.search('Visit "https://example.com/auth" now')
    assert m is not None
    assert m.group(0) == "https://example.com/auth"
