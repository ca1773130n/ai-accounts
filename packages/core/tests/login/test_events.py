import msgspec

from ai_accounts_core.login.events import (
    LoginComplete,
    LoginEvent,
    LoginFailed,
    ProgressUpdate,
    PromptAnswer,
    StdoutChunk,
    TextPrompt,
    UrlPrompt,
)


def test_url_prompt_roundtrip():
    evt = UrlPrompt(prompt_id="p-1", url="https://x.test/auth", user_code="ABCD-1234")
    data = msgspec.json.encode(evt)
    decoded = msgspec.json.decode(data, type=LoginEvent)
    assert isinstance(decoded, UrlPrompt)
    assert decoded.url == "https://x.test/auth"
    assert decoded.user_code == "ABCD-1234"


def test_text_prompt_hidden_flag():
    evt = TextPrompt(prompt_id="p-2", prompt="API key:", hidden=True)
    assert evt.hidden is True


def test_stdout_chunk_contains_ansi_stripped_text():
    evt = StdoutChunk(text="hello world")
    assert evt.text == "hello world"


def test_progress_update_optional_percent():
    a = ProgressUpdate(label="polling")
    b = ProgressUpdate(label="verifying", percent=50)
    assert a.percent is None
    assert b.percent == 50


def test_login_complete_shape():
    evt = LoginComplete(account_id="bkd-abc123", backend_status="validating")
    assert evt.account_id == "bkd-abc123"


def test_login_failed_shape():
    evt = LoginFailed(code="cli_exit_nonzero", message="claude exited with 2")
    assert evt.code == "cli_exit_nonzero"


def test_prompt_answer_text():
    ans = PromptAnswer(prompt_id="p-2", answer="sk-ant-xxx")
    assert ans.answer == "sk-ant-xxx"
