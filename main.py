"""LINE message categorizer: import multiple chats and watch exported files locally."""
import argparse
import sys
import time
from pathlib import Path
from categorizer import Store, classify
from configuration import DATABASE, IMPORTS, settings
from line_import import import_file


def import_paths(paths, config):
    store = Store(DATABASE)
    failures = 0
    try:
        for path in paths:
            try:
                chat, total, added, unresolved = import_file(store, path, config)
                print(f"{Path(path).name}: {chat}: {total} parsed, {added} added, {total-added} already saved")
                if unresolved:
                    print(f"  {unresolved} sender names unresolved; full lines preserved. Add sender_names in Category rules and reimport.")
            except (ValueError, OSError) as error:
                failures += 1
                print(f"Could not import {Path(path).name}: {error}", file=sys.stderr)
    finally:
        store.close()
    return failures


def watch(config):
    IMPORTS.mkdir(parents=True, exist_ok=True)
    seen, candidates = {}, {}
    print(f"Watching exported .txt files in {IMPORTS}. Ctrl+C to stop.", flush=True)
    print("This watches files; it does not fetch messages from LINE.", flush=True)
    try:
        while True:
            ready = []
            for path in IMPORTS.glob("*.txt"):
                try:
                    stat = path.stat()
                    signature = (stat.st_mtime_ns, stat.st_size)
                    if seen.get(path) != signature:
                        if candidates.get(path) == signature:
                            ready.append(path)
                            seen[path] = signature
                        candidates[path] = signature
                except OSError:
                    continue
            if ready:
                import_paths(ready, settings())
            time.sleep(config["poll_seconds"])
    except KeyboardInterrupt:
        print("Stopped.")


def demo():
    config = settings()
    for text in ("Project meeting tomorrow", "課題を提出", "Weekend picnic", "Hello"):
        print(f"{text} -> {classify(text, config['categories'])[0]}")
    print("Demo only: no sample messages were saved.")


def main():
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("launcher", "import", "watch", "export", "demo", "status", "inspect", "collect"), default="launcher")
    parser.add_argument("files", nargs="*", type=Path, help="LINE Save chat .txt files for --mode import")
    args = parser.parse_args()
    try:
        if args.mode == "launcher":
            from app import launch
            launch()
        elif args.mode == "export":
            store = Store(DATABASE)
            try:
                print("CSV saved to", store.export_csv())
            finally:
                store.close()
        else:
            config = settings()
            if args.mode == "import":
                paths = args.files or sorted(IMPORTS.glob("*.txt"))
                if not paths:
                    raise ValueError(f"No exports selected. Save LINE .txt exports in {IMPORTS}")
                return 1 if import_paths(paths, config) else 0
            elif args.mode == "watch":
                watch(config)
            elif args.mode == "demo":
                demo()
            elif args.mode == "status":
                store = Store(DATABASE)
                try:
                    print(f"Ready: {len(config['categories'])} categories; {len(store.chats())} chats; {sum(store.counts().values())} saved messages")
                    print("Mode: multi-chat export import (no personal-account live API)")
                    print("Import folder:", IMPORTS)
                finally:
                    store.close()
            else:
                from desktop_reader import inspect, collect
                if args.mode == "collect" and not config.get("message_container_auto_id", "").strip():
                    raise ValueError("The legacy single-chat reader is not calibrated. Use the export importer.")
                {"inspect": inspect, "collect": collect}[args.mode](config)
        return 0
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
