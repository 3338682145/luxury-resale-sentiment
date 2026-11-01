#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""二奢舆情案例清洗：合并新旧管线 -> 平台归属 -> 负面判定 -> 剔除软文/误归。

输出：
  data/clean/cases_clean.jsonl   待入库案例（含置信分级与证据）
  data/clean/reject.jsonl        剔除清单（含原因，便于复核）
  data/clean/stats.json          清洗统计
"""
import glob
import json
import os
import re
import time

BASE = "/workspace/二奢舆情采集"
MC = "/workspace/MediaCrawler"
OUT = os.path.join(BASE, "data/clean")
os.makedirs(OUT, exist_ok=True)

# ---------------- 词表 ----------------

# 平台名误命中噪音，先剔除再计数（"转转乐""转转鞋""旋转纽扣"等非平台用法）
PLATFORM_NOISE = {
    "转转": ["转转乐", "转转鞋", "转转转", "旋转", "转转运", "转圈", "转盘", "转转椅",
           "转转门", "转转杯", "转转火锅", "转一转", "转转热卤", "转转小火锅",
           "转转串串", "转转烤", "转转麻辣", "转转小馆", "转转食堂"],
    "闲鱼": ["咸鱼翻身", "咸鱼也要", "咸鱼一条"],
    "爱回收": [],
}

PLATFORM_WORDS = {
    "爱回收": ["爱回收", "万物新生", "爱回收严选"],
    "转转": ["转转"],
    "闲鱼": ["闲鱼", "咸鱼"],
}

# 负面维度：类型 -> 关键词
NEG_DIMENSIONS = {
    "压价到手刀": ["到手刀", "到手砍", "压价", "砍价", "跳水", "临时降价", "验完价",
                "说好", "一口价", "报价低", "给这么点", "只给", "低价收", "杀价",
                "回收价低", "亏死", "亏大"],
    "质检鉴定": ["质检", "鉴定", "假货", "假包", "翻新", "瑕疵", "成色不符", "成色差",
             "掉包", "换件", "拆机", "私自拆", "划痕", "破损", "以次充好", "不是正品",
             "验货", "查验", "损坏"],
    "售后维权": ["维权", "投诉", "12315", "消协", "市场监管局", "客服不", "没人管",
             "不处理", "不解决", "踢皮球", "扯皮", "推诿", "退款", "退货", "拒赔",
             "不予理赔", "结案", "拖延", "态度差", "冷处理", "拉黑"],
    "隐私骚扰": ["骚扰", "泄露", "电话轰炸", "短信轰炸", "个人信息", "隐私"],
    "欺诈套路": ["骗", "坑", "套路", "黑心", "避雷", "翻车", "踩雷", "被骗", "坑人",
             "欺诈", "虚假", "诱导", "霸王条款", "陷阱"],
    "物流损毁": ["丢件", "物流损坏", "运输损坏", "快递丢", "包装破损", "顺丰"],
}

# 软文/商家引流
PROMO_WORDS = ["上门回收", "高价回收", "回收报价", "免费鉴定", "免费估价", "全国回收",
               "诚信回收", "长期回收", "专业回收", "加v", "加V", "vx", "VX", "微信",
               "私信我", "滴滴我", "戳我", "咨询我", "欢迎咨询", "本店", "我们家回收",
               "回收热线", "门店地址"]

# 商家昵称特征
MERCHANT_NICK = ["回收", "奢", "当", "珠宝", "名表", "腕表", "鉴定", "二手"]

# 行业观察/创业分享（非投诉）
INDUSTRY_WORDS = ["创业", "商业模式", "认知", "赛道", "行业分析", "利润空间", "生意经",
                  "开店", "加盟", "供应链", "如何做", "能不能做", "赚钱吗"]

# 第一人称受害表述
VICTIM_PATTERNS = ["我被", "我的", "给我", "坑我", "骗我", "我买", "我卖", "我寄",
                   "我送", "我拿", "联系我", "我投诉", "我遇到", "亲身", "经历",
                   "本人", "气死我", "恶心"]

# 竞品平台：主体是这些的，不属于本次三家，剔除
OTHER_PLATFORMS = ["红布林", "只二", "妃鱼", "心上", "胖虎", "Plum", "会循环",
                   "奢收多", "爱奢", "奢当家", "二手奢侈品店", "二奢店", "线下店"]

# 教程/攻略帖（不是投诉）
HOWTO_WORDS = ["第一步", "第二步", "第三步", "教你", "攻略", "教程", "流程如下",
               "操作步骤", "如何维权", "怎么投诉", "话术"]

# 营销/软文话术（出现即高度疑似推广）
MARKETING_WORDS = ["代言", "推荐", "真香", "体验感", "拉满", "服务态度", "旗舰店",
                   "探店", "citywalk", "Citywalk", "打卡", "种草", "安利", "必入",
                   "冲冲冲", "绝绝子", "宝藏", "天花板", "yyds", "入手不亏"]

# 标题层面的强负面词（用于主体判定）
TITLE_NEG_WORDS = ["避雷", "坑", "骗", "垃圾", "恶心", "压价", "到手刀", "砍价",
                   "翻车", "踩雷", "维权", "投诉", "黑心", "套路", "差评",
                   "不负责", "离谱", "耍", "霸王", "气死", "避坑", "千万别",
                   "上当", "欺诈", "虚假", "拒赔", "扯皮", "踢皮球"]

# 标题正面/感叹式反问（"冤啊""靠谱吗"常是反讽或提问，需人工）
TITLE_SOFT_WORDS = ["改观", "真香", "推荐", "靠谱", "划算", "满意", "不错",
                    "找到了归宿", "太顶了", "神器", "满分", "给力", "值了",
                    "很顺利", "体验不错", "值得", "好评"]

# 否定式表述：负面词被否定，实际是正面（"没到手刀太爽了"）
NEGATION_PATTERNS = ["没到手刀", "没有到手刀", "没踩坑", "没踩雷", "没有踩坑",
                     "没被坑", "没被压价", "没压价", "没上当", "没被骗",
                     "不踩雷", "没有翻车", "没翻车", "不坑", "没套路"]

# 对比软文（踩线下/踩竞品，抬自家）
COMPARE_WORDS = ["vs", "VS", "对比", "谁更", "一目了然", "完胜", "吊打"]

# 强正面/软文表述（夸平台，含 2 个以上即判软文）
STRONG_POSITIVE = ["体验很好", "体验感极佳", "很专业", "很nice", "报价合理", "报价很",
                   "没有压价", "不会故意压价", "不用担心被压价", "不存在压价",
                   "到账很快", "马上打款", "秒到账", "百家竞价", "全国竞价",
                   "服务很好", "服务态度", "态度很好", "很满意", "值得信赖",
                   "强烈推荐", "真心安利", "救了我", "被惊艳到", "直接惊艳",
                   "秒了", "给力", "很靠谱", "省心", "透明", "没有套路",
                   "没有任何套路", "高效", "仪式感", "拉满", "高级感",
                   "不压价", "没有压价", "不扯皮", "良心", "改观", "一步到位"]

# 标题即教程（"退款其实很简单"这类不是投诉）
TITLE_HOWTO = ["其实很简单", "教程", "攻略", "教你", "干货", "流程如下", "操作步骤"]

POSITIVE_WORDS = ["很满意", "推荐", "靠谱", "方便", "服务好", "点赞", "真香",
                  "顺利", "专业", "效率高", "不错", "值得信赖", "体验好"]


def norm(s):
    return (s or "").strip()


def parse_num(v):
    """解析 '1.7万' / '12' / '' 之类的互动数。"""
    if v is None:
        return 0
    s = str(v).strip().replace(",", "")
    if not s:
        return 0
    try:
        if "万" in s:
            return int(float(s.replace("万", "")) * 10000)
        if "w" in s.lower():
            return int(float(s.lower().replace("w", "")) * 10000)
        return int(float(s))
    except Exception:
        return 0


def detect_platforms(text):
    hits = {}
    for plat, words in PLATFORM_WORDS.items():
        cleaned = text
        for bad in PLATFORM_NOISE.get(plat, []):
            cleaned = cleaned.replace(bad, "")
        cnt = 0
        for w in words:
            cnt += cleaned.count(w)
        if cnt:
            hits[plat] = cnt
    return hits


def score_negative(text):
    dims = {}
    total = 0
    for dim, words in NEG_DIMENSIONS.items():
        hit = [w for w in words if w in text]
        if hit:
            dims[dim] = hit
            total += len(hit)
    return dims, total


def has_victim(text):
    return any(p in text for p in VICTIM_PATTERNS)


def is_promo(text, nick):
    promo_hits = [w for w in PROMO_WORDS if w in text]
    nick_hit = any(w in nick for w in MERCHANT_NICK)
    # 强引流：≥2 个 promo 词；或 1 个 + 商家昵称
    if len(promo_hits) >= 2:
        return True, promo_hits
    if promo_hits and nick_hit:
        return True, promo_hits
    return False, promo_hits


def is_industry(text):
    hits = [w for w in INDUSTRY_WORDS if w in text]
    return (len(hits) >= 2), hits


def load_new():
    rows = []
    seen = set()
    files = sorted(glob.glob(os.path.join(MC, "data/xhs/jsonl/*contents*.jsonl")))
    for p in files:
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
                if not nid or nid in seen:
                    continue
                seen.add(nid)
                rows.append({
                    "note_id": nid,
                    "title": norm(d.get("title")),
                    "desc": norm(d.get("desc")),
                    "author": norm(d.get("nickname")),
                    "liked": parse_num(d.get("liked_count")),
                    "collected": parse_num(d.get("collected_count")),
                    "comment_count": parse_num(d.get("comment_count")),
                    "url": d.get("note_url") or f"https://www.xiaohongshu.com/explore/{nid}",
                    "publish_ts": d.get("time"),
                    "tags": d.get("tag_list") or "",
                    "type": d.get("type"),
                    "src": "new",
                })
    return rows


def load_old_cases():
    p = os.path.join(BASE, "data/cases.jsonl")
    rows = []
    if not os.path.exists(p):
        return rows
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            comments = d.get("comments") or []
            if isinstance(comments, str):
                comments = []
            rows.append({
                "note_id": d.get("note_id"),
                "title": norm(d.get("title")),
                "desc": norm(d.get("desc")),
                "author": norm(d.get("author")),
                "liked": parse_num(d.get("liked")),
                "collected": parse_num(d.get("collected")),
                "comment_count": parse_num(d.get("comment_count")),
                "url": d.get("url"),
                "publish_ts": d.get("publish_ts"),
                "tags": "",
                "type": "",
                "src": "old",
            })
    return rows


def load_comments():
    buf = {}
    cfiles = glob.glob(os.path.join(MC, "data/xhs/jsonl/*comments*.jsonl"))
    for p in cfiles:
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
                c = norm(d.get("content"))
                if not nid or not c:
                    continue
                buf.setdefault(nid, []).append({
                    "content": c,
                    "like": parse_num(d.get("like_count")),
                })
    for nid in buf:
        buf[nid].sort(key=lambda x: -x["like"])
    return buf


def judge_subject(title, desc):
    """判定投诉主体平台。标题优先，正文开头次之，全文兜底。"""
    t_plats = detect_platforms(title)
    t_other = [p for p in OTHER_PLATFORMS if p in title]
    if t_other and not t_plats:
        return "", "竞品主体:" + t_other[0], True
    if len(t_plats) == 1:
        return list(t_plats)[0], "标题", False
    if len(t_plats) > 1:
        return "", "标题多平台", True
    head = desc[:80]
    h_plats = detect_platforms(head)
    if len(h_plats) == 1:
        return list(h_plats)[0], "正文开头", False
    if len(h_plats) > 1:
        return "", "开头多平台", True
    b_plats = detect_platforms(title + desc)
    if len(b_plats) == 1:
        return list(b_plats)[0], "正文全文", False
    if len(b_plats) > 1:
        return "", "全文多平台", True
    return "", "未提及", False


def clean_len(text):
    """去掉话题标签与符号后的实质字数。"""
    t = re.sub(r"#[^#]*\[话题\]#|#[^#\s]+#?", "", text)
    t = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", t)
    return len(t)


def main():
    cand = {}
    with open(os.path.join(BASE, "data/candidates_v2.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                cand[d["note_id"]] = d

    rows = load_new() + load_old_cases()
    seen = set()
    uniq = []
    for r in rows:
        if r["note_id"] and r["note_id"] not in seen:
            seen.add(r["note_id"])
            uniq.append(r)

    comments = load_comments()

    kept, rejected = [], []
    for r in uniq:
        title, desc = r["title"], r["desc"]
        body = f"{title}\n{desc}"
        cand_row = cand.get(r["note_id"], {})
        cand_module = cand_row.get("module", "")

        # ---- 主体判定 ----
        plat, subj_method, conflict = judge_subject(title, desc)

        # 标题 / 开头负面（比全文匹配可靠得多）
        t_neg = [w for w in TITLE_NEG_WORDS if w in title]
        h_dims, h_neg = score_negative(title + desc[:120])
        dims, neg_total = score_negative(body)
        victim = has_victim(body)
        promo, promo_hits = is_promo(body, r["author"])
        industry, ind_hits = is_industry(body)
        pos_hits = [w for w in POSITIVE_WORDS if w in body]
        mkt_hits = [w for w in MARKETING_WORDS if w in body]
        strong_pos = [w for w in STRONG_POSITIVE if w in body]
        t_howto = [w for w in TITLE_HOWTO if w in title]
        howto_hits = [w for w in HOWTO_WORDS if w in body]
        t_soft = [w for w in TITLE_SOFT_WORDS if w in title]
        t_negate = [w for w in NEGATION_PATTERNS if w in title]
        t_compare = [w for w in COMPARE_WORDS if w in title]
        real_len = clean_len(desc) + clean_len(title)

        # 评论区
        ev_all = comments.get(r["note_id"], [])
        c_text = "\n".join(c["content"] for c in ev_all[:40])
        c_dims, c_neg = score_negative(c_text)
        c_plats = detect_platforms(c_text)

        # ---- 剔除规则（按优先级）----
        reason = None
        if real_len < 45:
            reason = f"信息量不足:{real_len}字"
        elif promo:
            reason = f"商家引流:{','.join(promo_hits[:3])}"
        elif len(mkt_hits) >= 2 and not t_neg:
            reason = f"营销话术:{','.join(mkt_hits[:3])}"
        elif len(howto_hits) >= 2 and not victim:
            reason = f"教程帖:{','.join(howto_hits[:2])}"
        elif t_howto:
            reason = f"标题为教程/经验总结:{t_howto[0]}"
        elif len(strong_pos) >= 2:
            reason = f"平台软文:{','.join(strong_pos[:3])}"
        elif industry and neg_total <= 2 and not victim:
            reason = f"行业观察非投诉:{','.join(ind_hits[:2])}"
        elif conflict:
            reason = subj_method
        elif not plat:
            reason = "未判定出投诉主体平台"
        elif not t_neg and h_neg == 0:
            reason = "标题及开头均无负面"
        elif t_negate:
            reason = f"否定式表述(实为正面):{t_negate[0]}"
        elif t_soft and not t_neg:
            reason = f"标题正面倾向:{','.join(t_soft[:2])}"
        elif t_compare and plat:
            reason = f"对比软文:{t_compare[0]}"
        elif ("吗？" in title or "吗?" in title or "?" in title[-8:]) and not t_neg:
            reason = "提问咨询帖"

        if reason:
            rejected.append({**r, "reason": reason, "cand_module": cand_module,
                             "c_neg": c_neg})
            continue

        # ---- 置信分级 ----
        title_plat = bool(detect_platforms(title))
        if t_neg and title_plat:
            level = "A"           # 标题同时含平台名与负面词
        elif title_plat and h_neg >= 2:
            level = "B"           # 标题点名平台，开头有实质负面
        elif plat and h_neg >= 2:
            level = "C"           # 正文开头点名平台且有负面
        elif plat and h_neg >= 1:
            level = "D"
        else:
            level = "E"

        neg_dims_final = list(h_dims.keys()) or list(dims.keys())
        kept.append({
            **r,
            "platform": plat,
            "platform_method": subj_method,
            "cand_module": cand_module,
            "title_neg": t_neg,
            "neg_dims": neg_dims_final,
            "neg_hits": h_dims if h_dims else dims,
            "neg_score": h_neg if h_neg else neg_total,
            "comment_neg_score": c_neg,
            "victim": victim,
            "pos_hits": pos_hits,
            "mkt_hits": mkt_hits,
            "real_len": real_len,
            "level": level,
            "evidence_comments": ev_all[:8],
            "evidence_count": len(ev_all),
            "clean_ts": int(time.time()),
        })

    kept.sort(key=lambda x: (x["level"], -x["neg_score"], -x["liked"]))

    with open(os.path.join(OUT, "cases_clean.jsonl"), "w", encoding="utf-8") as f:
        for r in kept:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(OUT, "reject.jsonl"), "w", encoding="utf-8") as f:
        for r in rejected:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    from collections import Counter
    stats = {
        "total_in": len(uniq),
        "kept": len(kept),
        "rejected": len(rejected),
        "by_src": dict(Counter(r["src"] for r in kept)),
        "by_platform": dict(Counter(r["platform"] or "未提及" for r in kept)),
        "by_level": dict(Counter(r["level"] for r in kept)),
        "by_dim": dict(Counter(d for r in kept for d in r["neg_dims"])),
        "reject_reasons": dict(Counter(r["reason"].split(":")[0] for r in rejected)),
        "with_evidence": sum(1 for r in kept if r["evidence_count"] > 0),
    }
    with open(os.path.join(OUT, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
