#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把负面词补搜结果并入候选池，供后续清洗使用。

输出：
  data/candidates_v2.jsonl   原候选 + 补搜新增（去重）
  data/clean/search_new.jsonl 仅补搜新增部分
"""
import glob
import json
import os

BASE = "/workspace/二奢舆情采集"
MC = "/workspace/MediaCrawler"

PLAT = {"爱回收": ["爱回收", "万物新生"], "转转": ["转转"], "闲鱼": ["闲鱼", "咸鱼"]}


def guess_module(kw, text):
    """按关键词与正文判定归属模块。"""
    for name, words in PLAT.items():
        if any(w in kw for w in words):
            if name == "闲鱼":
                return "P0-B-闲鱼"
            return f"P0-A-{name}"
    for name, words in PLAT.items():
        if any(w in text for w in words):
            return "P0-B-闲鱼" if name == "闲鱼" else f"P0-A-{name}"
    return "补搜-未分类"


def main():
    old = {}
    with open(os.path.join(BASE, "data/candidates.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                old[d["note_id"]] = d

    new = {}
    for p in glob.glob(os.path.join(MC, "data/xhs/jsonl/search_contents_*.jsonl")):
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                nid = d.get("note_id")
                if not nid:
                    continue
                title = d.get("title") or ""
                desc = d.get("desc") or ""
                kw = d.get("source_keyword") or ""
                new[nid] = {
                    "note_id": nid,
                    "xsec_token": d.get("xsec_token", ""),
                    "title": title,
                    "nickname": d.get("nickname", ""),
                    "liked": d.get("liked_count", ""),
                    "comment": d.get("comment_count", ""),
                    "module": guess_module(kw, title + desc),
                    "from_kw": kw,
                    "src": "补搜",
                }

    added = {k: v for k, v in new.items() if k not in old}
    merged = list(old.values()) + list(added.values())

    os.makedirs(os.path.join(BASE, "data/clean"), exist_ok=True)
    with open(os.path.join(BASE, "data/candidates_v2.jsonl"), "w", encoding="utf-8") as f:
        for r in merged:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(BASE, "data/clean/search_new.jsonl"), "w", encoding="utf-8") as f:
        for r in added.values():
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    from collections import Counter
    print(json.dumps({
        "补搜采集": len(new),
        "与原候选重复": len(new) - len(added),
        "净新增": len(added),
        "合并后候选": len(merged),
        "新增模块分布": dict(Counter(v["module"] for v in added.values())),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
