from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "extension"


def test_macos_installer_uses_stable_application_support_copy():
    installer = (ROOT / "install_native_host.sh").read_text()

    assert "Library/Application Support/AI Workflow Bridge" in installer
    assert 'cp -R "$SOURCE_HOST_DIR" "$INSTALLED_HOST_DIR"' in installer
    assert "com.apple.quarantine" in installer
    assert 'PYTHON_BIN="$(find_python || true)"' in installer
    assert "Python 3.11+ is required" in installer
    assert '"$INSTALLED_LAUNCHER"' in installer


def test_native_host_is_ready_only_after_real_message():
    background = (EXT / "background.js").read_text()

    start = background.index("function connectNative()")
    end = background.index("function scheduleReconnect()")
    connect_block = background[start:end]

    assert "nativeReady = true" not in connect_block
    assert "markNativeReady(message);" in background
    assert "NATIVE_HANDSHAKE_TIMEOUT_MS = 8000" in background
    assert (
        "NATIVE_RECONNECT_DELAYS_MS = "
        "[2500, 5000, 10000, 20000, 30000]"
    ) in background
    assert "connecting: true" in background


def test_sidepanel_has_connecting_host_state():
    sidepanel = (EXT / "sidepanel.js").read_text()

    assert 'event.connecting' in sidepanel
    assert '"CONNECTING"' in sidepanel
