"""
cron: 0 */6 * * *
new Env("Linux.Do 签到")
"""

import os
import random
import time
import functools
from loguru import logger
from DrissionPage import ChromiumOptions, Chromium
from tabulate import tabulate
from curl_cffi import requests
from bs4 import BeautifulSoup
from notify import NotificationManager


def retry_decorator(retries=3, min_delay=5, max_delay=10):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == retries - 1:
                        logger.error(f"函数 {func.__name__} 最终执行失败: {str(e)}")
                    logger.warning(
                        f"函数 {func.__name__} 第 {attempt + 1}/{retries} 次尝试失败: {str(e)}"
                    )
                    if attempt < retries - 1:
                        sleep_s = random.uniform(min_delay, max_delay)
                        logger.info(
                            f"将在 {sleep_s:.2f}s 后重试 ({min_delay}-{max_delay}s 随机延迟)"
                        )
                        time.sleep(sleep_s)
            return None

        return wrapper

    return decorator


os.environ.pop("DISPLAY", None)
os.environ.pop("DYLD_LIBRARY_PATH", None)

USERNAME = os.environ.get("LINUXDO_USERNAME")
PASSWORD = os.environ.get("LINUXDO_PASSWORD")
COOKIES = os.environ.get("LINUXDO_COOKIES", "").strip()
BROWSE_ENABLED = os.environ.get("BROWSE_ENABLED", "true").strip().lower() not in [
    "false",
    "0",
    "off",
]
if not USERNAME:
    USERNAME = os.environ.get("USERNAME")
if not PASSWORD:
    PASSWORD = os.environ.get("PASSWORD")

HOME_URL = "https://linux.do/"
LOGIN_URL = "https://linux.do/login"
SESSION_URL = "https://linux.do/session"
CSRF_URL = "https://linux.do/session/csrf"


