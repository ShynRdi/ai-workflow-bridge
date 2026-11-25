"""Keep pytest completely separate from a user's running Bridge."""
import os
import tempfile

_test_home = None
_previous_home = None


def pytest_sessionstart(session):
    global _test_home, _previous_home
    # Runs before test collection imports native_host/config.py.
    _previous_home = os.environ.get("AI_WORKFLOW_BRIDGE_HOME")
    _test_home = tempfile.TemporaryDirectory(prefix="awb-pytest-")
    os.environ["AI_WORKFLOW_BRIDGE_HOME"] = _test_home.name


def pytest_sessionfinish(session, exitstatus):
    if _previous_home is None:
        os.environ.pop("AI_WORKFLOW_BRIDGE_HOME", None)
    else:
        os.environ["AI_WORKFLOW_BRIDGE_HOME"] = _previous_home
    if _test_home is not None:
        _test_home.cleanup()
