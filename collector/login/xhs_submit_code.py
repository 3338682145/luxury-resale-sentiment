#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用已收到的验证码直接登录（不重新发送短信）。
流程: 打开登录页 -> 手机号登录 tab -> 填手机号 -> 勾协议 -> 填验证码 -> 提交 -> 导出 cookie
"""
import os, time, json, pathlib, re

PHONE = os.environ.get('XHS_PHONE', '')
CODE_FILE = '/tmp/xhs_code.txt'
RESULT_FILE = '/tmp/xhs_login_result.txt'
SHOT_DIR = '/workspace/二奢舆情采集/logs'
COOKIE_OUT = '/root/.xiaohongshu/cookies.json'
PROFILE = '/tmp/xhs_profile'

from playwright.sync_api import sync_playwright


def log(m):
    print(f'[{time.strftime("%H:%M:%S")}] {m}', flush=True)


def shot(pg, name):
    try:
        pg.screenshot(path=f'{SHOT_DIR}/submit_{name}.png')
        log(f'截图: submit_{name}.png')
    except Exception as e:
        log(f'截图失败: {e}')


def find_fill(pg, selectors, value, label):
    for sel in selectors:
        try:
            el = pg.query_selector(sel)
            if el and el.is_visible():
                el.click()
                el.fill(value)
                log(f'{label} ok <- {sel}')
                return True
        except Exception:
            continue
    log(f'{label} 未找到')
    return False


def click_exact(pg, pattern):
    try:
        loc = pg.get_by_text(pattern)
        for i in range(loc.count() - 1, -1, -1):
            el = loc.nth(i)
            try:
                if el.is_visible():
                    el.click()
                    log(f'点击: {el.inner_text().strip()[:20]!r}')
                    return True
            except Exception:
                continue
    except Exception as e:
        log(f'点击异常: {e}')
    return False


def main():
    code = pathlib.Path(CODE_FILE).read_text(encoding='utf-8').strip()
    code = ''.join(ch for ch in code if ch.isdigit())
    if len(code) < 4:
        log(f'验证码文件无效: {code!r}')
        pathlib.Path(RESULT_FILE).write_text('NO_CODE', encoding='utf-8')
        return
    log(f'待提交验证码: {code}')

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, headless=False,
            args=['--no-sandbox', '--disable-dev-shm-usage',
                  '--disable-blink-features=AutomationControlled'],
            viewport={'width': 1280, 'height': 900},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        )
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.goto('https://www.xiaohongshu.com/login?source=web', timeout=60000)
        time.sleep(4)
        shot(pg, '01_login')

        if 'login' not in pg.url:
            log('未在登录页，URL=' + pg.url)
        click_exact(pg, re.compile(r'^手机号登录$'))
        time.sleep(1)

        find_fill(pg, ['input[placeholder*="手机号"]', 'input[type="tel"]',
                       'input[maxlength="11"]'], PHONE, '手机号')
        time.sleep(1)

        # 协议勾选
        try:
            pg.get_by_text('我已阅读并同意').first.click(force=True)
            log('勾选协议')
        except Exception:
            pass
        time.sleep(1)

        ok = find_fill(pg, ['input[placeholder*="验证码"]', 'input[maxlength="6"]',
                            'input[name="code"]'], code, '验证码')
        shot(pg, '02_filled')
        if not ok:
            log('验证码输入框不存在')
            pathlib.Path(RESULT_FILE).write_text('NO_CODE_INPUT', encoding='utf-8')
            shot(pg, '03_fail')
            ctx.close()
            return

        time.sleep(1)
        # 提交：找文本恰为「登录」的按钮
        submitted = False
        for el in pg.query_selector_all('button, div, span'):
            try:
                t = (el.inner_text() or '').strip().replace(' ', '')
                if t == '登录' and el.is_visible():
                    box = el.bounding_box()
                    if box and box['width'] > 100 and box['height'] > 30:
                        el.click()
                        log('已点登录按钮')
                        submitted = True
                        break
            except Exception:
                continue
        if not submitted:
            log('未定位到登录按钮，尝试文本点击')
            click_exact(pg, re.compile(r'^登\s*录$'))

        ok_login = False
        for i in range(30):
            time.sleep(2)
            if 'login' not in pg.url:
                log(f'离开登录页: {pg.url} ({i*2}s)')
                ok_login = True
                break
            try:
                el = pg.query_selector('input[placeholder*="验证码"]')
                if not el or not el.is_visible():
                    log(f'登录框消失 ({i*2}s)')
                    ok_login = True
                    break
            except Exception:
                pass
        shot(pg, '04_result')

        cookies = ctx.cookies()
        pathlib.Path(COOKIE_OUT).write_text(
            json.dumps(cookies, ensure_ascii=False, indent=1), encoding='utf-8')
        names = [c['name'] for c in cookies]
        log(f'导出 {len(cookies)} 个 cookie，含 web_session={"web_session" in names}')
        log('当前 URL: ' + pg.url)
        pathlib.Path(RESULT_FILE).write_text(
            ('OK' if ok_login else 'UNCERTAIN') + f' cookies={len(cookies)}', encoding='utf-8')
        ctx.close()


if __name__ == '__main__':
    main()