class LinuxDoBrowser:
    def __init__(self) -> None:
        from sys import platform

        if platform == "linux" or platform == "linux2":
            platformIdentifier = "X11; Linux x86_64"
        elif platform == "darwin":
            platformIdentifier = "Macintosh; Intel Mac OS X 10_15_7"
        elif platform == "win32":
            platformIdentifier = "Windows NT 10.0; Win64; x64"
        else:
            platformIdentifier = "X11; Linux x86_64"

        co = (
            ChromiumOptions()
            .headless(True)
            .incognito(True)
            .set_argument("--no-sandbox")
        )
        co.set_user_agent(
            f"Mozilla/5.0 ({platformIdentifier}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        )
        self.browser = Chromium(co)
        self.page = self.browser.new_tab()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36 Edg/142.0.0.0",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        self.notifier = NotificationManager()

    @staticmethod
    def parse_cookie_string(cookie_str: str) -> list[dict]:
        cookies = []
        for part in cookie_str.strip().split(";"):
            part = part.strip()
            if "=" in part:
                name, _, value = part.partition("=")
                cookies.append({
                    "name": name.strip(),
                    "value": value.strip(),
                    "domain": ".linux.do",
                    "path": "/",
                })
        return cookies

    def sync_session_cookies_from_browser(self):
        """从浏览器同步Cookie到requests.session，这是修复表格为空的关键"""
        try:
            cookie_list = self.page.get.cookies()
            for c in cookie_list:
                self.session.cookies.set(
                    c.get("name"),
                    c.get("value"),
                    domain=c.get("domain", ".linux.do").lstrip("."),
                    path=c.get("path", "/")
                )
            logger.info("✅ 已从浏览器同步Cookie到请求会话")
        except Exception as e:
            logger.warning(f"同步Cookie失败: {e}")

    def login_with_cookies(self, cookie_str: str) -> bool:
        logger.info("检测到手动Cookie，尝试Cookie登录...")
        dp_cookies = self.parse_cookie_string(cookie_str)
        if not dp_cookies:
            logger.error("Cookie解析失败或为空")
            return False

        for ck in dp_cookies:
            self.session.cookies.set(ck["name"], ck["value"], domain="linux.do")

        self.page.set.cookies(dp_cookies)
        self.page.get(HOME_URL)
        time.sleep(3)

        try:
            if self.page.ele("@id=current-user") or "avatar" in self.page.html:
                logger.info("Cookie登录成功")
                self.sync_session_cookies_from_browser()
                return True
        except:
            pass
        logger.error("Cookie登录失败或已过期")
        return False

    def login(self):
        logger.info("开始账号密码登录")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36 Edg/142.0.0.0",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": LOGIN_URL,
        }
        try:
            resp_csrf = self.session.get(CSRF_URL, headers=headers, impersonate="firefox135")
            csrf_token = resp_csrf.json().get("csrf")
        except:
            logger.error("获取CSRF失败")
            return False

        headers.update({
            "X-CSRF-Token": csrf_token,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://linux.do",
        })

        data = {
            "login": USERNAME,
            "password": PASSWORD,
            "second_factor_method": "1",
            "timezone": "Asia/Shanghai",
        }

        try:
            resp_login = self.session.post(SESSION_URL, data=data, headers=headers, impersonate="chrome136")
            if resp_login.status_code != 200 or resp_login.json().get("error"):
                logger.error("登录失败")
                return False
            logger.info("登录成功")
        except:
            return False

        cookies_dict = self.session.cookies.get_dict()
        dp_cookies = [{"name": k, "value": v, "domain": ".linux.do", "path": "/"} for k, v in cookies_dict.items()]
        self.page.set.cookies(dp_cookies)
        self.page.get(HOME_URL)
        time.sleep(3)
        self.sync_session_cookies_from_browser()
        return True

    def click_topic(self):
        try:
            topic_list = self.page.ele("@id=list-area").eles(".:title")
            if not topic_list:
                return False
            logger.info(f"发现 {len(topic_list)} 个帖子，随机浏览10个")
            for topic in random.sample(topic_list, min(10, len(topic_list))):
                self.click_one_topic(topic.attr("href"))
            return True
        except:
            return False

    @retry_decorator()
    def click_one_topic(self, topic_url):
        new_page = self.browser.new_tab()
        try:
            new_page.get(topic_url)
            if random.random() < 0.3:
                self.click_like(new_page)
            self.browse_post(new_page)
        finally:
            try:
                new_page.close()
            except:
                pass

    def browse_post(self, page):
        prev_url = None
        for _ in range(10):
            scroll = random.randint(500, 700)
            page.run_js(f"window.scrollBy(0,{scroll})")
            if random.random() < 0.03:
                break
            at_bottom = page.run_js("window.scrollY + window.innerHeight >= document.body.scrollHeight")
            current_url = page.url
            if current_url == prev_url and at_bottom:
                break
            prev_url = current_url
            time.sleep(random.uniform(2, 4))

    def click_like(self, page):
        try:
            btn = page.ele(".discourse-reactions-reaction-button")
            if btn:
                btn.click()
                logger.info("已点赞")
                time.sleep(1)
        except:
            pass

    def get_connect_info(self):
        """修复：确保登录态再获取"""
        logger.info("正在获取 connect 数据...")
        try:
            resp = self.session.get(
                "https://connect.linux.do/",
                headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
                impersonate="chrome136"
            )
            soup = BeautifulSoup(resp.text, "html.parser")
            rows = soup.select("table tr")
            info = []
            for row in rows:
                cells = row.select("td")
                if len(cells) >= 3:
                    p = cells[0].text.strip()
                    c = cells[1].text.strip() or "0"
                    r = cells[2].text.strip() or "0"
                    info.append([p, c, r])
            table_str = "\n" + tabulate(info, headers=["项目", "当前", "要求"], tablefmt="pretty")
            logger.info("\n--------------Connect Info-----------------")
            logger.info(table_str)
            return table_str
        except Exception as e:
            logger.error(f"获取失败: {e}")
            return "\n[获取数据失败]"

    def send_notifications(self, browse_enabled, table_str):
        status = f"✅ Linux.Do 签到完成：{USERNAME}"
        if browse_enabled:
            status += " + 已自动浏览"
        msg = status + table_str
        self.notifier.send_all("Linux.Do 签到", msg)

    def run(self):
        try:
            login_ok = False
            if COOKIES:
                login_ok = self.login_with_cookies(COOKIES)
                if not login_ok:
                    logger.warning("Cookie登录失败，尝试账号密码")
                    login_ok = self.login()
            else:
                login_ok = self.login()

            if BROWSE_ENABLED:
                self.click_topic()
                logger.info("浏览任务完成")

            table_str = self.get_connect_info()
            self.send_notifications(BROWSE_ENABLED, table_str)

        finally:
            try:
                self.page.close()
                self.browser.quit()
            except:
                pass


if __name__ == "__main__":
    if not COOKIES and (not USERNAME or not PASSWORD):
        print("请设置 LINUXDO_COOKIES 或 USERNAME+PASSWORD")
        exit(1)
    bot = LinuxDoBrowser()
    bot.run()
