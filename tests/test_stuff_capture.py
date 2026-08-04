from utils.stuff_capture import CHROMIUM_ARGS, _format_capture_error, _has_blocked_marker


def test_has_blocked_marker_detects_cloudflare_message():
    assert _has_blocked_marker("", "Sorry, you have been blocked")


def test_has_blocked_marker_ignores_regular_page_text():
    assert not _has_blocked_marker("Dofusbook", "Stuff page loaded")


def test_format_capture_error_hides_playwright_timeout_details():
    reason = _format_capture_error(TimeoutError("Locator.inner_text: Timeout exceeded"))

    assert reason == "Capture navigateur impossible: Dofusbook n'a pas repondu a temps."


def test_chromium_args_keep_capture_lightweight():
    assert "--disable-dev-shm-usage" in CHROMIUM_ARGS
    assert "--disable-background-networking" in CHROMIUM_ARGS
    assert "--disable-extensions" in CHROMIUM_ARGS
    assert "--disable-gpu" in CHROMIUM_ARGS
