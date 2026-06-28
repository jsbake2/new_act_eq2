"""Turn raw EQ2 log lines into CombatEvent objects.

The regexes are ported from the official ACT English parser
(EQAditu/AdvancedCombatTracker, ACT_English_Parser.cs) which is the plugin ACT
itself ships for EQ2.  Line wrapper confirmed as:

    (1649968681)[Thu Apr 14 22:38:01 2022] message text.

Damage numbers on the 64-bit client come as plain (270333864), comma-grouped
(270,333,864) or suffix-abbreviated (270.3M / 17.7B), hence the [\\d,.KMBTQ]+
amount class.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional

from .models import CombatEvent

# --- line wrapper ------------------------------------------------------------
LINE_RE = re.compile(r"\((?P<epoch>\d{10})\)\[(?P<ts>.{24})\]\s(?P<msg>.*)$")

# amount token used everywhere
_AMT = r"[\d,\.KMBTQ]+"
_APOS = r"['’]"   # EQ2 logs use ASCII ' and the curly ’ (U+2019) interchangeably

# --- the message patterns, applied in order ----------------------------------
# 1) main damage line: auto-attack, abilities, crits, multi/double/aoe/bash
DMG_RE = re.compile(
    r"^(?P<attackerAndSkill>.+?) "
    r"(?P<special>(?:critically )?(?:hits?|flurry|flurries|multi attacks?|"
    r"double attacks?|aoe attacks?|bash(?:es)?)) "
    r"(?P<victim>.+?) for "
    r"(?P<crit>a .*?critical of )?(?P<damageAndType>.+?) damage\.$"
)
# 2) reverse / "is hit by" phrasing (DoT ticks, procs, reactives)
DMG_BY_RE = re.compile(
    r"^(?P<victim>.+?) (?:is|are) "
    r"(?P<oldcrit>(?:critically )?(?:hit|multi attack(?:ed)?)) by "
    r"(?P<skillType>.+?) for "
    r"(?P<crit>a .*?critical of )?(?P<damageAndType>.+?) damage\.$"
)
# 2b) unattributed damage: "X is hit for N damage." (falling/reflect/AOE w/o source)
UNATTRIB_RE = re.compile(
    r"^(?P<victim>.+?) (?:is|are) hit for "
    r"(?P<crit>a .*?critical of )?(?P<damageAndType>.+?) damage\.$"
)
# 3) heals
HEAL_RE = re.compile(
    r"^(?P<healerAndSkill>.+?) (?P<oldcrit>critically heals|heals) "
    r"(?P<victim>.+?) for (?P<crit>a .*?critical of )?(?P<damage>" + _AMT +
    r") hit points?\.$"
)
# 4) power "refresh"
REFRESH_RE = re.compile(
    r"^(?P<healerAndSkill>.+?) (?P<oldcrit>(?:critically )?refreshes) "
    r"(?P<victim>.+?) for (?P<crit>a .*?critical of )?(?P<damage>" + _AMT +
    r") mana points?\.$"
)
# 5) ward / absorb
WARD_RE = re.compile(
    r"^(?P<healerAndSkill>.+?) absorbs (?P<damage>" + _AMT +
    r") points? of damage from being done to (?P<victim>.+?)"
    r"(?: with " + _AMT + r" points? of damage bleeding through)?\."
)
# 6) miss / parry / dodge / riposte / resist / immune
MISS_RE = re.compile(
    r"^(?P<attacker>.+?) (?:try|tries) to (?P<attackType>[^ ]+) "
    r"(?P<victimAndSkill>.+?), but (?P<why>.+)\.$"
)
# 7) hit but no damage
NODMG_RE = re.compile(
    r"^(?P<attackerAndSkill>.+?) "
    r"(?P<crit>(?:critically )?(?:hits?|flurry|flurries|multi attacks?|"
    r"double attacks?|aoe attacks?)) "
    r"(?P<victim>.+?) but fails? to infl[ie]ct any damage\.$"
)
# 8) death / killing blow
DEATH_RE = re.compile(r"^(?P<attacker>.+?) (?:has|have) killed (?P<victim>.+)\.$")

# pet token: "Gnasher<Maergoth's tiger>" -> owner = Maergoth
PET_RE = re.compile(r"(?P<petName>[A-Za-z]* ?)<(?P<owner>[A-Za-z]+)" + _APOS +
                    r"s? (?P<petClass>.+?)>")
# possessive-form pet: "Bucknasty's awaken grave" (owner capitalised, pet name
# lowercase). EQ2 abilities are Capitalised, so a lowercase tail = a pet.
POSS_PET_RE = re.compile(r"^(?P<owner>[A-Z][a-z]+)" + _APOS +
                         r"s (?P<pet>[a-z][a-z ]+)$")

# multi-element damage like "400 heat and 200 disease" / "400 heat, 200 disease"
_SEG_RE = re.compile(r"(?P<n>" + _AMT + r")\s+(?:points of\s+)?(?P<type>[A-Za-z]+)")

_MULTI_WORDS = ("flurry", "flurries", "multi", "double", "aoe")

_SUFFIX = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000,
           "T": 1_000_000_000_000, "Q": 1_000_000_000_000_000}


def parse_amount(tok: str) -> int:
    """'270,333,864' / '270.3M' / '17.7B' / '1234' -> int."""
    tok = tok.strip().replace(",", "")
    if not tok:
        return 0
    mult = 1
    if tok[-1] in _SUFFIX:
        mult = _SUFFIX[tok[-1]]
        tok = tok[:-1]
    try:
        return int(round(float(tok) * mult))
    except ValueError:
        return 0


def _damage_and_type(blob: str) -> tuple[int, str]:
    """Sum the (possibly multi-element) damage and return (total, primary_type)."""
    total = 0
    primary = ""
    for m in _SEG_RE.finditer(blob):
        n = parse_amount(m.group("n"))
        total += n
        if not primary:
            primary = m.group("type")
    if total == 0:
        # fall back: a lone number with type word stripped
        total = parse_amount(re.sub(r"[^\d,\.KMBTQ]", "", blob))
    return total, primary


class Parser:
    """Stateful only in that it knows the logging character's name (`me`) so it
    can expand YOU / YOUR / YOURSELF.  Everything else is pure."""

    def __init__(self, me: str = "You"):
        self.me = me or "You"

    def set_me(self, name: str) -> None:
        if name:
            self.me = name

    # -- name normalisation ---------------------------------------------------
    def _expand_self(self, name: str) -> str:
        n = name.strip()
        low = n.lower()
        if low in ("you", "your", "yourself"):
            return self.me
        if low.startswith("your "):
            return self.me + " " + n[5:]
        return n

    def normalise_actor(self, token: str) -> tuple[str, Optional[str]]:
        """Return (display_name, owner_if_pet). Pets credit their owner."""
        token = token.strip()
        m = PET_RE.search(token)
        if m:
            owner = self._expand_self(m.group("owner"))
            pet = (m.group("petName") or "").strip() or (owner + "'s pet")
            return pet, owner
        # possessive-form pet "Bucknasty's awaken grave" -> fold onto owner
        pp = POSS_PET_RE.match(token)
        if pp:
            owner = self._expand_self(pp.group("owner"))
            return owner, owner
        return self._expand_self(token), None

    def _split_attacker_skill(self, blob: str) -> tuple[str, Optional[str], str]:
        """attackerAndSkill -> (attacker_display, owner_if_pet, skill_name)."""
        blob = blob.strip()
        # pet first (e.g. "Gnasher<Maergoth's tiger>")
        pm = PET_RE.search(blob)
        if pm:
            disp, owner = self.normalise_actor(blob)
            return disp, owner, "Auto Attack"
        low = blob.lower()
        if low == "you" or low == "yourself":
            return self.me, None, "Auto Attack"
        if low.startswith("your "):
            return self.me, None, blob[5:].strip()
        # possessive: "Gaptia's Coordinated Wounds" or "Anomalous' Impale"
        # (names ending in s take a bare apostrophe, hence s?)
        pm2 = re.match(r"^(?P<who>.+?)" + _APOS + r"s? (?P<skill>.+)$", blob)
        if pm2:
            who, _ = self.normalise_actor(pm2.group("who"))
            skill = pm2.group("skill").strip()
            # lowercase skill tail = a pet's name (abilities are Capitalised in
            # EQ2), so credit the owner and flag it as pet damage.
            if skill[:1].islower():
                return who, who, skill
            return who, None, skill
        # plain name -> auto attack
        disp, owner = self.normalise_actor(blob)
        return disp, owner, "Auto Attack"

    # -- main entry -----------------------------------------------------------
    def parse_line(self, line: str) -> Optional[CombatEvent]:
        m = LINE_RE.match(line)
        if not m:
            return None
        ts = float(m.group("epoch"))
        msg = m.group("msg").rstrip("\r\n")
        return self.parse_message(msg, ts, raw=line)

    def parse_message(self, msg: str, ts: float, raw: str = "") -> Optional[CombatEvent]:
        # Order matters. The reverse "X is hit by Y for Z" and unattributed
        # "X is hit for Z" forms MUST be tried before the main damage regex —
        # otherwise "Gobekn is hit by Trap for 50" gets misread as attacker
        # "Gobekn is" hitting victim "by Trap" (because "is hit" matches the verb).
        bm = DMG_BY_RE.match(msg)
        if bm:
            vic, _ = self.normalise_actor(bm.group("victim"))
            atk, owner, skill = self._split_attacker_skill(bm.group("skillType"))
            amount, dtype = _damage_and_type(bm.group("damageAndType"))
            oc = bm.group("oldcrit").lower()
            crit = bool(bm.group("crit")) or "critically" in oc
            return CombatEvent(ts, "damage", atk, vic, skill, amount, dtype,
                               crit, "multi" in oc, owner=owner, raw=raw)

        um = UNATTRIB_RE.match(msg)
        if um:
            vic, _ = self.normalise_actor(um.group("victim"))
            amount, dtype = _damage_and_type(um.group("damageAndType"))
            # no attacker to credit — record incoming only
            return CombatEvent(ts, "damage", "", vic, "", amount, dtype,
                               bool(um.group("crit")), raw=raw)

        dm = DMG_RE.match(msg)
        if dm and "but fail" not in msg:
            atk, owner, skill = self._split_attacker_skill(dm.group("attackerAndSkill"))
            vic, _vowner = self.normalise_actor(dm.group("victim"))
            amount, dtype = _damage_and_type(dm.group("damageAndType"))
            special = dm.group("special").lower()
            crit = bool(dm.group("crit")) or special.startswith("critically")
            multi = any(w in special for w in _MULTI_WORDS)
            return CombatEvent(ts, "damage", atk, vic, skill, amount, dtype,
                               crit, multi, owner=owner, raw=raw)

        hm = HEAL_RE.match(msg)
        if hm:
            atk, owner, skill = self._split_attacker_skill(hm.group("healerAndSkill"))
            vic, _ = self.normalise_actor(hm.group("victim"))
            amount = parse_amount(hm.group("damage"))
            crit = bool(hm.group("crit")) or "critically" in hm.group("oldcrit").lower()
            return CombatEvent(ts, "heal", atk, vic, skill, amount, "heal",
                               crit, owner=owner, raw=raw)

        rm = REFRESH_RE.match(msg)
        if rm:
            atk, owner, skill = self._split_attacker_skill(rm.group("healerAndSkill"))
            vic, _ = self.normalise_actor(rm.group("victim"))
            return CombatEvent(ts, "refresh", atk, vic, skill,
                               parse_amount(rm.group("damage")), "power",
                               owner=owner, raw=raw)

        wm = WARD_RE.match(msg)
        if wm:
            atk, owner, skill = self._split_attacker_skill(wm.group("healerAndSkill"))
            vic, _ = self.normalise_actor(wm.group("victim"))
            return CombatEvent(ts, "ward", atk, vic, skill,
                               parse_amount(wm.group("damage")), "ward",
                               owner=owner, raw=raw)

        nm = NODMG_RE.match(msg)
        if nm:
            atk, owner, skill = self._split_attacker_skill(nm.group("attackerAndSkill"))
            vic, _ = self.normalise_actor(nm.group("victim"))
            return CombatEvent(ts, "miss", atk, vic, skill, 0, "",
                               miss_reason="no damage", owner=owner, raw=raw)

        mm = MISS_RE.match(msg)
        if mm:
            atk, owner, _ = self._split_attacker_skill(mm.group("attacker"))
            vic, _ = self.normalise_actor(mm.group("victimAndSkill"))
            return CombatEvent(ts, "miss", atk, vic, "Auto Attack", 0, "",
                               miss_reason=mm.group("why"), owner=owner, raw=raw)

        dthm = DEATH_RE.match(msg)
        if dthm:
            atk, owner, _ = self._split_attacker_skill(dthm.group("attacker"))
            vic, _ = self.normalise_actor(dthm.group("victim"))
            return CombatEvent(ts, "death", atk, vic, "", 0, "", owner=owner, raw=raw)

        return None

    def parse_many(self, lines: Iterable[str]) -> List[CombatEvent]:
        out = []
        for ln in lines:
            ev = self.parse_line(ln)
            if ev is not None:
                out.append(ev)
        return out
