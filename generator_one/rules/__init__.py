"""规则层：物理规则 + 工艺规则"""
from rules.physical_rules import check as check_physical, auto_fix as fix_physical, Violation
from rules.craft_rules import (
    check_action_grid as check_craft_actions,
    check_stitch_grid as check_craft_stitches,
    auto_fix_action_grid as fix_craft_actions,
    auto_fix_stitch_grid as fix_craft_stitches,
    tension_score,
)