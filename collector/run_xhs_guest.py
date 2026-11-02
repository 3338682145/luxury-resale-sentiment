#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""二奢舆情项目：免 cookie（游客态）补采小红书详情的采集器。

与 run_xhs_detail.py 的区别：
  - 不依赖 MediaCrawler / 登录 cookie / x-s 签名，纯 curl + iPhone UA 打 SSR
  - 产出 正文 / 标题 / 作者 / 互动数 / 图片 / 标签 / 首屏评论（一级+子评论）
  - 评论只有首屏一页（约 10 条一级），大热帖拿不全；翻页必须签名

用法：
  python3 run_xhs_guest.py --src case --limit 20        # 用案例库 CSV 的链接抽查
  python3 run_xhs_guest.py --src cand --limit 1000      # 用候选清单补采
  python3 run_xhs_guest.py --src cand --only-pending    # 只补「未拉详情」的

输出：
  data/guest/notes_guest.jsonl     每行一条笔记（字段对齐 clean_cases.load_new）
  data/guest/comments_guest.jsonl  每行一条评论
  data/guest/run_log.json          本次运行统计
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUTDIR = os.path.join(ROOT, "data/guest")
os.makedirs(OUTDIR, exist_ok=True)

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")

NOTES_OUT = os.path.join(OUTDIR, "notes_guest.jsonl")
COMMENTS_OUT = os.path.join(OUTDIR, "comments_guest.jsonl")


# ---------------------------------------------------------------- HTTP
def fetch(url, timeout=25):
    """取 SSR HTML。--noproxy 必须加，本机系统代理会破坏请求。"""
    p = subprocess.run(
        ["curl", "-sS", "--noproxy", "*", "-A", UA, "-L",
         "--max-time", str(timeout), "-w", "\n@@HTTP:%{http_code}", url],
        capture_output=True, text=True, errors="ignore",
    )
    body, _, code = p.stdout.rpartition("\n@@HTTP:")
    return code.strip(), body


# ---------------------------------------------------------------- 解析
def _jsonslice(text, key):
    """取 `"key":{...}` 那段，按括号配平切片（跳过字符串内的括号）。"""
    i = text.find('"%s"' % key)
    if i < 0:
        return None
    i = text.find("{", i)
    if i < 0:
        return None
    depth, j, instr, esc = 0, i, False, False
    while j < len(text):
        c = text[j]
        if instr:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                instr = False
        else:
            if c == '"':
                instr = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[i:j + 1])
                    except Exception:
                        return None
        j += 1
    return None


def num(v):
    """'1,200' / '1.2万' / None -> int"""
    if v is None:
        return 0
    s = str(v).strip().replace(",", "")
    if not s:
        return 0
    try:
        if "万" in s:
            return int(float(s.replace("万", "")) * 10000)
        return int(float(s))
    except Exception:
        return 0


def parse(html, note_id):
    root = _jsonslice(html, "noteData") or {}
    note = ((root.get("data") or {}).get("noteData")) or root.get("note") or {}
    if not note:
        return None
    inter = note.get("interactInfo") or {}
    user = note.get("user") or {}
    tags = [t.get("name") for t in (note.get("tagList") or [])
            if isinstance(t, dict) and t.get("name")]

    cm = _jsonslice(html, "commentData") or {}
    flat = []
    for c in (cm.get("comments") or []):
        flat.append({
            "level": 0,
            "content": (c.get("content") or "").strip(),
            "like": num(c.get("likeCount")),
            "nick": ((c.get("user") or {}).get("nickname") or ""),
            "ip": c.get("ipLocation") or "",
        })
        for s in (c.get("subComments") or []):
            flat.append({
                "level": 1,
                "content": (s.get("content") or "").strip(),
                "like": num(s.get("likeCount")),
                "nick": ((s.get("user") or {}).get("nickname") or ""),
                "ip": s.get("ipLocation") or "",
            })

    return {
        "note_id": note.get("noteId") or note_id,
        "title": (note.get("title") or "").strip(),
        "desc": (note.get("desc") or "").strip(),
        "author": user.get("nickName") or "",
        "author_id": user.get("userId") or "",
        "liked": num(inter.get("likedCount")),
        "collected": num(inter.get("collectedCount")),
        "comment_count": num(inter.get("commentCount")),
        "share_count": num(inter.get("shareCount")),
        "images": len(note.get("imageList") or []),
        "type": note.get("type"),
        "publish_ts": note.get("time"),
        "tags": tags,
        "comments": flat,
        "comments_l1": cm.get("commentCountL1") or 0,
    }


