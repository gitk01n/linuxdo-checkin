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
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36 Edg/142.0.0.0",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
        )
        self.notifier = NotificationManager()

    @staticmethod
    def parse_cookie_string(cookie_str: str) -> list[dict]:
        cookies = []
        for part in cookie_str.strip().split(";"):
            part = part.strip()
            if "=" in part:
                name, _, value = part.partition("=")
                cookies.append(
                    {
                        "name": name.strip(),
                        "value": value.strip(),
                        "domain": ".linux.do",
                        "path": "/",
                    }
                )
        return cookies

    def login_with_cookies(self, cookie_str: str) -> bool:
        logger.info("检测到手动 Cookie，尝试 Cookie 登录...")
        dp_cookies = self.parse_cookie_string(cookie_str)
        if not dp_cookies:
            logger.error("Cookie 解析失败或为空，无法使用 Cookie 登录")
            return False

        logger.info(f"成功解析 {len(dp_cookies)} 个 Cookie 条目")

        for ck in dp_cookies:
            self.session.cookies.set(ck["name"], ck["value"], domain="linux.do")

        self.page.set.cookies(dp_cookies)
        logger.info("Cookie 设置完成，导航至 linux.do...")
        self.page.get(HOME_URL)
        time.sleep(5)

        try:
            user_ele = self.page.ele("@id=current-user")
        except Exception as e:
            logger.warning(f"Cookie 登录验证异常: {str(e)}")
            return True
        if not user_ele:
            if "avatar" in self.page.html:
                logger.info("Cookie 登录验证成功 (通过 avatar)")
                return True
            logger.error("Cookie 登录验证失败，可能已过期")
            return False
        else:
            logger.info("Cookie 登录验证成功")
            return True

    def login(self):
        logger.info("开始账号密码登录")
        logger.info("获取 CSRF token...")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36 Edg/142.0.0.0",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": LOGIN_URL,
        }
        resp_csrf = self.session.get(CSRF_URL, headers=headers, impersonate="firefox135")
        if resp_csrf.status_code != 200:
            logger.error(f"获取 CSRF token 失败: {resp_csrf.status_code}")
            return False
        csrf_data = resp_csrf.json()
        csrf_token = csrf_data.get("csrf")
        logger.info(f"CSRF Token obtained: {csrf_token[:10]}...")

        logger.info("正在登录...")
        headers.update(
            {
                "X-CSRF-Token": csrf_token,
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Origin": "https://linux.do",
            }
        )

        data = {
            "login": USERNAME,
            "password": PASSWORD,
            "second_factor_method": "1",
            "timezone": "Asia/Shanghai",
        }

        try:
            resp_login = self.session.post(
                SESSION_URL, data=data, impersonate="chrome136", headers=headers
            )

            if resp_login.status_code == 200:
                response_json = resp_login.json()
                if response_json.get("error"):
                    logger.error(f"登录失败: {response_json.get('error')}")
                    return False
                logger.info("登录成功!")
            else:
                logger.error(f"登录失败，状态码: {resp_login.status_code}")
                logger.error(resp_login.text)
                return False
        except Exception as e:
            logger.error(f"登录请求异常: {e}")
            return False

        logger.info("同步 Cookie 到 DrissionPage...")
        cookies_dict = self.session.cookies.get_dict()
        dp_cookies = []
        for name, value in cookies_dict.items():
            dp_cookies.append(
                {
                    "name": name,
                    "value": value,
                    "domain": ".linux.do",
                    "path": "/",
                }
            )

        self.page.set.cookies(dp_cookies)
        logger.info("Cookie 设置完成，导航至 linux.do...")
        self.page.get(HOME_URL)

        time.sleep(5)
        try:
            user_ele = self.page.ele("@id=current-user")
        except Exception as e:
            logger.warning(f"登录验证失败: {str(e)}")
            return True
        if not user_ele:
            if "avatar" in self.page.html:
                logger.info("登录验证成功 (通过 avatar)")
                return True
            logger.error("登录验证失败")
            return False
        else:
            logger.info("登录验证成功")
            return True

    def click_topic(self):
        topic_list = self.page.ele("@id=list-area").eles(".:title")
        if not topic_list:
            logger.error("未找到主题帖")
            return False
        logger.info(f"发现 {len(topic_list)} 个主题帖，随机选择10个")
        for topic in random.sample(topic_list, 10):
            self.click_one_topic(topic.attr("href"))
        return True

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
            except Exception:
                pass

    def browse_post(self, page):
        prev_url = None
        for _ in range(10):
            scroll_distance = random.randint(550, 650)
            logger.info(f"向下滚动 {scroll_distance} 像素...")
            page.run_js(f"window.scrollBy(0, {scroll_distance})")
            logger.info(f"已加载页面: {page.url}")

            if random.random() < 0.03:
                logger.success("随机退出浏览")
                break

            at_bottom = page.run_js(
                "window.scrollY + window.innerHeight >= document.body.scrollHeight"
            )
            current_url = page.url
            if current_url != prev_url:
                prev_url = current_url
            elif at_bottom and prev_url == current_url:
                logger.success("已到达页面底部，退出浏览")
                break

            wait_time = random.uniform(2, 4)
            logger.info(f"等待 {wait_time:.2f} 秒...")
            time.sleep(wait_time)

    def run(self):
        try:
            if COOKIES:
                login_res = self.login_with_cookies(COOKIES)
                if not login_res:
                    logger.warning("Cookie 登录失败，尝试账号密码登录...")
                    login_res = self.login()
            else:
                login_res = self.login()
            if not login_res:
                logger.warning("登录验证失败")

            if BROWSE_ENABLED:
                click_topic_res = self.click_topic()
                if not click_topic_res:
                    logger.error("点击主题失败，程序终止")
                    return
                logger.info("完成浏览任务")

            # 修复点：获取表格并传给通知
            connect_table = self.print_connect_info()
            self.send_notifications(BROWSE_ENABLED, connect_table)

        finally:
            try:
                self.page.close()
            except Exception:
                pass
            try:
                self.browser.quit()
            except Exception:
                pass

    def click_like(self, page):
        try:
            like_button = page.ele(".discourse-reactions-reaction-button")
            if like_button:
                logger.info("找到未点赞的帖子，准备点赞")
                like_button.click()
                logger.info("点赞成功")
                time.sleep(random.uniform(1, 2))
            else:
                logger.info("帖子可能已经点过赞了")
        except Exception as e:
            logger.error(f"点赞失败: {str(e)}")

    def print_connect_info(self):
        logger.info("获取连接信息")
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        }
        resp = self.session.get(
            "https://connect.linux.do/", headers=headers, impersonate="chrome136"
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        rows = soup.select("table tr")
        info = []

        for row in rows:
            cells = row.select("td")
            if len(cells) >= 3:
                project = cells[0].text.strip()
                current = cells[1].text.strip() if cells[1].text.strip() else "0"
                requirement = cells[2].text.strip() if cells[2].text.strip() else "0"
                info.append([project, current, requirement])

        # 修复点：返回表格字符串
        table_str = "\n" + tabulate(info, headers=["项目", "当前", "要求"], tablefmt="pretty")
        logger.info("--------------Connect Info-----------------")
        logger.info(table_str)
        return table_str

    # 修复点：接收表格并拼进通知
    def send_notifications(self, browse_enabled, connect_table=""):
        """发送签到通知"""
        status_msg = f"✅每日登录成功: {USERNAME}"
        if browse_enabled:
            status_msg += " + 浏览任务完成"

        final_msg = status_msg + connect_table
        self.notifier.send_all("LINUX DO", final_msg)


if __name__ == "__main__":
    if not COOKIES and (not USERNAME or not PASSWORD):
        print("请设置 LINUXDO_COOKIES，或同时设置 USERNAME 和 PASSWORD")
        exit(1)
    browser = LinuxDoBrowser()
    browser.run()
