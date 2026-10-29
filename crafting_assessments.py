"""Authored phase-4 assessment panel, acore#1 / #5. Proposals are not approvals.

Values are guarded against baseline drift. These are small, item-specific hypotheses
for review, not an executable migration or claims of in-game validation.
"""
PANEL = {
    2568: ('adjustment proposed', 'Brown Linen Vest: for a self-funded cloth wearer around 5–15, its 15 armor trails readily sold Knitted/Woven Vests at 18. Propose armor 18, keeping it below the 21-armor, +2 Spirit Journeyman vest. This removes a basic vendor disadvantage without adding a universal stat package. Verify accessible vendor prices and actual linen effort before acceptance.', {'armor': (15,18)}),
    2303: ('adjustment proposed', 'Handstitched Leather Pants: propose +1 Agility in an unused stat slot. Burnt Leather Breeches provide +1 Agility and 48 armor; keeping crafted armor at 46 retains a modest drop advantage. The DBC/trainer skill discrepancy and material effort must be resolved before selecting this for a pilot. This is a tentative leather leveling hypothesis, not proof of availability.', {'stat_type1': (0,3),'stat_value1': (0,1)}),
    2584: ('adjustment proposed', 'Woolen Cape: propose +1 Stamina, retaining 14 armor. Rat Cloth Cloak has +2 Stamina at 14 armor; Inscribed Cloak adds +2 Stamina at 15 armor. Preserve those drop advantages while giving wool investment a small defensive purpose. Confirm source access at approximately 11–15 and wool availability; do not compare only equip levels.', {'stat_type1': (0,7),'stat_value1': (0,1)}),
    2300: ('manual review','Embossed Leather Vest already has +2 Stamina. Riverpaw and Gnoll alternatives add other primary stats but source access and the DBC/trainer rank conflict remain unresolved. Do not raise its stats merely because the broad uncertainty band includes much later drops.', {}),
    2308: ('manual review','Fine Leather Cloak needs a role and source review. Later acquisition alternatives such as Inscribed/Stonemason cloaks are conditional drops, not guaranteed starter equipment. Preserve baseline until recipe/material effort and practical access are compared.', {}),
    2309: ('manual review','Embossed Leather Boots have conflicting skill evidence. Higher-level Inscribed/Bristlebark alternatives are insufficient grounds for a low-level buff. Resolve the training and self-sufficient route first.', {}),
    2314: ('manual review','Toughened Leather Armor has a broader acquisition uncertainty than its equip level suggests. Intermediate materials and profession progression matter. Preserve baseline; do not tune against a level-40 template merely because uncertainty extends to 60.', {}),
    2315: ('manual review','Dark Leather Boots compete in a band containing rare and unusually strong drops. Feet of the Lynx is not an ordinary guaranteed acquisition benchmark. Retain baseline until the recipe/material route and a non-exceptional comparator set are verified.', {}),
    2316: ('manual review','Dark Leather Cloak alternatives include dungeon and rare-drop cloaks. Their source identities are evidence, not equal effort or availability. Preserve the item pending travel, group and recipe-path review.', {}),
    2569: ('strong — leave unchanged','Linen Boots provide +1 Intellect and +1 Spirit at 17 armor. The nearby Calico, Native and Spellbinder examples have no resolved primary stats and 15–17 armor. This is already a useful caster-leveling craft in the provisional 8–15 scenario; retain it. Market and recipe effort still need owner confirmation.', {}),
    2578: ('strong — leave unchanged','Barbaric Linen Vest combines +2 Stamina and +2 Spirit with 26 armor. The nearby vendor Knitted Vest and Journeyman example offer less defense or fewer dimensions. Preserve a worthwhile early tailoring milestone rather than flattening the whole profession with buffs.', {}),
    2580: ('manual review','Reinforced Linen Cape already contributes Intellect. Seer’s Cape is a higher-equip-level drop with more armor and two stats; it should remain a desirable alternative. No numerical change until availability and cloth investment are calibrated.', {}),
    2582: ('strong — leave unchanged','Green Woolen Vest already has +4 Stamina, +3 critical rating and 30 armor on this WotLK baseline. The shown vendor/ordinary examples have less armor and no equivalent resolved primary benefits. Retain the existing craft; this is not an original-Vanilla-stat reconstruction.', {}),
    4307: ('manual review','Heavy Linen Gloves have an early Spirit niche. Quest rewards with zero equip requirement must be evaluated by quest minimum/recommended level, faction and prerequisites. They are not level-1 benchmarks. No buff based on those templates alone.', {}),
    4308: ('strong — leave unchanged','Green Linen Bracers add +1 Stamina at 10 armor; the nearby Calico/Barbaric/Simple examples have 9 armor without the same resolved stat. Preserve this modest useful step at provisional acquisition 7–15.', {}),
    4309: ('strong — leave unchanged','Handstitched Linen Britches supply +2 Intellect, +2 Spirit and 23 armor compared with vendor/Calico examples at 16–17 armor with no resolved primary stats. Keep this caster progression option unchanged.', {}),
    2848: ('manual review','Bronze Mace already has hit rating and approximately 11.15 base DPS. Stout Battlehammer is around 10.87 DPS, but weapon speed and random properties can change the comparison. Preserve baseline; no universal DPS-only or stat-sum conclusion.', {}),
    2849: ('manual review','Bronze Axe already supplies +3 Stamina and roughly 11.67 base DPS. Forester’s Axe has similar base DPS but unresolved variants and speed trade-offs. Preserve the craft while checking weapon-role assumptions; no automatic damage buff.', {}),
    2850: ('manual review','Bronze Shortsword has +3 Agility and about 12.38 base DPS, already near the conditional Decapitating Sword and vendor Longsword examples. Attack speed, class role and random variants require review; retain baseline.', {}),
    4368: ('manual review','Flying Tiger Goggles provide an early head-slot option with +4 Stamina and +4 Spirit, but require Engineering 100 to wear. A fishing-reward hat is not a role-equivalent combat benchmark. Keep the item and verify profession, materials and sparse head-slot availability before any adjustment.', {}),
    4373: ('manual review','Shadow Goggles offer +5 Intellect and +6 Spirit but recipe access extends uncertainty. Do not compare an equip-zero engineering wearable directly to equip-zero unrestricted gear or much later dungeon hats. Retain baseline until the recipe route is known.', {}),
    4385: ('manual review','Green Tinted Goggles have +8 Stamina and +7 Spirit but require Engineering 150. Their value is tied to profession investment and early head-slot scarcity. Keep baseline and review actual skill/material availability instead of buffing from equip requirement alone.', {}),
}


def apply_panel(record):
    if record['id'] not in PANEL:
        record['focused_panel'] = False
        return
    assessment,reason,changes = PANEL[record['id']]
    for field,(expected,value) in changes.items():
        if record['baseline'].get(field)!=expected:
            raise ValueError(f"Assessment baseline changed for item {record['id']} field {field}; re-review authored proposal")
        record['proposed'][field]=value
    record['assessment']=assessment
    record['reasoning'].append(reason)
    record['focused_panel']=True
    record['limitations'].append('Focused engineering assessment, not owner approval or in-game validation. Acquisition assumptions must be confirmed before a pilot.')
