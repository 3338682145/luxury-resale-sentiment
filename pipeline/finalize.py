#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按人工复核结果生成正式入库文件。

抽检结论：
  A 级：全量核对，准确率 97%
  C 级：全量核对，准确率 83%
  B/D 级：抽检准确率仅 50-58%，不做整级入库，
          改由人工逐条阅读后以白名单方式挑选真负面样本
"""
import json
import os
from collections import Counter

BASE = "/workspace/二奢舆情采集"
CLEAN = os.path.join(BASE, "data/clean")

# A/C 级中人工判定为误判的（剔除）
BLACKLIST_TITLES = [
    "告别上海二奢店压价PUA，转转这波我给满分",
    "换了手机 到苹果授权店把17pro 5000出掉了",
    "感谢验货宝，是我太贪心了",
    "到底要不要走验货宝",
    "奢侈品鉴定小诀窍",
    "Apple trade in安全下车",
    "亲测有效",
    "大家避雷一下xhs上的奢饰品回收",
    "体验爱回收！告别扯皮内耗",
    "转转上门回收手机会压价吗？这事我有发言权",
    "西安BOSS直聘｜爱回收这个招聘套路大家快跑！",
    "怕处理旧物被压价❓转转上门回收让我改观了",
    "防骗锦囊！记住这3点，骗子全退散！！",
    "太好了，是维权指南，我们有救了",
    "平台维权封神！5 步拿回 500 元补偿",
    "佛山转转二手车避雷",
    "紧急避雷贴！差点被骗",
    "壁垒xy新型诈骗…",
    "出货需谨慎",
    "深圳二奢回收还有没有王法！白白坑我1w",
    "转转回收旧iPhone13会压价吗？",
    "转转上收手机会压价吗？",
    "转转二手机购机老手的避坑指南分享",
]

# B/D 级中人工逐条确认属于真负面的（白名单放行）
WHITELIST_TITLES = [
    # ---- B 级 36 条 ----
    "谢谢闲鱼假装个人的二奢店送的验货宝",
    "咸鱼出包险被宰",
    "对闲鱼彻底失望了",
    "闲鱼验货宝 以假乱真",
    "闲鱼慎出包",
    "转转客服来电！全程录音",
    "闲鱼验货宝鉴定错误，几个月不赔偿",
    "我Fendi正品围巾",
    "转转出谷子，惨遭ysg碰瓷",
    "咸鱼验货宝你没事吧？我专柜买的",
    "各位慎用闲鱼验货宝吧",
    "闲鱼二奢烂透了",
    "记录下自己闲鱼卖二奢经历",
    "闲鱼验货宝售假",
    "闲鱼卖包经历，最后亲自到线下奢品回收店成交。",
    "远离咸鱼二奢",
    "举报闲鱼翻新包商家失败",
    "转转，一次糟糕的购物体验",
    "爱回收镜头开箱那一刻我人都傻了",
    "千万不要在闲鱼上出售个人二奢！！",
    "在转转买二手机要小心，到手发现屏幕有划痕",
    "闲鱼验货宝刀 举报起来！",
    "咸鱼验货宝真的会验货吗",
    "转转复检骚操作！砍低价单，转头加价重卖",
    "下次我旧衣服就算扔了，也不送爱回收了",
    "闲鱼验货宝水平能力有限",
    "爱回收你真可以！！",
    "转转拿换屏iphone当原装卖！",
    "闲鱼卖包血泪教训",
    "jd爱回收吃相太难看！！！",
    "小心“京东爱回收”黑了你的数码产品",
    "转转买到翻新机",
    "闲鱼真的是不适合出包包了",
    "爱回收卖浸液电脑！7000多买的维修费15000",
    "爱回收，怎么怂了呢",
    "货不对板 转转小法庭强制打款",
    # ---- D 级 26 条 ----
    "太可怕了！tiffany项链被闲鱼验货宝调包后续",
    "闲鱼二奢交易烂透了，贩子猖獗",
    "某鱼整这个功能，真的太够八逆天了",
    "咸鱼出包遇到二奢贩子千万不要妥协！",
    "二奢装个人买家 被手刀",
    "二手机翻车，某转平台说不删视频200都不给",
    "验货宝费用追溯成功，坚持就会有结果",
    "超过 1.5w 的包 千万不要闲鱼出！！",
    "避雷苏州中银惠龙某回收中心",
    "咸鱼购买speedy30历程",
    "大家如果要卖闲置高档包的话，千万不要去闲鱼",
    "京东爱回收因为这个点刀500块",
    "维权大结局！拿到了5000补偿且不用删帖",
    "爱回收，你还有没有天理！！！",
    "🐟验货后直接给我🔪6000",
    "😡曝光闲鱼「赏欣**」北京实体店",
    "黄鱼买家可以不经卖家同意直接退货？！",
    "这种哪里可以投诉吗",
    "到手刀概率 100%",
    "送验货宝的包碰水了",
    "闲鱼想要乱开价 就要做好保护妈妈的准备",
    "爱回收果然专业做鞋服啊！这报价太感人了",
    "转转红布林你们就这么对待你们的客户",
    "支持转转关自由市场，个人真的容易买到假",
    "这么好看的老爹鞋竟然只给150块的回收价",
    "我们的困境源于我们的妥协",
    "关于转转质保售后怎样 后续来了！！",
    "转转平台购物踩大雷！买“零售机”收到“官换机",
]


def hit(title, table):
    return any(title.startswith(t) for t in table)


rows = [json.loads(l) for l in open(os.path.join(CLEAN, "cases_clean.jsonl"), encoding="utf-8")]

final, hold, dropped = [], [], []
for r in rows:
    t = r["title"]
    if hit(t, BLACKLIST_TITLES):
        r["drop_reason"] = "人工复核误判"
        dropped.append(r)
        continue
    if r["level"] in ("A", "C") or hit(t, WHITELIST_TITLES):
        r["entry_basis"] = "规则分级" if r["level"] in ("A", "C") else "人工白名单"
        final.append(r)
        continue
    hold.append(r)

order = {"A": 0, "C": 1, "B": 2, "D": 3}
final.sort(key=lambda x: (order.get(x["level"], 9), -x["liked"]))

with open(os.path.join(CLEAN, "cases_final.jsonl"), "w", encoding="utf-8") as f:
    for r in final:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
with open(os.path.join(CLEAN, "cases_hold.jsonl"), "w", encoding="utf-8") as f:
    for r in hold:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
with open(os.path.join(CLEAN, "manual_dropped.jsonl"), "w", encoding="utf-8") as f:
    for r in dropped:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

report = {
    "入库": len(final),
    "待复核池": len(hold),
    "人工剔除": len(dropped),
    "入库平台分布": dict(Counter(r["platform"] for r in final)),
    "入库分级": dict(Counter(r["level"] for r in final)),
    "入库依据": dict(Counter(r["entry_basis"] for r in final)),
    "入库负面类型": dict(Counter(d for r in final for d in r["neg_dims"])),
    "带评论证据": sum(1 for r in final if r["evidence_count"] > 0),
    "总互动量": sum(r["liked"] for r in final),
}
print(json.dumps(report, ensure_ascii=False, indent=2))
