# LINE Message Categorizer

An AI-assisted Python experiment for sorting messages from LINE chat text exports using editable keyword rules. It imports multiple chats, stores them in a local SQLite database, and offers a desktop browser and CSV export. The import and categorization workflow runs locally and needs no API key.

**Project status** This is a snapshot of a personal experiment and is no longer actively maintained. It is an independent project and is unaffiliated with LINE.

## Try it on Windows

Use Python 3.10 or later. The desktop interface also needs Tkinter. The export importer, keyword rules, and CLI use only the Python standard library.

    python main.py --mode demo
    python main.py --mode import examples/sample_chat.txt
    python main.py --mode status
    python main.py --mode export

The demo displays synthetic classification results without writing a database. The example export also contains fictional messages and is safe to import. To open the desktop interface, run `python main.py`.

## Import your own exports

In LINE, open a chat and use **Save chat / トークを保存**. Select the exported text file in the desktop app, or pass its path to `python main.py --mode import`. For Windows space-separated exports, retain the original filename so the app can use it as a chat label if the export omits one. For participants the parser cannot identify, add exact display names under `sender_names` in the local settings and reimport.

Open **Category rules** in the desktop app to edit rules, or copy `settings.example.json` to `settings.json` and edit that copy. The app falls back to the example settings on first run and writes rule changes to `settings.json`. You can also assign a category to an entire chat, overriding the keyword rules.

Use **Watch import folder** in the desktop app or `python main.py --mode watch` to import saved exports from `data/imports/` as they change. The watcher reads exported files from disk. Save a fresh export to import newer messages.

## Local data and limitations

- The SQLite database, exports, and desktop-reader diagnostics can contain message text and sender names. Keep real chat exports under `data/` or outside the repository. Git ignores `data/`, local settings, and common export files. A real export under a different name can still be staged accidentally.
- Imports support UTF-8, UTF-16 with a byte-order mark, and CP932, with support for tab-separated and Windows space-separated exports. Ambiguous numeric dates default to month/day/year and can be configured.
- Reimports use chat labels, timestamps, sender information, and message content to recognize repeats. Changes to chat names, edited messages, and partial exports can affect that matching. Imported messages stay in the local database even if later removed from LINE.
- Keyword classification is approximate. Ties are marked for review and short messages often have too little context for a useful classification. Media is represented only by any text placeholders in the export.

## Legacy desktop reader

The experimental `inspect` and `collect` modes are retained as historical code. They require Windows, a running LINE desktop client, `python -m pip install -r requirements.txt`, and local UI Automation configuration. The reader was designed around one open chat and may fail with other LINE versions. Use the text export workflow for normal use.

## Tests

    python -m unittest -v

The tests use synthetic messages and temporary databases.
