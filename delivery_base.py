import time
import json
import os
import random
from datetime import datetime
from typing import List, Dict, Optional, Callable
from DrissionPage import ChromiumPage, ChromiumOptions
from DrissionPage.errors import PageDisconnectedError
from config import MAX_DELIVERY_COUNT, GREETING_MESSAGE, CITY_MAP

# 岗位状态标记
JOB_STATUS_INIT = 0
JOB_STATUS_DELIVERED = 1
JOB_STATUS_SKIPPED = 2


class BaseDeliveryDP:
    """投递引擎基类 — 包含平台无关的搜索/匹配/投递流程。
    子类需实现平台特有的 CSS 选择器和 URL 构建方法。"""

    # ── 子类必须覆盖的属性 ──
    platform_name = "Base"                  # 平台名称
    storage_filename = "jobs_storage.json"  # 本地存储文件名
    cookie_file = "cookies.json"            # Cookie 文件路径
    local_port = 9222                       # 浏览器调试端口
    user_data_dir = "browser_data"          # 浏览器用户数据目录

    def __init__(self, page, resume_analyzer=None):
        self.page = page
        self.resume_analyzer = resume_analyzer
        self.delivery_count = 0
        self.delivery_log = []
        self.max_delivery = MAX_DELIVERY_COUNT
        self.running = True
        self.log_callback = None
        self.jobs_storage = self._load_jobs_storage()
        self.seen_job_urls = set()
        self.delivered_companies = set()
        self.stop_mode = "count"
        self.max_time_seconds = 3600
        self.start_time = None
        self.reprocess_skipped = False

    # ═══════════════════════════════════════════════════════
    #  存储管理
    # ═══════════════════════════════════════════════════════

    def _storage_path(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), self.storage_filename)

    def _load_jobs_storage(self) -> Dict:
        path = self._storage_path()
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.log(f"加载岗位存储失败: {e}")
        return {}

    def _save_jobs_storage(self):
        try:
            with open(self._storage_path(), 'w', encoding='utf-8') as f:
                json.dump(self.jobs_storage, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log(f"保存岗位存储失败: {e}")

    def get_job_status(self, job_url: str) -> int:
        return self.jobs_storage.get(job_url, {}).get('status', JOB_STATUS_INIT)

    def update_job_status(self, job_url: str, status: int, job_title: str = "",
                          match_score: int = 0, company: str = "", hr_name: str = ""):
        if job_url not in self.jobs_storage:
            self.jobs_storage[job_url] = {
                'status': status,
                'title': job_title,
                'company': company,
                'hr_name': hr_name,
                'match_score': match_score,
                'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        else:
            self.jobs_storage[job_url]['status'] = status
            self.jobs_storage[job_url]['title'] = job_title
            self.jobs_storage[job_url]['match_score'] = match_score
            self.jobs_storage[job_url]['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            if company:
                self.jobs_storage[job_url]['company'] = company
            if hr_name:
                self.jobs_storage[job_url]['hr_name'] = hr_name
        self._save_jobs_storage()
        self.log(f"  岗位状态已更新: {job_title} | 公司: {company} | 匹配度: {match_score}% | 状态: {status}")

    def is_job_processed(self, job_url: str) -> bool:
        status = self.get_job_status(job_url)
        if self.reprocess_skipped and status == JOB_STATUS_SKIPPED:
            return False
        return status in [JOB_STATUS_DELIVERED, JOB_STATUS_SKIPPED]

    def is_job_duplicate(self, job_url: str) -> bool:
        return job_url in self.jobs_storage

    # ═══════════════════════════════════════════════════════
    #  通用工具
    # ═══════════════════════════════════════════════════════

    def should_stop(self) -> bool:
        if self.stop_mode == "count":
            if self.delivery_count >= self.max_delivery:
                self.log(f"已达到最大投递数: {self.max_delivery}")
                return True
        else:
            elapsed = time.time() - self.start_time
            if elapsed >= self.max_time_seconds:
                self.log(f"已达到最大运行时间: {self.max_time_seconds // 60}分钟")
                return True
            remaining = self.max_time_seconds - elapsed
            if remaining > 0 and int(remaining) % 60 == 0:
                self.log(f"剩余时间: {int(remaining // 60)}分钟")
        return False

    def log(self, msg):
        timestamp = datetime.now().strftime('%H:%M:%S')
        log_msg = f"[{timestamp}] {msg}"
        print(log_msg)
        if self.log_callback:
            self.log_callback(msg)

    def match_title_keywords(self, title: str, keywords: List[str]) -> bool:
        if not title or title == "未知":
            return False
        title_lower = title.lower()
        for keyword in keywords:
            keyword_lower = keyword.lower().strip()
            if keyword_lower and keyword_lower in title_lower:
                return True
        return False

    def wait_for_element(self, page, selector, timeout=5):
        try:
            return page.ele(selector, timeout=timeout)
        except:
            return None

    def wait_and_click(self, page, selector, timeout=5):
        elem = self.wait_for_element(page, selector, timeout)
        if elem:
            try:
                elem.click()
                return True
            except:
                pass
        return False

    def log_delivery(self, job_info: Dict, success: bool, reason: str = ""):
        log_entry = {
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'job_title': job_info.get('title', '未知'),
            'company': job_info.get('company', '未知'),
            'success': success,
            'reason': reason
        }
        self.delivery_log.append(log_entry)
        if success:
            self.log(f"  ✅ 投递成功: {job_info.get('title', '未知')} - {job_info.get('company', '未知')}")
        else:
            self.log(f"  ❌ 投递失败: {job_info.get('title', '未知')} - {job_info.get('company', '未知')} - {reason}")

    # ═══════════════════════════════════════════════════════
    #  断线重连
    # ═══════════════════════════════════════════════════════

    def _safe_navigate(self, url, max_retries=3):
        for attempt in range(max_retries):
            try:
                self.page.get(url)
                time.sleep(random.uniform(1.5, 3.0))
                return True
            except PageDisconnectedError:
                self.log(f"  ⚠ 页面连接断开 (第{attempt + 1}次)，正在重连...")
                time.sleep(3 * (attempt + 1))
                try:
                    old_page = self.page
                    try:
                        cookies = old_page.cookies()
                        cookie_path = self._storage_dir_file(self.cookie_file)
                        with open(cookie_path, 'w', encoding='utf-8') as f:
                            json.dump(cookies, f, ensure_ascii=False, indent=2)
                    except:
                        pass

                    co = ChromiumOptions()
                    co.set_paths(local_port=self.local_port,
                                 user_data_path=self._storage_dir_file(self.user_data_dir))
                    co.set_argument('--start-maximized')
                    co.set_argument('--no-sandbox')
                    co.set_argument('--disable-gpu')
                    co.set_argument('--disable-blink-features=AutomationControlled')
                    co.set_argument('--disable-dev-shm-usage')
                    co.set_argument('--disable-software-rasterizer')
                    co.set_user_agent(
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
                    self.page = ChromiumPage(co)
                    self.log(f"  ✓ 浏览器已重新连接")

                    cookie_path = self._storage_dir_file(self.cookie_file)
                    if os.path.exists(cookie_path):
                        try:
                            with open(cookie_path, 'r', encoding='utf-8') as f:
                                saved_cookies = json.load(f)
                            for c in saved_cookies:
                                self.page.set.cookies(c)
                        except:
                            pass
                except Exception as recon_err:
                    self.log(f"  ✗ 重连失败: {recon_err}")
                    if attempt == max_retries - 1:
                        return False
            except Exception as e:
                if 'disconnect' in str(e).lower() or 'disconnected' in str(e).lower():
                    self.log(f"  ⚠ 连接异常 (第{attempt + 1}次): {e}")
                    time.sleep(3 * (attempt + 1))
                    if attempt == max_retries - 1:
                        return False
                    continue
                raise
        return False

    def _storage_dir_file(self, filename):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)

    # ═══════════════════════════════════════════════════════
    #  子类必须实现的方法（平台特有）
    # ═══════════════════════════════════════════════════════

    def build_search_url(self, city_code: str, keyword: str) -> str:
        raise NotImplementedError

    def get_job_cards(self, page=None) -> List:
        raise NotImplementedError

    def extract_job_info_from_card(self, card) -> Optional[Dict]:
        raise NotImplementedError

    def get_job_detail_and_hr(self, job_info: Dict, page=None) -> tuple:
        raise NotImplementedError

    def deliver_job(self, job_info: Dict, resume_text: str = None,
                    custom_greeting: str = None, page=None) -> bool:
        raise NotImplementedError

    def load_more_content(self) -> bool:
        """加载更多内容。默认：滚动到底部（BOSS直聘模式）。
        子类可覆盖为翻页模式（智联招聘模式）。
        返回 True 表示加载成功，False 表示没有更多内容。"""
        try:
            for i in range(3):
                self.page.scroll.to_bottom()
                time.sleep(1)
            return True
        except:
            return False

    # ═══════════════════════════════════════════════════════
    #  核心搜索 + 投递循环
    # ═══════════════════════════════════════════════════════

    def search_and_deliver(self, city_code: str, city_name: str, title_keywords: List[str],
                           threshold: int = 60, resume_text: str = "", mode: str = "auto",
                           callback: Optional[Callable] = None):
        self.running = True
        self.delivery_count = 0
        self.delivery_log = []
        self.start_time = time.time()

        KEYWORD_SWITCH_INTERVAL = 30 * 60
        keywords_delivery_limit = 150
        total_keywords = len(title_keywords)

        current_search_keyword_index = 0
        last_switch_time = time.time()

        while self.running and not self.should_stop():
            current_time = time.time()
            if current_time - last_switch_time >= KEYWORD_SWITCH_INTERVAL:
                current_search_keyword_index = (current_search_keyword_index + 1) % total_keywords
                last_switch_time = current_time
                self.log(f"")
                self.log(f"{'=' * 50}")
                self.log(f"30分钟已到，切换搜索关键词")
                self.log(f"{'=' * 50}")

            current_search_keyword = title_keywords[current_search_keyword_index]
            search_url = self.build_search_url(city_code, current_search_keyword)

            self.log(f"")
            self.log(f"当前搜索关键词: {current_search_keyword} (索引: {current_search_keyword_index})")
            self.log(f"匹配关键词: {title_keywords} (任一匹配即可)")
            self.log(f"URL: {search_url}")
            self.log(f"下次切换时间: {time.strftime('%H:%M:%S', time.localtime(last_switch_time + KEYWORD_SWITCH_INTERVAL))}")

            try:
                if not self._safe_navigate(search_url):
                    self.log(f"  ✗ 无法连接页面，跳过关键词: {current_search_keyword}")
                    time.sleep(30)
                    continue

                self.seen_job_urls = set()
                scroll_count = 0
                max_scrolls = 3
                keyword_delivery_count = 0
                found_any_cards = False

                while self.running and scroll_count < max_scrolls and keyword_delivery_count < keywords_delivery_limit:
                    self.log(f"{'-' * 40}")
                    self.log(f"第 {scroll_count + 1} 次滚动")

                    job_cards = self.get_job_cards(self.page)
                    self.log(f"当前页面岗位数: {len(job_cards)}")

                    if len(job_cards) == 0:
                        self.log("未找到岗位卡片")
                        break

                    found_any_cards = True

                    matched_count = 0

                    for idx, card in enumerate(job_cards):
                        if not self.running:
                            break
                        if mode == "auto" and self.should_stop():
                            return
                        if keyword_delivery_count >= keywords_delivery_limit:
                            self.log(f"当前关键词已投递 {keyword_delivery_count} 个，切换关键词")
                            break

                        try:
                            job_info = self.extract_job_info_from_card(card)
                        except Exception as e:
                            self.log(f"提取岗位信息异常: {e}")
                            continue

                        if not job_info:
                            continue

                        job_url = job_info.get('url')
                        job_title = job_info.get('title', '')
                        company = job_info.get('company', '')

                        if not job_url:
                            continue

                        # 会话级去重
                        if job_url in self.seen_job_urls:
                            self.log(f"  [{idx + 1}] {job_title} - {company} (会话中已处理)")
                            continue
                        self.seen_job_urls.add(job_url)

                        # URL 去重
                        if self.is_job_processed(job_url):
                            status = self.get_job_status(job_url)
                            status_str = "已投递" if status == JOB_STATUS_DELIVERED else "已跳过"
                            self.log(f"  [{idx + 1}] {job_title} - {company} (URL已{status_str})")
                            continue

                        # 标题关键词匹配
                        if not self.match_title_keywords(job_title, title_keywords):
                            continue

                        matched_count += 1
                        self.log(f"  [{idx + 1}] {job_title} - {company}")
                        self.log(f"       >> 标题匹配!")

                        if not self.running:
                            break

                        # 获取详情
                        job_detail, hr_name = self.get_job_detail_and_hr(job_info, self.page)
                        if not job_detail:
                            continue

                        job_info['job_detail'] = job_detail
                        job_info['hr_name'] = hr_name

                        # URL 重复最终检查
                        if self.is_job_duplicate(job_url):
                            self.log(f"       >> URL已存在，更新标记为跳过")
                            self.update_job_status(job_url, JOB_STATUS_SKIPPED, job_title, 0, company, hr_name)
                            continue

                        # AI 匹配度
                        match_score = 50
                        if self.resume_analyzer and resume_text and self.running:
                            self.log(f"       >> 计算匹配度...")
                            match_result = self.resume_analyzer.calculate_match_score(
                                resume_text, job_title, job_detail, company)
                            match_score = match_result.get('score', 50)
                            self.log(f"       >> 匹配度: {match_score}%")

                        job_info['match_score'] = match_score
                        self.update_job_status(job_url, JOB_STATUS_INIT, job_title, match_score, company, hr_name)

                        # 投递决策
                        if callback and self.running:
                            if match_score >= threshold:
                                self.log(f"       >> 匹配度达标，开始投递...")
                                success = callback(job_info, match_score, job_detail)
                                if success:
                                    if company != '未知':
                                        normalized_company = company.strip().replace(' ', '').replace('　', '')
                                        self.delivered_companies.add(normalized_company)
                                    keyword_delivery_count += 1
                                self.log(f"       >> 当前关键词已投递 {keyword_delivery_count} 个，总投递数: {self.delivery_count}")
                            else:
                                self.log(f"       >> 匹配度不足，更新标记为跳过")
                                self.update_job_status(job_url, JOB_STATUS_SKIPPED, job_title, match_score, company, hr_name)

                        if mode == "auto" and self.should_stop():
                            return
                        if keyword_delivery_count >= keywords_delivery_limit:
                            self.log(f"当前关键词已投递 {keyword_delivery_count} 个，切换关键词")
                            break

                    self.log(f"本次滚动匹配数: {matched_count}")

                    if mode == "auto" and self.should_stop():
                        return
                    if keyword_delivery_count >= keywords_delivery_limit:
                        self.log(f"当前关键词已投递 {keyword_delivery_count} 个，切换关键词")
                        break

                    self.log("加载更多内容...")
                    if not self.load_more_content():
                        self.log("没有更多内容可加载")
                        break
                    scroll_count += 1

                # 如果一次都没找到卡片，强制切换关键词，避免无限重试同一URL
                if not found_any_cards:
                    self.log(f"该关键词未找到任何岗位卡片，强制切换关键词")
                    current_search_keyword_index = (current_search_keyword_index + 1) % total_keywords
                    last_switch_time = time.time()
                    time.sleep(3)
                    continue

            except Exception as e:
                self.log(f"处理关键词 {current_search_keyword} 时出错: {e}")
                import traceback
                traceback.print_exc()

        self.log("=" * 50)
        self.log(f"搜索投递完成! 共投递 {self.delivery_count} 个岗位")
        self.log("=" * 50)

    def search_and_filter_jobs(self, title_keywords, threshold, resume_text, mode,
                               city_code, log_callback=None, callback=None):
        if log_callback:
            self.log_callback = log_callback
        city_name = CITY_MAP.get(city_code, "北京")
        self.search_and_deliver(city_code, city_name, title_keywords, threshold, resume_text, mode, callback)

    def search_and_collect_jobs(self, title_keywords, resume_text, city_code,
                                log_callback=None, callback=None):
        if log_callback:
            self.log_callback = log_callback
        city_name = CITY_MAP.get(city_code, "北京")
        self.search_and_deliver(city_code, city_name, title_keywords, 0, resume_text, "manual", callback)

    def stop(self):
        self.running = False
        self.log("正在停止搜索...")
