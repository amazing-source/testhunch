import os
from pathlib import Path


def test_passes():
    assert 1 + 1 == 2


def test_fails_on_purpose():
    assert "carte" == "grise", "fails on every attempt"


def test_errors_on_purpose():
    raise RuntimeError("errors on every attempt")


def test_flaky_first_attempt():
    # Fails the first time it runs, passes when pytest-rerunfailures reruns it.
    marker = Path(os.environ["FLAKY_STATE_DIR"]) / "attempted"
    if not marker.exists():
        marker.write_text("")
        raise AssertionError("first attempt fails on purpose")
