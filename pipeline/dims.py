#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""二奢舆情：维度抽取 + 模块缺口报表。

任务书口径：
  品类：箱包/腕表/首饰(不含纯金)/奢品与潮流鞋服/配饰
  业务：仅收 C2B 回收；C2C 纠纷仅当涉及验货宝
  时间：2024-01-01 起，优先近 12 个月
  线：爱回收 包表首饰→值耀；鞋服配饰→第二回合（其邮寄回收已于 2026-07-09 下线）

用法：
  python3 pipeline/dims.py --report            # 看现有 217 条 + 新采数据的模块缺口
  python3 pipeline/dims.py --tag data/guest/notes_guest.jsonl   # 给 jsonl 打维度
"""
import argparse
import collections
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from keywords import (LUX_BAG, LUX_WATCH, LUX_JEWEL, LUX_FASHION, LUX_ACC,  # noqa: E402
                      LUX_ALL, GOLD_BULLION, EXCLUDE_3C)

CATS = {"箱包": LUX_BAG, "腕表": LUX_WATCH, "首饰": LUX_JEWEL,
        "鞋服": LUX_FASHION, "配饰": LUX_ACC}

# 回收方式
REC_MAIL = ["邮寄", "寄过去", "寄给", "快递", "顺丰", "寄件", "寄出", "到付", "包裹"]
REC_STORE = ["门店", "到店", "实体店", "柜台", "面交", "现场"]
REC_DOOR = ["上门", "师傅来", "快递员上门", "上门取件"]

# 我方相关线索（不得联系任何人，仅标记）
OURS_WORDS = ["第二回合", "值耀", "万物新生", "爱回收", "拍怕", "拍拍严选"]

# 实名刑事指控：只记链接、不摘正文、报老万
CRIM_WORDS = ["刑事", "诈骗罪", "刑拘", "判决书", "立案侦查", "起诉书", "派出所", "民警"]

# 模块目标（任务书）
TARGETS = [
    ("P0", "A", "爱回收二奢回收负面", 60),
    ("P0", "A", "转转二奢回收负面", 60),
    ("P0", "B", "闲鱼回收(含省心卖)+验货宝 二奢负面", 60),
    ("P1", "C", "三平台公开回收规则与用户协议对标", 3),
    ("P1", "D", "闲鱼二奢买卖家观察（独立成文）", 1),
    ("P1", "E", "第二回合 / SNAKE 公开负面自查", 0),
    ("P2", "F", "红布林 / 心上等对照案例", 30),
]


def hits(text, words):
    return [w for w in words if w in text]


def detect_cat(text):
    """返回 (主品类, 命中详情 dict, 是否纯金疑似)"""
    detail = {c: hits(text, ws) for c, ws in CATS.items()}
    detail = {c: v for c, v in detail.items() if v}
    gold = hits(text, GOLD_BULLION)
    if not detail:
        return ("未识别", {}, bool(gold))
    primary = sorted(detail.items(), key=lambda kv: -len(kv[1]))[0][0]
    return (primary, detail, bool(gold) and primary == "首饰")


def detect_recovery(text):
    m, s, d = hits(text, REC_MAIL), hits(text, REC_STORE), hits(text, REC_DOOR)
    got = [n for n, v in (("邮寄", m), ("门店", s), ("上门", d)) if v]
    if not got:
        return "不明", []
    # 上门优先于门店（"门店+上门"常见于同城）
    if "上门" in got:
        return "上门", got
    return got[0], got


def business_line(platform, cat):
    if "爱回收" in platform:
        return "值耀" if cat in ("箱包", "腕表", "首饰") else (
            "第二回合" if cat in ("鞋服", "配饰") else "未定")
    if "第二回合" in platform:
        return "第二回合"
    if "值耀" in platform:
        return "值耀"
    return ""


def ours_tag(platform, cat, text):
    if not ("爱回收" in platform or hits(text, ["第二回合", "值耀", "万物新生"])):
        return ""
    if platform and "爱回收" in platform and cat in ("箱包", "腕表", "首饰", "鞋服", "配饰"):
        return "疑似"
    if hits(text, ["第二回合", "值耀"]):
        return "疑似"
    return ""


def criminal_tag(text):
    return "疑似" if hits(text, CRIM_WORDS) else ""


def tag(platform, title, desc, tags=""):
    text = " ".join([title or "", desc or "", tags or ""])
    cat, detail, gold = detect_cat(text)
    rec, rec_hits = detect_recovery(text)
    return {
        "品类": cat,
        "品类命中": detail,
        "纯金疑似": gold,
        "回收方式": rec,
        "回收方式依据": rec_hits,
        "业务线": business_line(platform, cat),
        "我方相关": ours_tag(platform, cat, text),
        "刑事指控": criminal_tag(text),
        "3C噪音": "是" if (hits(text, EXCLUDE_3C) and cat == "未识别") else "",
    }


# ---------------------------------------------------------------- 报表
def load_cases():
    p = os.path.join(ROOT, "outputs/案例库_入库_217条.csv")
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_guest():
    p = os.path.join(ROOT, "data/guest/notes_guest.jsonl")
    out = []
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("status") == "ok":
                    out.append(d)
    return out


def report():
    cases = load_cases()
    for r in cases:
        t = tag(r.get("平台", ""), r.get("标题", ""), r.get("正文摘要", ""))
        r.update(t)
    plat = collections.Counter(r["平台"] for r in cases)
    print("== 现有案例库 217 条 ==")
    print("平台:", dict(plat))
    print("品类:", dict(collections.Counter(r["品类"] for r in cases)))
    print("回收方式:", dict(collections.Counter(r["回收方式"] for r in cases)))
    print("分级:", dict(collections.Counter(r["分级"] for r in cases)))
    print("业务线:", dict(collections.Counter(r["业务线"] for r in cases if r["业务线"])))
    print("我方相关=疑似:", sum(1 for r in cases if r["我方相关"] == "疑似"))
    print("3C噪音(未识别品类且命中3C词):", sum(1 for r in cases if r["3C噪音"]))
    print("刑事指控=疑似:", sum(1 for r in cases if r["刑事指控"]))

    print("\n== 模块达成度 ==")
    print(f"{'级别':<4}{'模块':<5}{'目标':<8}{'现有':<8}{'缺口':<6}说明")
    got = {
        "A-爱回收": sum(1 for r in cases if r["平台"] == "爱回收"),
        "A-转转": sum(1 for r in cases if r["平台"] == "转转"),
        "B-闲鱼": sum(1 for r in cases if r["平台"] == "闲鱼"),
        "C": 0, "D": 0,
        "E": sum(1 for r in cases if r["平台"] in ("第二回合", "SNAKE", "值耀")),
        "F": sum(1 for r in cases if r["平台"] in ("红布林", "心上")),
    }
    mapping = [("P0", "A", got["A-爱回收"], 60, "爱回收二奢回收负面"),
               ("P0", "A", got["A-转转"], 60, "转转二奢回收负面"),
               ("P0", "B", got["B-闲鱼"], 60, "闲鱼回收+验货宝二奢负面"),
               ("P1", "C", got["C"], 3, "三平台规则对标（每家1份）"),
               ("P1", "D", got["D"], 1, "闲鱼买卖家观察（独立成文）"),
               ("P1", "E", got["E"], 0, "第二回合/SNAKE 公开负面（全量）"),
               ("P2", "F", got["F"], 30, "红布林/心上等对照案例")]
    for lv, mod, have, tgt, note in mapping:
        gap = "-" if not tgt else max(0, tgt - have)
        print(f"{lv:<4}{mod:<5}{tgt or '全量':<8}{have:<8}{gap!s:<6}{note}")

    g = load_guest()
    if g:
        print("\n== 新采（免cookie）%d 条 ==" % len(g))
        print("品类:", dict(collections.Counter(tag(x.get("module", ""), x["title"], x["desc"],
                                                    " ".join(x.get("tags") or []))["品类"] for x in g)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--tag")
    a = ap.parse_args()
    if a.tag:
        with open(a.tag, encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                if d.get("status") != "ok":
                    continue
                d.update(tag(d.get("module", ""), d["title"], d["desc"],
                             " ".join(d.get("tags") or [])))
                print(json.dumps(d, ensure_ascii=False))
    else:
        report()
