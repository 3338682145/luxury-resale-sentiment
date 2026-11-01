#!/bin/bash
# 采集总管：跑采集 + 每 25 分钟吐一行进度快照（供巡检唤醒用）
# 设计要点：
#   1) run_xhs_detail.py 每轮 40 条，正常退出后立刻拉下一轮（断点续跑）
#   2) 每轮前清 SingletonLock，避免 Chrome 拒绝启动
#   3) 连续两轮零产出 -> 熔断，退出（风控信号，不硬刷）
#   4) 进度用独立计时器打印，避免每轮都唤醒

cd /workspace/MediaCrawler || exit 1
mkdir -p logs
LEDGER=logs/supervise.log
SNAP_INTERVAL=1500   # 25 分钟

# 只写日志文件，不进 stdout（stdout 留给进度快照，避免频繁唤醒巡检）
say() { echo "[$(date '+%F %T')] $*" >> "$LEDGER"; }

ensure_xvfb() {
    if ! pgrep -f "Xvfb :99" >/dev/null 2>&1; then
        rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null
        Xvfb :99 -screen 0 1440x900x24 -nolisten tcp > /tmp/xvfb.log 2>&1 &
        sleep 3
        say "Xvfb 已拉起"
    fi
}

# ---- 进度计时器（背景），只在有采集动作时才报 ----
(
  while true; do
    sleep "$SNAP_INTERVAL"
    python3 progress.py 2>/dev/null
  done
) &
TIMER=$!
trap 'kill $TIMER 2>/dev/null' EXIT INT TERM

ROUND=0
ZERO_STREAK=0
say "=== 总管启动 pid=$$ ==="
echo "{\"ts\":\"$(date '+%H:%M:%S')\",\"event\":\"start\",\"note\":\"supervise up\"}"
python3 progress.py 2>/dev/null

while [ $ROUND -lt 40 ]; do
    ROUND=$((ROUND + 1))
    ensure_xvfb

    BEFORE=$(python3 progress.py 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin)['new'])" 2>/dev/null || echo 0)
    LEFT=$(python3 progress.py 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin)['left'])" 2>/dev/null || echo 1)

    if [ "${LEFT:-1}" -le 0 ]; then
        say "已无待补采，总管收工"
        echo "{\"ts\":\"$(date '+%H:%M:%S')\",\"event\":\"done\",\"left\":0}"
        break
    fi

    rm -f browser_data/cdp_xhs_user_data_dir/Singleton* 2>/dev/null
    pkill -9 -x chrome 2>/dev/null
    sleep 2

    say "第 ${ROUND} 轮开跑，待补采 ${LEFT}"
    DISPLAY=:99 stdbuf -oL uv run python run_xhs_detail.py \
        --batch-size 40 --cooldown 90 >> "logs/collect_round${ROUND}.log" 2>&1
    RC=$?

    AFTER=$(python3 progress.py 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin)['new'])" 2>/dev/null || echo 0)
    GAIN=$((AFTER - BEFORE))
    say "第 ${ROUND} 轮结束 rc=${RC}，新增 ${GAIN}，累计 ${AFTER}"

    if [ "$GAIN" -le 0 ]; then
        ZERO_STREAK=$((ZERO_STREAK + 1))
        say "零产出 ${ZERO_STREAK} 次"
        if [ $ZERO_STREAK -ge 2 ]; then
            say "连续两轮零产出，疑似风控，熔断退出"
            echo "{\"ts\":\"$(date '+%H:%M:%S')\",\"event\":\"circuit_break\",\"zero_streak\":$ZERO_STREAK}"
            break
        fi
    else
        ZERO_STREAK=0
    fi
    sleep 30
done

say "=== 总管结束，共 ${ROUND} 轮 ==="
