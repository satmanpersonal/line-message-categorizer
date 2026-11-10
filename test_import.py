import csv
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from categorizer import Store, classify, classify_message
from configuration import validate
from line_import import Message, import_file, parse_date, parse_export, read_export


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.rules = {"Work / Logistics": ["荷揚げ"], "Friends": ["hang out"]}
        self.config = {"categories": self.rules, "date_order": "MDY", "poll_seconds": 3}

    def tearDown(self):
        self.store.close()

    def test_japanese_export_and_multiline_content(self):
        text = ('[LINE] サンプルとのトーク履歴\r\n保存日時：2026/10/23 16:00\r\n\r\n'
                '2026/10/23(金)\r\n09:00\t太郎\t"荷揚げの予定\n\n10:00集合\n引用: ""了解"""\r\n'
                '09:01\t花子\t了解\r\n09:02\t太郎がグループに参加しました。\r\n')
        chat, messages = parse_export(text, "fallback")
        self.assertEqual(chat, "サンプル")
        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[0], Message("2026-10-23T09:00:00", "太郎", '荷揚げの予定\n\n10:00集合\n引用: "了解"'))
        self.assertEqual(messages[2].sender, "[System]")

    def test_english_export_dates_and_am_pm(self):
        text = '[LINE] Chat history with Alex\nFriday, October 23, 2026\n9:30 PM\tAlex\thang out\n'
        chat, messages = parse_export(text, "fallback")
        self.assertEqual(chat, "Alex")
        self.assertEqual(messages[0].sent_at, "2026-10-23T21:30:00")
        self.assertEqual(parse_date("23/10/2026", "DMY").isoformat(), "2026-10-23")
        self.assertEqual(parse_date("Fri, 10/23/2026").isoformat(), "2026-10-23")
        self.assertEqual(parse_date("2026年10月23日(金)").isoformat(), "2026-10-23")

    def test_reimport_renamed_file_appends_only_new_messages(self):
        repeated = Message("2026-10-23T09:00:00", "Alex", "OK")
        messages = [repeated, repeated]
        self.assertEqual(self.store.import_messages("Chat", messages, self.rules, "first.txt"), 2)
        self.assertEqual(self.store.import_messages("Chat", messages, self.rules, "renamed.txt"), 0)
        self.assertEqual(self.store.import_messages("Chat", messages + [repeated], self.rules, "updated.txt"), 1)
        self.assertEqual(self.store.import_messages("Other chat", [repeated], self.rules, "other.txt"), 1)
        self.assertEqual(sum(self.store.counts().values()), 4)

    def test_atomic_import_rolls_back_on_failure(self):
        messages = [Message("2026-10-23T09:00:00", "Alex", "OK"), Message("2026-10-23T09:01:00", "Alex", None)]
        with self.assertRaises(TypeError):
            self.store.import_messages("Chat", messages, self.rules, "bad.txt")
        self.assertEqual(self.store.counts(), {})

    def test_malformed_export_does_not_save_any_messages(self):
        for text in ('09:00\tAlex\thi', 'not an export', '2026/13/23\n09:00\tA\thi',
                     '2026/10/23\n25:00\tAlex\thi', '2026/10/23\n09:00\tAlex\t"unterminated'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_export(text, "Chat")

    def test_windows_space_format_preserves_unknown_senders_and_reparses(self):
        text = '2026.10.23 Friday\n09:00 Alex Smith hang out\n09:01 My Name OK\n'
        chat, first = parse_export(text, "Alex Smith")
        self.assertEqual(first[0].sender, "Alex Smith")
        self.assertEqual(first[0].text, "hang out")
        self.assertEqual(first[1].sender, "")
        self.assertEqual(first[1].text, "My Name OK")
        self.store.import_messages(chat, first, self.rules, "file.txt")
        chat, second = parse_export(text, "Alex Smith", sender_names=["My Name"])
        self.assertEqual(second[1].sender, "My Name")
        self.assertEqual(second[1].text, "OK")
        self.assertEqual(self.store.import_messages(chat, second, self.rules, "file.txt"), 0)
        self.assertEqual(self.store.entry_count(), 2)
        self.assertEqual(self.store.db.execute("SELECT sender,text FROM entries WHERE sent_at LIKE '%09:01:00'").fetchone(), ("My Name", "OK"))

    def test_encodings_and_file_import(self):
        text = '[LINE] 仕事とのトーク履歴\n2026/10/23(金)\n09:00\t太郎\t荷揚げ\n'
        with tempfile.TemporaryDirectory() as folder:
            for encoding in ("utf-8-sig", "utf-16", "cp932"):
                path = Path(folder) / (encoding + ".txt")
                path.write_bytes(text.encode(encoding))
                self.assertEqual(read_export(path), text)
                chat, total, added, unresolved = import_file(self.store, path, self.config)
                self.assertEqual((chat, total), ("仕事", 1))
            self.assertEqual(sum(self.store.counts().values()), 1)

    def test_chat_assignment_reclassifies_existing_and_new_messages(self):
        messages = [Message("2026-10-23T09:00:00", "Alex", "OK")]
        self.store.import_messages("Chat", messages, self.rules, "file.txt")
        self.assertEqual(self.store.counts(), {"Uncategorized": 1})
        self.store.reclassify(self.rules, {"Chat": "Friends"})
        self.assertEqual(self.store.counts(), {"Friends": 1})
        self.assertEqual(classify_message("荷揚げ", self.rules, "Chat", {"Chat": "Friends"})[0], "Friends")

    def test_normalized_keywords_do_not_inflate_scores(self):
        self.assertEqual(classify("pay meet", {"A": ["pay", "PAY", "ＰＡＹ"], "B": ["meet"]})[0], "Needs review")
        self.assertEqual(classify("work shift 荷揚げ", {"Work": ["work", "shift"], "Work / Logistics": ["荷揚げ"]})[0], "Work / Logistics")

    def test_configuration_rejects_bad_values(self):
        for update in ({"categories": []}, {"categories": {"A": "word"}}, {"poll_seconds": float("nan")},
                       {"chat_categories": {"Chat": "Missing"}}, {"date_order": "YDM"}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                validate({**self.config, **update})

    def test_legacy_database_migrates_without_losing_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute('CREATE TABLE entries(id INTEGER PRIMARY KEY, observed_at_utc TEXT NOT NULL, chat_label TEXT NOT NULL, text TEXT NOT NULL, category TEXT NOT NULL, matched_keywords TEXT NOT NULL)')
            connection.execute('INSERT INTO entries VALUES(1,?,?,?,?,?)', ("2026-10-22", "Old chat", "hello", "Uncategorized", "[]"))
            connection.commit()
            connection.close()
            migrated = Store(path)
            try:
                migrated.add("Chat", "new", "Friends", [])
                self.assertEqual(sum(migrated.counts().values()), 2)
                self.assertEqual(migrated.db.execute('SELECT text FROM entries WHERE id=1').fetchone()[0], "hello")
            finally:
                migrated.close()

    def test_csv_roundtrip_unicode_and_formula_protection(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "test.sqlite3")
            try:
                store.add("日本語", "  =1+1\nsecond line", "Friends", [])
                path = store.export_csv()
                with path.open(encoding="utf-8-sig", newline="") as stream:
                    rows = list(csv.DictReader(stream))
                self.assertEqual(rows[0]["chat_label"], "日本語")
                self.assertEqual(rows[0]["text"], "'  =1+1\nsecond line")
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()

