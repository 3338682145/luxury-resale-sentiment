#!/bin/bash
# 补采守护：进程被意外杀掉（沙箱休眠/浏览器崩溃）后自动续跑。
# 断点由 run_xhs_detail.py 自己维护（已写入 jsonl 的 note_id 自动跳过），
# 所以这里只需要"死了就再拉起来"。

cd "$(dirname "$0")" || exit 1
mkdir -p logs

MAX_ROUND=30
ROUND=0

while [ $ROUND -lt $MAX_ROUND ]; do
    ROUND=$((ROUND + 1))
    echo "[$(date '+%F %T')] === 守护第 ${ROUND} 轮启动 ===" >> logs/daemon.log

    # 每轮先确保虚拟显示在
    if ! ps aux | grep -q "[X]vfb :99"; then
        rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null
        (Xvfb :99 -screen 0 1440x900x24 -nolisten tcp > /tmp/xvfb.log 2>&1 &)
        sleep 3
        echo "[$(date '+%F %T')] Xvfb 已重启" >> logs/daemon.log
    fi

    pkill -9 -x chrome 2>/dev/null
    sleep 2

    DISPLAY=:99 stdbuf -oL uv run python run_xhs_detail.py \
        --batch-size 40 --cooldown 90 >> "logs/collect_round${ROUND}.log" 2>&1
    RC=$?

    echo "[$(date '+%F %T')] 第 ${ROUND} 轮退出 rc=${RC}" >> logs/daemon.log

    # 正常跑完（没有待补采）时脚本会正常退出，检查是否还有剩余
    LEFT=$(DISPLAY=:99 uv run python - <<'PY' 2>/dev/null
import json, glob
cand = [json.loads(l) for l in open('/workspace/二奢舆情采集/data/candidates.jsonl', encoding='utf-8') if l.strip()]
done = set()
for p in glob.glob('data/xhs/jsonl/detail_contents_*.jsonl'):
    for l in open(p, encoding='utf-8'):
        if l.strip():
            try: done.add(json.loads(l)['note_id'])
            except Exception: pass
try:
    old = set(json.load(open('/workspace/二奢舆情采集/data/state.json'))['detailed'].keys())
except Exception:
    old = set()
try:
    failed = set(json.load(open('data/xhs/detail_failed.json')))
except Exception:
    failed = set()
print(sum(1 for c in cand if c['note_id'] not in done and c['note_id'] not in old and c['note_id'] not in failed))
PY
)
    echo "[$(date '+%F %T')] 剩余待补采: ${LEFT:-未知}" >> logs/daemon.log
    if [ "${LEFT:-1}" = "0" ]; then
        echo "[$(date '+%F %T')] 已全部补采完成" >> logs/daemon.log
        break
    fi
    sleep 30
done

echo "[$(date '+%F %T')] 守护结束" >> logs/daemon.log
