#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集进度快照：一行 JSON 输出，供定时巡检读取。"""
import glob
import json
import os
import subprocess
import sys
import time

CAND = "/workspace/二奢舆情采集/data/candidates.jsonl"
BASE = "/workspace/MediaCrawler"
OLD_STATE = "/workspace/二奢舆情采集/data/state.json"


def count_jsonl(pattern):
    ids = set()
    for p in glob.glob(os.path.join(BASE, pattern)):
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        nid = json.loads(line).get("note_id")
                        if nid:
                            ids.add(nid)
                    except Exception:
                        pass
        except Exception:
            pass
    return ids


def main():
    cand = []
    try:
        with open(CAND, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    cand.append(json.loads(line))
    except Exception:
        pass
    cand_ids = {c["note_id"] for c in cand if c.get("note_id")}

    new_done = count_jsonl("data/xhs/jsonl/detail_contents_*.jsonl")

    old_done = set()
    try:
        old_done = set(json.load(open(OLD_STATE, encoding="utf-8"))["detailed"].keys())
    except Exception:
        pass

    failed = set()
    try:
        failed = set(json.load(open(os.path.join(BASE, "data/xhs/detail_failed.json"), encoding="utf-8")))
    except Exception:
        pass

    merged = (new_done | old_done) & cand_ids
    left = cand_ids - new_done - old_done - failed

    alive = False
    try:
        out = subprocess.run(["pgrep", "-af", "run_xhs_[d]etail"], capture_output=True, text=True)
        alive = bool(out.stdout.strip())
    except Exception:
        pass

    # 评论条数
    n_comments = 0
    for p in glob.glob(os.path.join(BASE, "data/xhs/jsonl/detail_comments_*.jsonl")):
        try:
            with open(p, encoding="utf-8") as f:
                n_comments += sum(1 for line in f if line.strip())
        except Exception:
            pass

    snap = {
        "ts": time.strftime("%H:%M:%S"),
        "cand": len(cand_ids),
        "new": len(new_done),
        "old": len(old_done & cand_ids),
        "merged": len(merged),
        "left": len(left),
        "failed": len(failed),
        "comments": n_comments,
        "proc_alive": alive,
        "pct": round(len(merged) / max(len(cand_ids), 1) * 100, 1),
    }
    print(json.dumps(snap, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
