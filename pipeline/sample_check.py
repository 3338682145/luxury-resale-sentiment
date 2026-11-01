#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分层抽样生成待人工复核清单。"""
import json
import random
import sys

random.seed(20261101)
P = "/workspace/二奢舆情采集/data/clean/cases_clean.jsonl"
rows = [json.loads(l) for l in open(P, encoding="utf-8") if l.strip()]

plan = {"A": 9, "B": 6, "C": 4, "D": 3, "E": 2}
plats = ["爱回收", "转转", "闲鱼", ""]

picked = []
for lv, n in plan.items():
    for pl in plats:
        pool = [r for r in rows if r["level"] == lv and r["platform"] == pl]
        k = min(n, len(pool))
        if k:
            picked += random.sample(pool, k)

print(f"总样本池 {len(rows)}，抽检 {len(picked)} 条\n", file=sys.stderr)

for i, r in enumerate(picked, 1):
    body = (r["title"] + " ｜ " + r["desc"]).replace("\n", " ")
    ev = " ‖ ".join(c["content"][:40] for c in r["evidence_comments"][:2])
    print(f"[{i}] L{r['level']} {r['platform'] or '无平台'} | 模块{r['cand_module']} | 负面{r['neg_score']} 评论负面{r['comment_neg_score']}")
    print(f"    T: {r['title'][:70]}")
    print(f"    D: {body[len(r['title']):][:150]}")
    if ev:
        print(f"    C: {ev[:110]}")
    print()

with open("/workspace/二奢舆情采集/data/clean/sample_ids.json", "w", encoding="utf-8") as f:
    json.dump([r["note_id"] for r in picked], f, ensure_ascii=False, indent=1)
