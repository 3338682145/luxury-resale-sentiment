#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Playwright 扫码登录：自己持有浏览器会话，二维码截图 + 轮询登录结果 + 导出 cookie。"""
import os, time, json, pathlib

SHOT_DIR = '/workspace/二奢舆情采集'
PROFILE = '/tmp/xhs_qr_profile'
COOKIE_OUT = '/root/.xiaohongshu/cookies.json'
COOKIE_ALT = '/tmp/cookies.json'
RESULT = '/tmp/xhs_qr_result.txt'
WAIT = 480

from playwright.sync_api import sync_playwright


def log(m):
    print(f'[{time.strftime("%H:%M:%S")}] {m}', flush=True)


def main():
    if os.path.exists(RESULT):
        os.remove(RESULT)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, headless=False,
            args=['--no-sandbox', '--disable-dev-shm-usage',
                  '--disable-blink-features=AutomationControlled',
                  '--window-size=1280,900'],
            viewport={'width': 1280, 'height': 900},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36',
        )
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.goto('https://www.xiaohongshu.com/login?source=web', timeout=60000)
        time.sleep(5)

        # 若默认不是扫码 tab，点一下
        for t in ('扫码登录', '二维码登录'):
            try:
                el = pg.get_by_text(t, exact=False).first
                if el and el.is_visible():
                    el.click()
                    log(f'点击 {t}')
                    time.sleep(2)
                    break
            except Exception:
                continue

        # 定位二维码元素（img/canvas，取面积最大的可见元素）
        best = None
        for sel in ('img', 'canvas', '.qrcode img', '.qrcode-img'):
            try:
                for el in pg.query_selector_all(sel):
                    if not el.is_visible():
                        continue
                    box = el.bounding_box()
                    if not box or box['width'] < 100 or box['height'] < 100:
                        continue
                    area = box['width'] * box['height']
                    if best is None or area > best[0]:
                        best = (area, el, box)
            except Exception:
                continue

        fn = f'{SHOT_DIR}/扫码登录_{time.strftime("%H%M%S")}.png'
        if best:
            el = best[1]
            try:
                el.screenshot(path=fn)
                log(f'二维码元素截图: {fn} ({int(best[2]["width"])}x{int(best[2]["height"])})')
            except Exception as e:
                log(f'元素截图失败: {e}')
                pg.screenshot(path=fn)
        else:
            pg.screenshot(path=fn)
            log(f'未定位二维码元素，整屏截图: {fn}')
        print('QR_FILE=' + fn, flush=True)

        # 轮询登录结果：以 web_session 变化 + 离开登录页为准
        ok = False
        for i in range(WAIT // 3):
            time.sleep(3)
            try:
                cookies = ctx.cookies()
            except Exception:
                break
            ws = [c for c in cookies if c['name'] == 'web_session']
            wslen = len(ws[0]['value']) if ws else 0
            url = pg.url
            if 'login' not in url or wslen > 40:
                log(f'检测到登录迹象 url={url} web_session_len={wslen}')
                time.sleep(3)
                ok = True
                break
            if i % 40 == 0:
                log(f'等待扫码... {i*3}s url={url} ws_len={wslen}')
        pg.screenshot(path=f'{SHOT_DIR}/扫码结果_{time.strftime("%H%M%S")}.png')

        cookies = ctx.cookies()
        txt = json.dumps(cookies, ensure_ascii=False, indent=1)
        pathlib.Path(COOKIE_OUT).write_text(txt, encoding='utf-8')
        pathlib.Path(COOKIE_ALT).write_text(txt, encoding='utf-8')
        names = [c['name'] for c in cookies]
        log(f'导出 {len(cookies)} cookie -> {COOKIE_OUT}')
        log('关键: ' + ', '.join(n for n in ('web_session', 'a1', 'webId') if n in names))
        pathlib.Path(RESULT).write_text(
            ('OK' if ok else 'FAIL') + f' n={len(cookies)} url={pg.url}', encoding='utf-8')
        ctx.close()


if __name__ == '__main__':
    main()
