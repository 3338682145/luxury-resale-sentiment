#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小红书手机号+验证码登录（Playwright）。
阶段1: 打开登录页 -> 填手机号 -> 点"获取验证码" -> 等待 /tmp/xhs_code.txt
阶段2: 读到验证码 -> 填入 -> 提交 -> 导出 cookies
"""
import os, sys, time, json, pathlib, re

PHONE = os.environ.get('XHS_PHONE', '')
CODE_FILE = '/tmp/xhs_code.txt'
RESULT_FILE = '/tmp/xhs_login_result.txt'
SHOT_DIR = '/workspace/二奢舆情采集/logs'
COOKIE_OUT = '/root/.xiaohongshu/cookies.json'
PROFILE = '/tmp/xhs_profile'
TIMEOUT_WAIT_CODE = 900  # 等验证码 15 分钟（留足用户回传时间）

from playwright.sync_api import sync_playwright


def log(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def shot(pg, name):
    try:
        pg.screenshot(path=f'{SHOT_DIR}/login_{name}.png')
        log(f'截图已存: login_{name}.png')
    except Exception as e:
        log(f'截图失败: {e}')


def find_and_fill(pg, selectors, value, label):
    for sel in selectors:
        try:
            el = pg.query_selector(sel)
            if el:
                el.click()
                el.fill(value)
                log(f'{label}: 命中选择器 {sel}')
                return True
        except Exception:
            continue
    log(f'{label}: 未找到元素 (尝试过 {len(selectors)} 个选择器)')
    return False


def click_text(pg, texts):
    for t in texts:
        try:
            el = pg.get_by_text(t, exact=False).first
            if el and el.is_visible():
                el.click()
                log(f'点击文本: {t}')
                return True
        except Exception:
            continue
    log(f'未找到可点击文本: {texts}')
    return False


def send_code_button(pg):
    """精确定位「获取验证码」按钮（避免误选外层容器 div）。"""
    pats = [re.compile(r'^获取验证码$'), re.compile(r'^发送验证码$'),
            re.compile(r'^重新发送(\s*[\(（]\s*\d+\s*[s秒]?\s*[\)）])?$')]
    for pat in pats:
        try:
            loc = pg.get_by_text(pat)
            cnt = loc.count()
        except Exception:
            continue
        for i in range(cnt - 1, -1, -1):
            try:
                el = loc.nth(i)
                if el.is_visible():
                    return el, (el.inner_text() or '').strip()
            except Exception:
                continue
    return None, ''


def click_send_code(pg, max_cooldown=240):
    """点击获取/重新发送验证码；若处于冷却倒计时则先等到归零。"""
    elapsed = 0
    attempts = 0
    while elapsed <= max_cooldown and attempts < 4:
        el, t = send_code_button(pg)
        if el is None:
            log('未找到验证码发送按钮，2s 后重试')
            time.sleep(2)
            elapsed += 2
            continue
        digits = ''.join(ch for ch in t if ch.isdigit())
        cooling = ('重新发送' in t) and digits and int(digits) > 0
        if cooling:
            wait = min(int(digits), 120)
            log(f'短信冷却中（{t}），等待 {wait}s')
            time.sleep(wait + 1)
            elapsed += wait + 1
            continue
        try:
            el.click()
            log(f'点击发送按钮: {t}')
        except Exception as e:
            log(f'点击失败: {e}')
            time.sleep(2)
            elapsed += 2
            continue
        attempts += 1
        time.sleep(3)
        el2, t2 = send_code_button(pg)
        if el2 is not None and '重新发送' in t2:
            log(f'发送成功，按钮变为: {t2}')
            return True
        log(f'按钮仍为「{t2}」，未触发发送，重试')
        time.sleep(2)
        elapsed += 5
    log('多次尝试仍未确认短信已发送')
    return False


def main():
    for p_ in (RESULT_FILE, CODE_FILE):
        if os.path.exists(p_):
            os.remove(p_)

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

        log('打开小红书登录页...')
        pg.goto('https://www.xiaohongshu.com/explore', timeout=60000)
        time.sleep(4)
        shot(pg, '01_home')

        # 进入登录态（访客也有 web_session，不能作为已登录依据，
        # 以页面是否出现登录框为准）
        try:
            pg.goto('https://www.xiaohongshu.com/login?source=web', timeout=60000)
        except Exception:
            pass
        time.sleep(4)
        shot(pg, '02_login')

        if 'login' not in pg.url:
            log('未跳到登录页，可能已是登录态，URL=' + pg.url)
        else:
            # 切换到手机号登录（若有 tab）
            click_text(pg, ['手机号登录', '验证码登录', '短信登录'])
            time.sleep(1)

            ok = find_and_fill(
                pg,
                ['input[placeholder*="手机号"]', 'input[type="tel"]',
                 'input[maxlength="11"]', '.phone input', 'input[name="phone"]'],
                PHONE, '填手机号')
            shot(pg, '03_phone')
            if not ok:
                # 打印页面结构辅助诊断
                log('页面 input 元素:')
                for el in pg.query_selector_all('input'):
                    try:
                        log('   ' + str(el.get_attribute('placeholder')) + ' | class=' + str(el.get_attribute('class'))[:60])
                    except Exception:
                        pass
                log('页面按钮文本:')
                for el in pg.query_selector_all('button, .clickable, a'):
                    try:
                        t = (el.inner_text() or '').strip()
                        if t and len(t) < 20:
                            log('   ' + t)
                    except Exception:
                        pass

            time.sleep(1)
            # 先勾选协议再点获取验证码（未勾选会被拦截）
            for sel in ['input[type="checkbox"]', '.agreement-checkbox', '.checkbox',
                        'input[type="radio"]']:
                try:
                    el = pg.query_selector(sel)
                    if el and not el.is_checked():
                        el.click(force=True)
                        log('已勾选协议')
                        break
                except Exception:
                    continue
            # 复选框可能是自定义样式圆圈，用文本旁的元素兜底
            try:
                pg.get_by_text('我已阅读并同意').first.click(force=True)
                log('已点协议文本')
            except Exception:
                pass

            time.sleep(1)
            ok_send = click_send_code(pg)
            log(f'>>> 发送请求完成（ok={ok_send}），验证码已发往 {PHONE}，请写入 {CODE_FILE}')
            shot(pg, '04_sms_sent')

            # 轮询等待验证码
            code = None
            waited = 0
            while waited < TIMEOUT_WAIT_CODE:
                if os.path.exists(CODE_FILE):
                    txt = pathlib.Path(CODE_FILE).read_text(encoding='utf-8').strip()
                    if txt:
                        code = ''.join(ch for ch in txt if ch.isdigit())
                        if len(code) >= 4:
                            log(f'读到验证码: {code}')
                            break
                time.sleep(2)
                waited += 2
            if not code:
                log('等待验证码超时')
                pathlib.Path(RESULT_FILE).write_text('TIMEOUT_NO_CODE', encoding='utf-8')
                shot(pg, '05_timeout')
                ctx.close()
                return

            find_and_fill(pg,
                          ['input[placeholder*="验证码"]', 'input[maxlength="6"]',
                           'input[name="code"]', '.code input'],
                          code, '填验证码')
            shot(pg, '05_code')
            time.sleep(1)

            # 勾选协议（若有未勾选）
            for sel in ['input[type="checkbox"]', '.agreement', '.checkbox']:
                try:
                    el = pg.query_selector(sel)
                    if el and not el.is_checked():
                        el.click()
                        log('已勾选协议')
                        break
                except Exception:
                    continue

            click_text(pg, ['登 录', '登录', '立即登录', '登錄'])
            log('已提交登录，等待结果...')

            # 等待登录成功：以离开登录页/登录框消失为准
            ok_login = False
            for i in range(40):
                time.sleep(2)
                cur = pg.url
                if 'login' not in cur:
                    log(f'页面已离开登录页: {cur} (第 {i*2}s)')
                    ok_login = True
                    break
                try:
                    el = pg.query_selector('input[placeholder*="验证码"]')
                    if not el or not el.is_visible():
                        log(f'登录框已消失 (第 {i*2}s)')
                        ok_login = True
                        break
                except Exception:
                    pass
            shot(pg, '06_result')

            if not ok_login:
                log('登录结果未确认，仍导出当前 cookies 供检查')

        # 导出 cookies
        cookies = ctx.cookies()
        pathlib.Path(COOKIE_OUT).write_text(
            json.dumps(cookies, ensure_ascii=False, indent=1), encoding='utf-8')
        log(f'已导出 {len(cookies)} 个 cookie -> {COOKIE_OUT}')
        names = [c['name'] for c in cookies]
        log('关键 cookie: ' + ', '.join(
            n for n in ('web_session', 'a1', 'webId', 'gid', 'customerClientId') if n in names))
        pathlib.Path(RESULT_FILE).write_text(
            'HAS_SESSION' if any(c['name'] == 'web_session' for c in cookies) else 'NO_SESSION',
            encoding='utf-8')
        ctx.close()


if __name__ == '__main__':
    main()
