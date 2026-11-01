#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""二奢舆情项目：按候选清单批量补采小红书详情。

特性：
  - 断点续跑：已写入 detail_contents_*.jsonl 的 note_id 自动跳过
  - 可接旧数据：把旧管线（二奢舆情采集/data/state.json）已抓过的笔记一并跳过
  - 小批次 + 批间冷却 + 单条间隔，避免触发限流
  - 风控熔断：连续两批零产出即停，不硬刷

用法：
  uv run python run_xhs_detail.py --batch-size 40 --cooldown 90
  uv run python run_xhs_detail.py --max-notes 5 --batch-size 5   # 小样试跑
"""
import argparse
import asyncio
import glob
import json
import os
import sys
import time

os.environ.setdefault("DISPLAY", ":99")

import config
from var import crawler_type_var
from tools import utils

CAND_FILE = "/workspace/二奢舆情采集/data/candidates.jsonl"
OLD_STATE = "/workspace/二奢舆情采集/data/state.json"
DATA_BASE = "data/xhs/jsonl"
FAIL_LEDGER = "data/xhs/detail_failed.json"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_candidates():
    rows = []
    with open(CAND_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if d.get("note_id"):
                rows.append(d)
    return rows


def build_url(c):
    return (
        f"https://www.xiaohongshu.com/explore/{c['note_id']}"
        f"?xsec_token={c.get('xsec_token', '')}&xsec_source=pc_feed"
    )


def done_ids():
    """MediaCrawler 已经成功写入的笔记。"""
    ids = set()
    for path in glob.glob(os.path.join(DATA_BASE, "detail_contents_*.jsonl")):
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if d.get("note_id"):
                        ids.add(d["note_id"])
        except OSError:
            pass
    return ids


def old_pipeline_ids():
    """旧管线（MCP）已抓到正文的笔记，避免重复劳动。"""
    try:
        st = json.load(open(OLD_STATE, encoding="utf-8"))
        return set(st.get("detailed", {}).keys())
    except Exception:
        return set()


def load_failed():
    try:
        return set(json.load(open(FAIL_LEDGER, encoding="utf-8")))
    except Exception:
        return set()


def save_failed(ids):
    os.makedirs(os.path.dirname(FAIL_LEDGER), exist_ok=True)
    json.dump(sorted(ids), open(FAIL_LEDGER, "w", encoding="utf-8"), ensure_ascii=False)


PROFILE_DIR = os.path.join("browser_data", "cdp_xhs_user_data_dir")


def clean_stale_profile():
    """清掉上次进程被强杀留下的 Chrome 单例锁。

    不清的话 Chrome 会认为配置目录仍被占用，直接起不来，
    CDP 启动等满 60s 超时后回退到 Playwright 内置浏览器（本项目未安装）而失败。
    """
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        p = os.path.join(PROFILE_DIR, name)
        try:
            if os.path.islink(p) or os.path.isfile(p):
                os.unlink(p)
        except OSError:
            pass


async def run_batch(urls):
    """跑一批，返回本批成功写入的条数。"""
    clean_stale_profile()
    config.CRAWLER_TYPE = "detail"
    config.LOGIN_TYPE = "cookie"
    config.XHS_SPECIFIED_NOTE_URL_LIST = urls
    config.ENABLE_GET_COMMENTS = True
    config.MAX_CONCURRENCY_NUM = 1
    crawler_type_var.set("detail")

    from media_platform.xhs import XiaoHongShuCrawler

    before = len(done_ids())
    crawler = XiaoHongShuCrawler()
    await crawler.start()
    after = len(done_ids())
    return after - before


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-size", type=int, default=40, help="每批条数")
    ap.add_argument("--cooldown", type=int, default=90, help="批间冷却秒数")
    ap.add_argument("--gap", type=int, default=6, help="单条间隔秒数")
    ap.add_argument("--max-notes", type=int, default=0, help="本次最多补采多少条，0 为不限")
    ap.add_argument("--max-empty-rounds", type=int, default=2, help="连续零产出多少批后熔断")
    args = ap.parse_args()

    config.CRAWLER_MAX_SLEEP_SEC = args.gap

    cands = load_candidates()
    done = done_ids()
    old = old_pipeline_ids()
    failed = load_failed()

    pending = [
        c for c in cands
        if c["note_id"] not in done and c["note_id"] not in old and c["note_id"] not in failed
    ]

    log(f"候选 {len(cands)} | 新管线已采 {len(done)} | 旧管线已有 {len(old)} | 历史失败 {len(failed)}")
    log(f"待补采 {len(pending)} 条；批次 {args.batch_size}，批间冷却 {args.cooldown}s，单条间隔 {args.gap}s")

    if args.max_notes:
        pending = pending[: args.max_notes]
        log(f"本次上限 {args.max_notes} 条")

    empty_rounds = 0
    total_ok = 0
    round_no = 0

    while pending:
        round_no += 1
        batch = pending[: args.batch_size]
        pending = pending[args.batch_size:]
        log(f"=== 第 {round_no} 批：{len(batch)} 条（剩余待跑 {len(pending)}） ===")

        infra_error = False
        try:
            ok = asyncio.run(run_batch([build_url(c) for c in batch]))
        except Exception as e:
            log(f"批次异常：{type(e).__name__}: {str(e)[:160]}")
            ok = 0
            infra_error = True

        total_ok += ok
        log(f"第 {round_no} 批完成：成功 {ok}/{len(batch)}，累计 {total_ok}")

        if ok == 0:
            empty_rounds += 1
            if infra_error:
                # 基础设施故障（浏览器起不来等）不代表这些笔记抓不到，
                # 不能写进失败台账，否则会被永久跳过。
                log("批间异常导致的零产出，不计入失败台账，稍后重试这批")
                pending = batch + pending
            else:
                # 本批全部失败，记入失败台账，避免整轮重来
                for c in batch:
                    failed.add(c["note_id"])
                save_failed(failed)
            if empty_rounds >= args.max_empty_rounds:
                log(f"连续 {empty_rounds} 批零产出，疑似触发风控，停止。")
                break
        else:
            empty_rounds = 0
            # 成功的从失败台账里剔除
            failed -= {c["note_id"] for c in batch}
            save_failed(failed)

        if pending:
            log(f"冷却 {args.cooldown}s ...")
            time.sleep(args.cooldown)

    log(f"全部结束：本次新增 {total_ok} 条；剩余待补采 {len(pending)} 条")


if __name__ == "__main__":
    main()
