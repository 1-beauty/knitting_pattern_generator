# -*- coding: utf-8 -*-
"""Remove w/o PatternPlan mention from desktop speech draft S10."""
p = r"E:\DeskTop\PPT答辩讲稿_10分钟.md"
s = open(p, encoding="utf-8").read()
pairs = [
    ("与四个基线的对比", "与三个基线的对比"),
    ("本项目 0，去掉 PatternPlan 的消融版本也是 0，LLM 直接生成", "本项目 0，LLM 直接生成"),
]
for old, new in pairs:
    assert old in s, f"not found: {old[:20]}"
    s = s.replace(old, new)
open(p, "w", encoding="utf-8").write(s)
print("speech fixed OK; leftover w/o:", s.count("w/o"), "; leftover 消融:", s.count("消融"))
