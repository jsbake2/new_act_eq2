import unittest
from pathlib import Path

from eq2act.encounter import EncounterManager
from eq2act.group import GroupTracker
from eq2act.parser import Parser

SAMPLE = Path(__file__).parent / "sample_logs" / "eq2log_Gaptia.txt"


class TestEncounter(unittest.TestCase):
    def setUp(self):
        self.parser = Parser(me="Gaptia")
        self.group = GroupTracker(me="Gaptia", mode="group")
        self.mgr = EncounterManager(self.group, timeout=12.0)

    def feed_file(self):
        for line in SAMPLE.read_text().splitlines():
            from eq2act.parser import LINE_RE
            m = LINE_RE.match(line)
            if not m:
                continue
            msg = m.group("msg")
            ts = float(m.group("epoch"))
            self.group.observe_text(msg)
            ev = self.parser.parse_message(msg, ts)
            if ev:
                self.mgr.feed(ev)

    def test_two_fights(self):
        self.feed_file()
        self.mgr.tick(now=1649968800)   # force-close trailing fight
        fights = self.mgr.all_fights()
        self.assertEqual(len(fights), 2)

    def test_group_membership(self):
        self.feed_file()
        self.assertIn("Maergoth", self.group.group)
        self.assertTrue(self.group.is_friend("Gaptia"))
        self.assertTrue(self.group.is_friend("Maergoth"))

    def test_cocombat_detects_dps_ally(self):
        # EQ2 encounter-locks mobs, so anyone damaging my mob is on my side —
        # even a pure-DPS ally who never heals and isn't in /whogroup.
        self.feed_file()
        self.assertIn("Randomstranger", self.group.players)
        self.assertTrue(self.group.is_friend("Randomstranger"))

    def test_solo_mode_excludes_others(self):
        # solo mode tracks only me + my pets, ignoring groupmates entirely.
        self.parser = Parser(me="Gaptia")
        self.group = GroupTracker(me="Gaptia", mode="solo")
        self.mgr = EncounterManager(self.group, timeout=12.0)
        self.feed_file()
        self.assertTrue(self.group.is_friend("Gaptia"))
        self.assertFalse(self.group.is_friend("Maergoth"))
        self.assertFalse(self.group.is_friend("Randomstranger"))

    def test_pet_credited_to_owner(self):
        self.feed_file()
        fight1 = self.mgr.history[0] if self.mgr.history else self.mgr.all_fights()[0]
        # Maergoth's pet damage (2000) should fold into Maergoth's total
        maer = fight1.combatants.get("Maergoth")
        self.assertIsNotNone(maer)
        self.assertGreaterEqual(maer.damage, 12345 + 2000)

    def test_solo_excludes_from_parse(self):
        self.parser = Parser(me="Gaptia")
        self.group = GroupTracker(me="Gaptia", mode="solo")
        self.mgr = EncounterManager(self.group, timeout=12.0)
        self.feed_file()
        fight1 = self.mgr.all_fights()[0]
        # in solo mode only Gaptia (+ pets) is a friendly combatant
        self.assertIn("Gaptia", fight1.combatants)
        self.assertNotIn("Randomstranger", fight1.combatants)

    def test_fight_named_for_top_enemy(self):
        self.feed_file()
        self.mgr.tick(now=1649968800)
        names = {f.name for f in self.mgr.all_fights()}
        self.assertIn("Brother Shen", names)
        self.assertIn("a fierce badger", names)

    def test_pastable(self):
        from eq2act.pastable import format_parse
        self.feed_file()
        self.mgr.tick(now=1649968800)
        f = [x for x in self.mgr.all_fights() if x.name == "Brother Shen"][0]
        txt = format_parse(f.summary())
        self.assertIn("Brother Shen", txt)
        self.assertIn("Gaptia", txt)


if __name__ == "__main__":
    unittest.main()
