"""Legacy one-chat UIA reader; requires calibration. Main app uses text exports."""
import time
from pathlib import Path
from categorizer import Store, classify_message, new_tail

ROOT = Path(__file__).resolve().parent

def line_window(config):
    from pywinauto import Desktop
    from pywinauto.application import Application
    app = Application(backend="uia").connect(path=config["line_executable"], timeout=5)
    matches = [w for w in Desktop(backend="uia").windows(process=app.process, visible_only=True)
               if w.window_text() == config["window_title"]]
    if len(matches) != 1:
        raise RuntimeError("Expected one configured LINE window. Sign in and check window_title.")
    return matches[0]

def inspect(config):
    target = ROOT / "data" / "line-controls.txt"
    target.parent.mkdir(exist_ok=True)
    line_window(config).print_control_identifiers(depth=8, filename=str(target))
    print("Saved local controls to", target)
    print("Find the unique message-history container ID and set message_container_auto_id.")
    print("The diagnostic can contain private text; keep it local.")

def snapshot(config):
    auto_id = config["message_container_auto_id"].strip()
    if not auto_id:
        raise RuntimeError("Live selector is not configured. Run Inspect LINE after sign-in; see README.md.")
    containers = line_window(config).descendants(auto_id=auto_id)
    if len(containers) != 1:
        raise RuntimeError("Message container not uniquely found. Stop and recalibrate.")
    result = [node.window_text().strip() for node in containers[0].descendants(
        control_type=config["message_control_type"]) if node.is_visible() and node.window_text().strip()]
    if not result:
        raise RuntimeError("No readable message text exposed in this container.")
    return result

def collect(config):
    if not config["chat_label"].strip():
        raise ValueError("Set chat_label for the single chat you will keep open.")
    interval = float(config["poll_seconds"])
    if interval < 1:
        raise ValueError("poll_seconds must be at least 1.")
    previous = snapshot(config)
    store = Store(ROOT / "data" / "messages.sqlite3")
    print("Baseline captured. Watching NEW visible text entries; Ctrl+C to stop.")
    print("Keep the SAME chat open at its newest messages. This is not an all-chat listener.")
    try:
        while True:
            time.sleep(interval)
            current = snapshot(config)
            added = new_tail(previous, current)
            if added is None:
                raise RuntimeError("Message view changed without overlap. Stopped; rebaseline before continuing.")
            for text in added:
                category, keywords = classify_message(text, config["categories"], config["chat_label"], config.get("chat_categories"))
                store.add(config["chat_label"], text, category, keywords)
                print("Saved a visible text entry:", category)
            previous = current
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        store.close()
