"""Local keyword categorization and conservative snapshot comparison."""
import csv
import hashlib
import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

def classify(text, rules):
    normalize = lambda value: unicodedata.normalize("NFKC", value).casefold()
    text = normalize(text)
    scores = []
    for name, words in rules.items():
        hits = []
        seen = set()
        for raw in words:
            word = normalize(raw)
            if not word or word in seen:
                continue
            seen.add(word)
            pattern = r"(?<!\w)" + re.escape(word) + r"(?!\w)" if word.isascii() else re.escape(word)
            if re.search(pattern, text):
                hits.append(raw)
        if hits:
            scores.append((name, hits))
    if any(name.startswith("Work / ") for name, _ in scores):
        scores = [(name, hits) for name, hits in scores if name != "Work"]
    if not scores:
        return "Uncategorized", []
    best = max(len(hits) for _, hits in scores)
    winners = [(name, hits) for name, hits in scores if len(hits) == best]
    return winners[0] if len(winners) == 1 else ("Needs review", [h for _, hits in winners for h in hits])

def classify_message(text, rules, chat="", chat_categories=None):
    category = (chat_categories or {}).get(chat)
    if category in rules:
        return category, []
    return classify(text, rules)


def new_tail(previous, current):
    """None means an ambiguous change: stop rather than mislabel old history."""
    if previous == current:
        return []
    if not previous or not current:
        return None
    for overlap in range(min(len(previous), len(current)), 0, -1):
        if previous[-overlap:] == current[:overlap]:
            return current[overlap:]
    return None

class Store:
    def __init__(self, path):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.execute("""CREATE TABLE IF NOT EXISTS entries(
            id INTEGER PRIMARY KEY, observed_at_utc TEXT NOT NULL,
            chat_label TEXT NOT NULL, text TEXT NOT NULL,
            category TEXT NOT NULL, matched_keywords TEXT NOT NULL)""")
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(entries)")}
        for column in ("sent_at", "sender", "source_file", "import_key"):
            if column not in columns:
                self.db.execute(f"ALTER TABLE entries ADD COLUMN {column} TEXT")
        self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS unique_import ON entries(import_key) WHERE import_key IS NOT NULL")
        self.db.commit()

    def add(self, chat, text, category, keywords):
        self.db.execute("INSERT INTO entries(observed_at_utc,chat_label,text,category,matched_keywords) VALUES(?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), chat, text, category,
             json.dumps(keywords, ensure_ascii=False)))
        self.db.commit()

    def export_csv(self):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target = self.path.parent / f"messages-{stamp}.csv"
        cursor = self.db.execute("SELECT * FROM entries ORDER BY id")
        with target.open("x", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow([column[0] for column in cursor.description])
            for row in cursor:
                writer.writerow(["'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v for v in row])
        return target

    def close(self):
        self.db.close()

    def import_messages(self, chat, messages, rules, source_file, chat_categories=None):
        """Deduplicate re-exports while preserving identical repeated messages."""
        occurrences = {}
        inserted = 0
        with self.db:
            for message in messages:
                identity = (chat, message.sent_at, message.raw_identity) if message.raw_identity is not None else (chat, message.sent_at, message.sender, message.text)
                occurrences[identity] = occurrences.get(identity, 0) + 1
                key = hashlib.sha256(json.dumps(
                    (*identity, occurrences[identity]), ensure_ascii=False).encode("utf-8")).hexdigest()
                category, keywords = classify_message(message.text, rules, chat, chat_categories)
                cursor = self.db.execute("""INSERT OR IGNORE INTO entries
                    (observed_at_utc,chat_label,text,category,matched_keywords,sent_at,sender,source_file,import_key)
                    VALUES(?,?,?,?,?,?,?,?,?)""", (
                    datetime.now(timezone.utc).isoformat(), chat, message.text, category,
                    json.dumps(keywords, ensure_ascii=False), message.sent_at, message.sender,
                    str(source_file), key))
                inserted += cursor.rowcount
                if not cursor.rowcount:
                    # A later import can resolve a previously unknown space-delimited sender.
                    self.db.execute("""UPDATE entries SET sender=?,text=?,category=?,matched_keywords=?,source_file=?
                        WHERE import_key=?""", (message.sender, message.text, category,
                        json.dumps(keywords, ensure_ascii=False), str(source_file), key))
        return inserted

    def entries(self, category=None, chat=None, limit=200, offset=0):
        clauses, values = [], []
        for column, value in (("category", category), ("chat_label", chat)):
            if value:
                clauses.append(f"{column}=?")
                values.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return self.db.execute(
            "SELECT id,chat_label,sent_at,sender,text,category,matched_keywords FROM entries" + where +
            " ORDER BY COALESCE(sent_at,observed_at_utc) DESC,id DESC LIMIT ? OFFSET ?", (*values, limit, offset)).fetchall()

    def counts(self):
        return dict(self.db.execute("SELECT category,COUNT(*) FROM entries GROUP BY category"))

    def chats(self):
        return [row[0] for row in self.db.execute("SELECT DISTINCT chat_label FROM entries ORDER BY chat_label")]

    def reclassify(self, rules, chat_categories=None):
        rows = self.db.execute("SELECT id,chat_label,text FROM entries").fetchall()
        with self.db:
            for entry_id, chat, text in rows:
                category, words = classify_message(text, rules, chat, chat_categories)
                self.db.execute("UPDATE entries SET category=?,matched_keywords=? WHERE id=?",
                    (category, json.dumps(words, ensure_ascii=False), entry_id))
        return len(rows)

    def entry_count(self, category=None, chat=None):
        clauses, values = [], []
        for column, value in (("category", category), ("chat_label", chat)):
            if value:
                clauses.append(f"{column}=?")
                values.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return self.db.execute("SELECT COUNT(*) FROM entries" + where, values).fetchone()[0]
