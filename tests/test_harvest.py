import unittest

from eq2act.harvest import HarvestTracker


def L(verb_line):
    """Wrap a bare message the way HarvestTracker.feed expects (no timestamp)."""
    return verb_line


class TestHarvest(unittest.TestCase):
    def setUp(self):
        self.t = HarvestTracker()

    def feed(self, msg, ts=1.0):
        return self.t.feed(msg, ts)

    def test_basic_gather(self):
        self.assertTrue(self.feed(
            r"You gather 3 \aITEM -1 -2:tussah root\/a from the velvety roots."))
        snap = self.t.snapshot()
        self.assertEqual(snap["total_qty"], 3)
        self.assertEqual(snap["total_pulls"], 1)
        self.assertEqual(snap["items"][0]["item"], "tussah root")
        self.assertEqual(snap["items"][0]["category"], "Gathering")
        self.assertEqual(snap["items"][0]["node"], "velvety roots")

    def test_forest_verb(self):
        # regression: the 'forest' verb (wood) was once missing entirely
        self.assertTrue(self.feed(
            r"You forest 10 \aITEM -5 -6:severed maple\/a from the wind felled tree."))
        snap = self.t.snapshot()
        self.assertEqual(snap["items"][0]["category"], "Foresting")
        self.assertEqual(snap["total_qty"], 10)

    def test_acquire_article_and_mined(self):
        self.assertTrue(self.feed(
            r"You acquire a 1 \aITEM 1 2:deer meat\/a from the creature den."))
        self.assertTrue(self.feed(
            r"You mined 3 \aITEM 3 4:supple loam\/a from the residual ore."))
        snap = self.t.snapshot()
        cats = {c["key"]: c["qty"] for c in snap["categories"]}
        self.assertEqual(cats["Trapping"], 1)
        self.assertEqual(cats["Mining"], 3)

    def test_rare_attributed_forward(self):
        # the rare is the item AFTER the banner, not the common item before it
        self.feed(r"You mine 1 \aITEM 1 2:salty loam\/a from the cloven ore.")
        self.feed("You have found a rare item!")
        self.feed(r"You mine 1 \aITEM 3 4:alkaline loam\/a from the cloven ore.")
        items = {it["item"]: it for it in self.t.snapshot()["items"]}
        self.assertFalse(items["salty loam"]["is_rare"])
        self.assertTrue(items["alkaline loam"]["is_rare"])
        self.assertEqual(items["alkaline loam"]["rares"], 1)

    def test_rare_total_reconciles(self):
        self.feed("You have found a rare item!")
        self.feed(r"You gather 1 \aITEM 1 2:oak root\/a from the velvety roots.")
        snap = self.t.snapshot()
        self.assertEqual(snap["rare_total"], 1)
        self.assertEqual(snap["total_rares"], 1)

    def test_node_grouping(self):
        self.feed(r"You mine 5 \aITEM 1 2:iron cluster\/a from the cloven ore.")
        self.feed(r"You mine 3 \aITEM 3 4:salty loam\/a from the cloven ore.")
        self.feed(r"You gather 2 \aITEM 5 6:root\/a from the roots.")
        nodes = {n["key"]: n for n in self.t.snapshot()["nodes"]}
        self.assertEqual(nodes["cloven ore"]["qty"], 8)
        self.assertEqual(len(nodes["cloven ore"]["items"]), 2)
        self.assertEqual(nodes["roots"]["qty"], 2)

    def test_non_harvest_ignored(self):
        self.assertFalse(self.feed("Fakechar hits a dummy for 100 slashing damage."))
        self.assertFalse(self.feed("You receive 5 gold."))

    def test_merge_and_load_old_format(self):
        self.feed(r"You mine 5 \aITEM 1 2:iron cluster\/a from the cloven ore.")
        other = HarvestTracker()
        other.feed(r"You mine 4 \aITEM 1 2:iron cluster\/a from the cloven ore.", 2.0)
        self.t.merge(other)
        self.assertEqual(self.t.items["iron cluster"]["qty"], 9)
        # round-trip through the older on-disk shape ("actions" instead of "pulls")
        fresh = HarvestTracker()
        fresh.load({"items": {"gold cluster": {"qty": 7, "actions": 3, "rares": 0,
                    "category": "Mining", "node": "wind swept stones"}},
                    "rare_total": 0})
        self.assertEqual(fresh.items["gold cluster"]["pulls"], 3)


if __name__ == "__main__":
    unittest.main()
