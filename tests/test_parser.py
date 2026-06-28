import unittest

from eq2act.parser import Parser, parse_amount


class TestAmount(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(parse_amount("1234"), 1234)

    def test_comma(self):
        self.assertEqual(parse_amount("270,333,864"), 270333864)

    def test_suffix(self):
        self.assertEqual(parse_amount("270.3M"), 270300000)
        self.assertEqual(parse_amount("17.7B"), 17700000000)
        self.assertEqual(parse_amount("11.0K"), 11000)


class TestParser(unittest.TestCase):
    def setUp(self):
        self.p = Parser(me="Gaptia")

    def parse(self, msg):
        return self.p.parse_message(msg, 1000.0)

    def test_auto_attack(self):
        ev = self.parse("YOU hit a fierce badger for 1,234 slashing damage.")
        self.assertEqual(ev.kind, "damage")
        self.assertEqual(ev.attacker, "Gaptia")
        self.assertEqual(ev.skill, "Auto Attack")
        self.assertEqual(ev.victim, "a fierce badger")
        self.assertEqual(ev.amount, 1234)
        self.assertEqual(ev.dtype, "slashing")

    def test_your_ability(self):
        ev = self.parse("YOUR Coordinated Wounds hits a fierce badger for 5,678 cold damage.")
        self.assertEqual(ev.attacker, "Gaptia")
        self.assertEqual(ev.skill, "Coordinated Wounds")
        self.assertEqual(ev.amount, 5678)

    def test_possessive_other(self):
        ev = self.parse("Maergoth's Lightning Strike hits a fierce badger for 12,345 magic damage.")
        self.assertEqual(ev.attacker, "Maergoth")
        self.assertEqual(ev.skill, "Lightning Strike")

    def test_crit(self):
        ev = self.parse("YOUR Coordinated Wounds critically hits a fierce badger for a critical of 11.0K cold damage.")
        self.assertTrue(ev.crit)
        self.assertEqual(ev.amount, 11000)

    def test_multi_element(self):
        ev = self.parse("YOUR Frozen Whirlwind multi attacks a fierce badger for 400 heat and 200 disease damage.")
        self.assertEqual(ev.amount, 600)
        self.assertTrue(ev.multi)
        self.assertEqual(ev.dtype, "heat")

    def test_pet(self):
        ev = self.parse("Gnasher<Maergoth's tiger> hits a fierce badger for 2,000 crushing damage.")
        self.assertEqual(ev.owner, "Maergoth")
        self.assertEqual(ev.credited_to, "Maergoth")
        self.assertEqual(ev.amount, 2000)

    def test_huge_crit(self):
        ev = self.parse("Gaptia's Coordinated Wounds hits Brother Shen for a critical of 17.7B cold damage.")
        self.assertEqual(ev.attacker, "Gaptia")
        self.assertTrue(ev.crit)
        self.assertEqual(ev.amount, 17700000000)

    def test_heal(self):
        ev = self.parse("YOUR Healing Light heals Gaptia for 5,000 hit points.")
        self.assertEqual(ev.kind, "heal")
        self.assertEqual(ev.amount, 5000)

    def test_refresh(self):
        ev = self.parse("YOUR Epiphany refreshes YOU for 1,144 mana points.")
        self.assertEqual(ev.kind, "refresh")
        self.assertEqual(ev.victim, "Gaptia")

    def test_ward(self):
        ev = self.parse("YOUR Scaled Protection absorbs 5,000 points of damage from being done to Gaptia.")
        self.assertEqual(ev.kind, "ward")
        self.assertEqual(ev.amount, 5000)

    def test_miss(self):
        ev = self.parse("a fierce badger tries to hit YOU, but YOU dodge.")
        self.assertEqual(ev.kind, "miss")

    def test_death(self):
        ev = self.parse("YOU have killed a fierce badger.")
        self.assertEqual(ev.kind, "death")
        self.assertEqual(ev.victim, "a fierce badger")

    def test_line_wrapper(self):
        ev = self.p.parse_line(
            "(1649968681)[Thu Apr 14 22:38:01 2022] YOU hit a fierce badger for 1,234 slashing damage.")
        self.assertIsNotNone(ev)
        self.assertEqual(ev.ts, 1649968681.0)

    def test_noise_ignored(self):
        self.assertIsNone(self.parse("You say to the group, hello there."))


if __name__ == "__main__":
    unittest.main()
