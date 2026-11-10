import unittest
from categorizer import Store, classify, new_tail

class CoreTests(unittest.TestCase):
    def test_matching(self):
        rules = {"Money": ["pay"], "Study": ["課題"]}
        self.assertEqual(classify("ＰＡＹ now", rules)[0], "Money")
        self.assertEqual(classify("payment", rules)[0], "Uncategorized")
        self.assertEqual(classify("課題を提出", rules)[0], "Study")

    def test_ties_and_empty_rules(self):
        self.assertEqual(classify("meet and pay", {"A": ["meet"], "B": ["pay"]})[0], "Needs review")
        self.assertEqual(classify("hello", {})[0], "Uncategorized")

    def test_snapshots(self):
        self.assertEqual(new_tail(["a", "b"], ["b", "c"]), ["c"])
        self.assertEqual(new_tail(["ok"], ["ok", "ok"]), ["ok"])
        self.assertEqual(new_tail(["a"], ["a"]), [])
        self.assertIsNone(new_tail(["a"], ["unrelated"]))
        self.assertIsNone(new_tail(["a"], []))

    def test_storage_preserves_repetitions_and_unicode(self):
        store = Store(":memory:")
        try:
            store.add("Test", "課題", "Study", ["課題"])
            store.add("Test", "課題", "Study", ["課題"])
            rows = store.db.execute("SELECT text, category FROM entries").fetchall()
            self.assertEqual(rows, [("課題", "Study"), ("課題", "Study")])
        finally:
            store.close()

if __name__ == "__main__":
    unittest.main()