# ---------------------------------------------------------------- 输入
def token_map():
    """候选清单里 944 条链接全带 xsec_token，按 note_id 建索引用于回填。"""
    idx = {}
    path = os.path.join(ROOT, "outputs/候选链接清单_944.csv")
    if not os.path.exists(path):
        return idx
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if "xsec_token" in (r.get("链接") or ""):
                idx[r["笔记ID"]] = r["链接"]
    return idx


def load_src(src, only_pending=False):
    out = []
    if src == "case":
        path = os.path.join(ROOT, "outputs/案例库_入库_217条.csv")
        tk = token_map()
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                url = r["链接"]
                nid = nid_of(url)
                filled = "xsec_token" not in url and nid in tk
                if filled:
                    url = tk[nid]
                out.append({"note_id": nid, "url": url,
                            "module": r.get("平台", ""), "token_filled": filled})
    else:
        path = os.path.join(ROOT, "outputs/候选链接清单_944.csv")
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if only_pending and r.get("是否已拉详情") != "否":
                    continue
                out.append({"note_id": r["笔记ID"], "url": r["链接"], "module": r["模块"]})
    return out


def nid_of(url):
    m = re.search(r"/(?:explore|discovery/item|item)/([0-9a-f]{24})", url or "")
    return m.group(1) if m else ""


def done_ids():
    s = set()
    if os.path.exists(NOTES_OUT):
        with open(NOTES_OUT, encoding="utf-8") as f:
            for line in f:
                try:
                    s.add(json.loads(line)["note_id"])
                except Exception:
                    pass
    return s


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", choices=["case", "cand"], default="cand")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--interval", type=float, default=1.5)
    ap.add_argument("--only-pending", action="store_true")
    ap.add_argument("--max-empty", type=int, default=3,
                    help="连续 N 条取不到内容即熔断（风控降级时尽快停手）")
    args = ap.parse_args()

    rows = load_src(args.src, args.only_pending)
    seen = done_ids()
    todo = [r for r in rows if (nid_of(r["url"]) or r["note_id"]) not in seen][:args.limit]
    print("待采 %d 条（总计 %d，已完成 %d）" % (len(todo), len(rows), len(seen)))

    ok = empty = fail = 0
    consec_empty = 0
    t0 = time.time()
    with open(NOTES_OUT, "a", encoding="utf-8") as fn, \
            open(COMMENTS_OUT, "a", encoding="utf-8") as fc:
        for i, r in enumerate(todo, 1):
            nid = nid_of(r["url"]) or r["note_id"]
            code, html = fetch(r["url"])
            d = parse(html, nid) if code == "200" else None
            if not d or not (d["title"] or d["desc"]):
                empty += 1
                consec_empty += 1
                if not d and "仅支持在小红书" in html:
                    st = "app_only"      # 网页端不给内容，需 APP
                elif d or "noteData" in html:
                    st = "no_content"
                else:
                    st = "deleted"
                if "xsec_token" not in r["url"]:
                    st = "no_token"
                print("  [%d/%d] %s %s %s (%s)" % (i, len(todo), code, st, nid[:12], r["module"]))
                fn.write(json.dumps({"note_id": nid, "status": st, "module": r["module"],
                                     "url": r["url"]}, ensure_ascii=False) + "\n")
                time.sleep(args.interval)
                if consec_empty >= args.max_empty:
                    print("  连续 %d 条取不到内容 → 熔断（疑似风控降级），请冷却后重跑" % consec_empty)
                    break
                continue
            if code != "200":
                fail += 1
            ok += 1
            consec_empty = 0
            d.update({"url": r["url"], "module": r["module"], "status": "ok", "src": "guest"})
            fn.write(json.dumps(d, ensure_ascii=False) + "\n")
            for c in d["comments"]:
                fc.write(json.dumps({"note_id": d["note_id"], **c}, ensure_ascii=False) + "\n")
            print("  [%d/%d] %s 👍%d 💬%d(抓%d) 🖼%d %-12s %s"
                  % (i, len(todo), code, d["liked"], d["comment_count"],
                     len(d["comments"]), d["images"], r["module"], d["title"][:24]))
            time.sleep(args.interval)

    log = {"src": args.src, "limit": args.limit, "tried": len(todo), "ok": ok,
           "empty": empty, "fail": fail, "secs": round(time.time() - t0, 1),
           "ts": int(time.time())}
    with open(os.path.join(OUTDIR, "run_log.json"), "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    print(json.dumps(log, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
