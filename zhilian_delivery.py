import time
import json
from typing import List, Dict, Optional
from delivery_base import BaseDeliveryDP, JOB_STATUS_DELIVERED, JOB_STATUS_SKIPPED
from config import ZHI_LIAN_COOKIE_FILE


class ZhilianDeliveryDP(BaseDeliveryDP):
    """智联招聘投递引擎"""

    platform_name = "智联招聘"
    storage_filename = "jobs_storage_zhilian.json"
    cookie_file = "cookies_zhilian.json"
    local_port = 9223
    user_data_dir = "browser_data_zhilian"

    def __init__(self, page, resume_analyzer=None):
        super().__init__(page, resume_analyzer)
        self._current_page = 1

    def load_more_content(self) -> bool:
        """智联翻页模式：点击下一页，或 URL 翻页"""
        self._current_page += 1
        self.log(f"翻到第 {self._current_page} 页...")

        # 方法1: 点击"下一页"按钮
        next_selectors = [
            'text:下一页', 'text:下一頁',
            '.next', '.next-page', '.pagination .next', '.page-next',
            '[class*="next"]',
        ]
        for sel in next_selectors:
            try:
                btn = self.page.ele(sel, timeout=1)
                if btn:
                    btn.click()
                    time.sleep(2)
                    self.log(f"已点击下一页: {sel}")
                    return True
            except:
                continue

        # 方法2: JS 点击
        try:
            result = self.page.run_js("""
            var btns = document.querySelectorAll('a, button, span');
            for (var i = 0; i < btns.length; i++) {
                var t = (btns[i].innerText || btns[i].textContent || '').trim();
                if (t === '下一页' || t === '>' || t === '>>') {
                    btns[i].click();
                    return 'clicked';
                }
            }
            return 'not_found';
            """)
            if result == 'clicked':
                time.sleep(2)
                return True
        except:
            pass

        # 方法3: URL 翻页兜底
        try:
            from urllib.parse import quote
            city_code = getattr(self, '_city_code', '530')
            kw = getattr(self, '_keyword', '')
            if kw:
                next_url = f"https://sou.zhaopin.com/jobs/searchresult.ashx?jl={city_code}&kw={quote(kw)}&p={self._current_page}&sm=0"
                self.log(f"URL翻页: ...p={self._current_page}")
                self.page.get(next_url)
                time.sleep(2)
                # 翻页后检测验证
                self._handle_verify_checkbox()
                return True
        except Exception as e:
            self.log(f"URL翻页失败: {e}")

        self.log("翻页失败")
        return False

    # ═══════════════════════════════════════════════════════
    #  智联招聘特有实现
    # ═══════════════════════════════════════════════════════

    def build_search_url(self, city_code: str, keyword: str) -> str:
        # 智联搜索 URL：城市代码格式 jl530（如北京=530）
        self._current_page = 1
        self._city_code = city_code
        self._keyword = keyword
        self.log(f"城市代码: {city_code}")
        from urllib.parse import quote
        return f"https://sou.zhaopin.com/jobs/searchresult.ashx?jl={city_code}&kw={quote(keyword)}&p=1&sm=0"

    def get_job_cards(self, page=None) -> List:
        current_page = page or self.page
        try:
            # 先检测并处理验证
            self._handle_verify_checkbox(current_page)

            self.log("正在获取智联岗位卡片...")

            # 步骤0: 验证 run_js 是否可用
            try:
                title = current_page.run_js("return document.title;")
                self.log(f"页面标题: {title}")
            except Exception as e:
                self.log(f"run_js不可用: {e}")

            # 步骤1: 先尝试 CSS 选择器
            card_selectors = [
                '.positionlist__item', '.joblist-box__item', '.job-card',
                '.searchResult__item', '.jobList__item', '.content__list--item',
                '[class*="positionlist"]', '[class*="joblist"]',
                '.search-content > div', '.result-list > div',
            ]
            for selector in card_selectors:
                try:
                    els = current_page.eles(selector, timeout=2)
                    if els and len(els) >= 3:
                        self.log(f"CSS选择器 {selector} 找到 {len(els)} 个卡片")
                        return self._extract_from_elements(els)
                except:
                    continue

            # 步骤2: 用简单 JS 诊断页面结构
            self.log("CSS未匹配，用JS诊断页面结构...")
            info_raw = current_page.run_js("""
            var info = {};
            info.url = window.location.href;
            info.divCount = document.querySelectorAll('div').length;
            info.liCount = document.querySelectorAll('li').length;
            info.aCount = document.querySelectorAll('a').length;

            // 找主要内容区域
            var areas = document.querySelectorAll('.content, .search-content, .result-list, .search-result, main, #app, .positionlist');
            info.areas = [];
            for (var i = 0; i < Math.min(areas.length, 5); i++) {
                var a = areas[i];
                var kids = a.children;
                var kidSamples = [];
                for (var j = 0; j < Math.min(kids.length, 5); j++) {
                    var k = kids[j];
                    kidSamples.push(k.tagName + '.' + (k.className||'').split(' ').slice(0,2).join('.') + '(' + ((k.innerText||'').length) + 'c)');
                }
                info.areas.push({sel: a.tagName + (a.id?'#'+a.id:'') + (a.className?'.'+a.className.split(' ').slice(0,2).join('.'):''), childCount: kids.length, samples: kidSamples});
            }

            // 找所有带链接且有文本的 li/div
            var candidates = [];
            var seen = {};
            var all = document.querySelectorAll('div[class], li[class]');
            for (var i = 0; i < all.length; i++) {
                var el = all[i];
                var txt = (el.innerText || el.textContent || '').trim();
                var links = el.querySelectorAll('a[href]');
                if (txt.length > 20 && txt.length < 2000 && links.length > 0) {
                    var cls = el.className || '';
                    if (!seen[cls]) {
                        seen[cls] = true;
                        var firstLink = links[0].getAttribute('href') || '';
                        candidates.push({cls: cls.split(' ').slice(0,3).join('.'), txtLen: txt.length, linkCount: links.length, firstHref: firstLink.slice(0, 80)});
                    }
                }
            }
            info.candidates = candidates.slice(0, 30);

            return JSON.stringify(info);
            """)

            if info_raw:
                try:
                    info = json.loads(info_raw)
                    self.log(f"页面URL: {info.get('url','')[:100]}")
                    self.log(f"元素数: div={info.get('divCount')} li={info.get('liCount')} a={info.get('aCount')}")
                    areas = info.get('areas', [])
                    for area in areas[:3]:
                        self.log(f"  区域: {area.get('sel','')} 子元素={area.get('childCount')} 样本={area.get('samples',[])}")
                    candidates = info.get('candidates', [])
                    if candidates:
                        self.log(f"候选卡片类型 ({len(candidates)}):")
                        for c in candidates[:6]:
                            self.log(f"  .{c['cls'][:60]} text={c['txtLen']}c links={c['linkCount']} href={c['firstHref'][:60]}")
                except Exception as e:
                    self.log(f"解析诊断JSON失败: {e} 原始: {str(info_raw)[:200]}")

            # 步骤3: 用简单 JS 提取有文本和链接的 div/li
            extract_raw = current_page.run_js("""
            var results = [];
            var seen = {};
            var items = document.querySelectorAll('div[class], li[class]');
            for (var i = 0; i < items.length; i++) {
                var el = items[i];
                var txt = (el.innerText || el.textContent || '').trim();
                if (txt.length < 20 || txt.length > 2000) continue;

                var links = el.querySelectorAll('a[href]');
                if (links.length === 0) continue;

                // 找最可能的岗位链接
                var jobUrl = '';
                var title = '';
                for (var j = 0; j < links.length; j++) {
                    var href = (links[j].getAttribute('href') || '').trim();
                    var lt = (links[j].innerText || links[j].textContent || '').trim();
                    if (href && href !== '#' && !href.startsWith('javascript:') && lt.length > 2) {
                        if (!jobUrl || lt.length > title.length) {
                            jobUrl = href;
                            title = lt;
                        }
                    }
                }

                if (title && jobUrl) {
                    if (!jobUrl.startsWith('http')) {
                        if (jobUrl.startsWith('//')) jobUrl = 'https:' + jobUrl;
                        else jobUrl = 'https://www.zhaopin.com' + (jobUrl.startsWith('/') ? '' : '/') + jobUrl;
                    }
                    var key = title + '|' + jobUrl;
                    if (!seen[key]) {
                        seen[key] = true;
                        var lines = txt.split('\\n').filter(function(l) { return l.trim(); });
                        results.push({
                            url: jobUrl, title: title,
                            company: lines.length > 1 ? lines[1].trim().slice(0, 40) : '',
                            salary: '',
                            location: lines.length > 2 ? lines[2].trim().slice(0, 20) : '',
                            fullText: txt.slice(0, 300)
                        });
                    }
                }
            }

            return JSON.stringify(results.slice(0, 40));
            """)

            if extract_raw:
                try:
                    jobs = json.loads(extract_raw)
                    self.log(f"JS提取到 {len(jobs)} 个岗位")
                    if jobs:
                        for i, j in enumerate(jobs[:3]):
                            self.log(f"  样本{i+1}: [{j.get('title','')[:30]}] url={j.get('url','')[:80]}")
                        return [{'type': 'js_data', 'data': j} for j in jobs]
                except Exception as e:
                    self.log(f"解析提取JSON失败: {e}")

            self.log("所有方法均未找到岗位卡片")
            return []

        except Exception as e:
            self.log(f"获取智联岗位卡片失败: {e}")
            import traceback
            traceback.print_exc()
        return []

    def _extract_from_elements(self, elements) -> List:
        """从 DrissionPage 元素列表中提取岗位数据"""
        results = []
        seen = set()
        for card in elements[:40]:
            try:
                card_text = card.text.strip() if card.text else ""
                if len(card_text) < 15:
                    continue

                links = card.eles('tag:a')
                job_url = ''
                title = ''
                for link in (links or []):
                    try:
                        href = link.attr('href') or ''
                        lt = link.text.strip() if link.text else ''
                        if href and href != '#' and not href.startswith('javascript:') and lt:
                            if not job_url or len(lt) > len(title):
                                job_url = href
                                title = lt
                    except:
                        pass

                if not job_url:
                    job_url = card.attr('data-url') or card.attr('data-link') or ''

                if not job_url.startswith('http'):
                    if job_url.startswith('//'):
                        job_url = 'https:' + job_url
                    else:
                        job_url = 'https://www.zhaopin.com' + ('' if job_url.startswith('/') else '/') + job_url

                key = title + '|' + job_url
                if key not in seen:
                    seen.add(key)
                    lines = [l.strip() for l in card_text.split('\n') if l.strip()]
                    results.append({
                        'url': job_url, 'title': title or (lines[0] if lines else '未知'),
                        'company': lines[1] if len(lines) > 1 else '未知',
                        'salary': '面议', 'location': '未知',
                        'fullText': card_text[:300]
                    })
            except:
                continue

        return [{'type': 'js_data', 'data': r} for r in results]

    def extract_job_info_from_card(self, card) -> Optional[Dict]:
        try:
            # 处理 JS 提取的数据格式
            if isinstance(card, dict) and card.get('type') == 'js_data':
                data = card.get('data', {})
                job_url = data.get('url', '')
                if job_url and not job_url.startswith('http'):
                    if job_url.startswith('//'):
                        job_url = f"https:{job_url}"
                    else:
                        job_url = f"https://www.zhaopin.com{'/' if not job_url.startswith('/') else ''}{job_url}"
                return {
                    'title': data.get('title', '未知'),
                    'company': data.get('company', '未知'),
                    'salary': data.get('salary', '面议'),
                    'location': data.get('location', '未知'),
                    'publish_time': data.get('publish_time', '未知'),
                    'url': job_url
                }

            title = "未知"
            company = "未知"
            salary = "面议"
            location = "未知"
            publish_time = "未知"
            job_url = None

            # 查找岗位链接
            if hasattr(card, 'tag') and card.tag == 'a':
                job_link = card
            elif hasattr(card, 'eles'):
                job_link = None
                all_links = card.eles('tag:a')
                for link in all_links:
                    href = link.attr('href') or ''
                    if any(p in href for p in [
                        '/position/', 'jobs.zhaopin.com', '/job_detail/',
                        '/jobs/', 'CC', 'CZ'
                    ]):
                        job_link = link
                        break
                if not job_link and all_links:
                    # 取第一个有效链接
                    for link in all_links:
                        href = link.attr('href') or ''
                        if href and not href.startswith('#') and not href.startswith('javascript:'):
                            job_link = link
                            break
            else:
                job_link = None

            if job_link:
                job_url = job_link.attr('href')
                if job_url and not job_url.startswith('http'):
                    job_url = f"https:{job_url}" if job_url.startswith('//') else f"https://www.zhaopin.com{job_url}"
                title = job_link.text.strip() if job_link.text else "未知"

            # 提取公司名称
            try:
                company_selectors = [
                    '.company-name',
                    '.complay__name',
                    '.company__name',
                    '.cname',
                    '[class*="company"]'
                ]
                for selector in company_selectors:
                    try:
                        elems = card.eles(selector, timeout=0.5)
                        if elems:
                            company = elems[0].text.strip() if elems[0].text else "未知"
                            if company and company != "未知" and len(company) > 1:
                                break
                    except:
                        pass
            except:
                pass

            # 提取薪资
            try:
                salary_selectors = [
                    '.salary', '.job-salary', '.jobinfo__salary',
                    '[class*="salary"]', '[class*="pay"]'
                ]
                for selector in salary_selectors:
                    try:
                        elems = card.eles(selector, timeout=0.5)
                        if elems:
                            salary = elems[0].text.strip() if elems[0].text else "面议"
                            if salary:
                                break
                    except:
                        pass
            except:
                pass

            # 提取地点
            try:
                loc_selectors = [
                    '.demand', '.job-demands', '.jobinfo__demand',
                    '.job-location', '[class*="location"]', '[class*="address"]'
                ]
                for selector in loc_selectors:
                    try:
                        elems = card.eles(selector, timeout=0.5)
                        if elems:
                            location = elems[0].text.strip() if elems[0].text else "未知"
                            if location:
                                break
                    except:
                        pass
            except:
                pass

            if title == "未知" and not job_url:
                return None

            return {
                'title': title,
                'company': company,
                'salary': salary,
                'location': location,
                'publish_time': publish_time,
                'url': job_url
            }
        except:
            return None

    def get_job_detail_and_hr(self, job_info: Dict, page=None) -> tuple:
        if not job_info.get('url'):
            return None, None

        current_page = page or self.page
        new_tab = None

        try:
            self.log(f"       >> 访问智联详情页...")
            new_tab = current_page.new_tab(job_info['url'])

            # 检测并处理验证复选框
            self._handle_verify_checkbox(new_tab)

            # 等待详情加载
            time.sleep(2)

            detail_parts = []
            hr_name = ""

            # 岗位名称
            try:
                title_selectors = ['.job-name', '.jobinfo__name', '.position-name', 'h1', '.job-title']
                for sel in title_selectors:
                    elem = self.wait_for_element(new_tab, sel, timeout=1)
                    if elem and elem.text:
                        detail_parts.append(f"岗位名称: {elem.text.strip()}")
                        break
            except:
                pass

            # 公司
            try:
                company_selectors = ['.company-name', '.complay__name', '.cname']
                for sel in company_selectors:
                    elem = self.wait_for_element(new_tab, sel, timeout=1)
                    if elem and elem.text:
                        detail_parts.append(f"公司: {elem.text.strip()}")
                        break
            except:
                pass

            # 薪资
            try:
                salary_selectors = ['.salary', '.job-salary', '.jobinfo__salary']
                for sel in salary_selectors:
                    elem = self.wait_for_element(new_tab, sel, timeout=1)
                    if elem and elem.text:
                        detail_parts.append(f"薪资: {elem.text.strip()}")
                        break
            except:
                pass

            # HR 姓名
            try:
                hr_selectors = [
                    '.hr-name',
                    '.recruiter-name',
                    '.publisher-name',
                    '.boss-name',
                ]
                for selector in hr_selectors:
                    try:
                        hr_elem = new_tab.ele(selector, timeout=1)
                        if hr_elem and hr_elem.text:
                            hr_text = hr_elem.text.strip()
                            if hr_text and len(hr_text) > 1 and len(hr_text) < 15:
                                hr_name = hr_text
                                self.log(f"       >> 提取到HR姓名: {hr_name}")
                                break
                    except:
                        continue
            except:
                pass

            # 岗位详情
            try:
                detail_selectors = [
                    '.job-description',
                    '.describtion',
                    '.job-detail',
                    '.position-detail',
                    '.jobinfo__detail',
                    '.responsibility',
                    '.job-require',
                    '.job-main',
                ]
                for selector in detail_selectors:
                    try:
                        detail_elem = self.wait_for_element(new_tab, selector, timeout=1)
                        if detail_elem and detail_elem.text:
                            detail_text = detail_elem.text.strip()
                            if len(detail_text) > 30:
                                detail_parts.append(f"岗位详情:\n{detail_text}")
                                break
                    except:
                        pass
            except:
                pass

            detail_text = "\n\n".join(detail_parts) if detail_parts else "无详情"
            return detail_text, hr_name

        except Exception as e:
            self.log(f"       >> 获取智联详情失败: {e}")
            return None, None
        finally:
            # 确保详情页签总是被关闭，并恢复主页面焦点
            if new_tab:
                try:
                    new_tab.close()
                except:
                    pass
            # 关闭后激活主页面（第一个含 zhaopin.com 的页签），避免 latest_tab 指向过期页签
            try:
                time.sleep(0.3)
                all_tabs = list(current_page.tabs) if hasattr(current_page, 'tabs') else []
                for t in all_tabs:
                    try:
                        if 'zhaopin.com' in (t.url or ''):
                            current_page.activate_tab(t)
                            break
                    except:
                        pass
            except:
                pass

    def deliver_job(self, job_info: Dict, resume_text: str = None,
                    custom_greeting: str = None, page=None) -> bool:
        from config import GREETING_MESSAGE

        self.log(f"       >> [智联] 开始投递: {job_info.get('title')} | {job_info.get('company')}")
        self.log(f"       >> 当前投递数: {self.delivery_count}/{self.max_delivery}")

        if self.delivery_count >= self.max_delivery:
            self.log(f"       >> 已达到单次最大投递数")
            return False

        if self.check_daily_limit():
            return False

        if not job_info.get('url'):
            self.log(f"       >> 没有岗位URL")
            return False

        current_page = page or self.page
        job_title = job_info.get('title', '')
        company = job_info.get('company', '')
        job_url = job_info.get('url')
        delivery_tab = None

        try:
            self.log(f"       >> 打开智联岗位页面...")
            delivery_tab = current_page.new_tab(job_url)
            time.sleep(3)

            # 检测并处理验证复选框
            self._handle_verify_checkbox(delivery_tab)

            # 检测是否有验证码/真人验证
            if self._check_captcha(delivery_tab):
                self.log(f"       >> ⚠ 检测到验证码/真人验证，无法自动处理")
                self.log_delivery(job_info, success=False, reason="需要人工验证")
                return False

            # 步骤1: 查找并点击投递按钮
            apply_clicked = self._click_apply_button(delivery_tab)
            if not apply_clicked:
                self.log(f"       >> 未找到任何投递按钮")
                self.log_delivery(job_info, success=False, reason="未找到投递按钮")
                return False

            self.log(f"       >> 已点击投递按钮，等待响应...")
            time.sleep(2)

            # 点击后也可能弹出验证码
            if self._check_captcha(delivery_tab):
                self.log(f"       >> ⚠ 点击后出现验证码/真人验证")
                self.log_delivery(job_info, success=False, reason="需要人工验证")
                return False

            # 步骤2: 优先检测直接投递成功（智联最常见：点击后页面展示"投递成功"）
            if self._check_delivery_success(delivery_tab):
                self._mark_delivered(job_info, job_title, company, job_url)
                self._cleanup_after_delivery(current_page)
                return True

            # 步骤3: 检查是否有确认弹窗（如"确定投递该职位"）
            if self._confirm_dialog(delivery_tab):
                self.log(f"       >> 确认弹窗已处理，再次检测...")
                time.sleep(1.5)
                if self._check_delivery_success(delivery_tab):
                    self._mark_delivered(job_info, job_title, company, job_url)
                    self._cleanup_after_delivery(current_page)
                    return True

            # 步骤4: 检查是否有聊天弹窗（少数岗位需要先沟通）
            chat_input = self._find_chat_input(delivery_tab)
            if chat_input:
                self.log(f"       >> 检测到聊天输入框，填充打招呼语...")
                greeting = self._gen_greeting(resume_text, custom_greeting, job_title, company,
                                              job_info.get('job_detail', ''))
                if self._fill_and_send_chat(delivery_tab, greeting):
                    time.sleep(1.5)
                    if self._check_delivery_success(delivery_tab):
                        self._mark_delivered(job_info, job_title, company, job_url)
                        self._cleanup_after_delivery(current_page)
                        return True
                    # 发送了消息但无明确成功提示，也视为投递成功
                    if self._no_error_message(delivery_tab):
                        self.log(f"       >> 消息已发送，视为投递成功")
                        self._mark_delivered(job_info, job_title, company, job_url)
                        self._cleanup_after_delivery(current_page)
                        return True
                else:
                    self.log(f"       >> 聊天发送失败")
                    self.log_delivery(job_info, success=False, reason="聊天发送失败")
                    return False

            # 步骤5: 无错误提示，视为投递成功
            if self._no_error_message(delivery_tab):
                self.log(f"       >> 无错误提示，视为投递成功")
                self._mark_delivered(job_info, job_title, company, job_url)
                self._cleanup_after_delivery(current_page)
                return True

            self.log(f"       >> 无法确认投递状态，视为失败")
            self.log_delivery(job_info, success=False, reason="无法确认投递状态")
            return False

        except Exception as e:
            self.log(f"       >> 投递异常: {e}")
            self.log_delivery(job_info, success=False, reason=str(e))
            return False
        finally:
            # 投递失败时兜底：只保留主页面，关闭所有其他页签
            try:
                time.sleep(0.3)
                self._close_extra_tabs(current_page)
            except Exception as e:
                self.log(f"       >> 关闭页签异常: {e}")

    # ── 页签清理 ──

    def _cleanup_after_delivery(self, page):
        """投递成功后：关闭所有页签，只保留主页面"""
        try:
            time.sleep(0.3)
            self._close_extra_tabs(page)
        except Exception as e:
            self.log(f"       >> 清理闲置页签异常: {e}")

    def _close_extra_tabs(self, page):
        """关闭多余页签，只保留智联主页面。
        优先保留第一个含 zhaopin.com 的页签，兜底保留 tabs[0]（最老的页签）。
        """
        try:
            all_tabs = list(page.tabs) if hasattr(page, 'tabs') else []
            if not all_tabs or len(all_tabs) <= 1:
                return

            # 找到要保留的页签索引：优先第一个含 zhaopin.com 的页签
            keep_idx = 0
            for i, t in enumerate(all_tabs):
                try:
                    if 'zhaopin.com' in (t.url or ''):
                        keep_idx = i
                        break
                except:
                    pass

            # 关闭除保留页签外的所有页签
            closed = 0
            for i, t in enumerate(all_tabs):
                if i == keep_idx:
                    continue
                try:
                    t.close()
                    closed += 1
                except:
                    pass

            if closed > 0:
                self.log(f"       >> 已关闭 {closed} 个多余页签，保留主页面")
        except Exception as e:
            self.log(f"       >> 清理页签异常: {e}")

    # ── 验证处理 ──

    def _handle_verify_checkbox(self, tab=None) -> bool:
        """检测并点击智联验证复选框 #verifyCheckbox。
        优先通过监听 captcha.eo.gtimg.com 网络请求来触发，兜底直接查找元素。
        """
        target = tab or self.page

        # 方案1：网络监听 captcha.eo.gtimg.com 请求，请求到达时说明验证组件已加载
        try:
            target.listen.start('captcha.eo.gtimg.com')
            result = target.listen.wait(timeout=4, fit_count=False)
            if result:
                self.log(f"       >> 检测到 captcha 验证请求，等待验证元素渲染...")
                time.sleep(0.5)
                cb = target.ele('#verifyCheckbox', timeout=2)
                if cb:
                    self.log(f"       >> 正在点击验证复选框...")
                    cb.click()
                    time.sleep(2)
                    return True
        except:
            pass
        finally:
            try:
                target.listen.stop()
            except:
                pass

        # 方案2：兜底直接查找 #verifyCheckbox 元素
        try:
            cb = target.ele('#verifyCheckbox', timeout=0.5)
            if cb:
                self.log(f"       >> 检测到验证复选框，正在点击...")
                cb.click()
                time.sleep(2)
                return True
        except:
            pass
        # 也检查当前所有页签中是否有验证页
        try:
            all_tabs = target.tabs if hasattr(target, 'tabs') else []
            for t in all_tabs:
                try:
                    if 'zhaopin.com' in (t.url or '') and 'verify' in (t.url or '').lower():
                        cb = t.ele('#verifyCheckbox', timeout=0.5)
                        if cb:
                            self.log(f"       >> 在验证页签检测到复选框，正在点击...")
                            cb.click()
                            time.sleep(2)
                            return True
                except:
                    pass
        except:
            pass
        return False

    def _click_apply_button(self, tab) -> bool:
        """查找并点击投递/申请按钮，返回是否点击成功"""
        apply_selectors = [
            'text:立即投递',
            'text:投递简历',
            'text:申请职位',
            'text:投递',
            'text:申请',
            '.btn-apply',
            '.apply-btn',
            '.deliver-btn',
            '.resume-btn',
            '.btn-deliver',
            '.op-btn',
            '.btn-primary',
            '[class*="apply"]',
            '[class*="deliver"]',
        ]

        for sel in apply_selectors:
            try:
                btn = tab.ele(sel, timeout=1)
                if btn:
                    self.log(f"       >> 找到投递按钮: {sel}")
                    try:
                        btn.scroll.to_see()
                    except:
                        pass
                    btn.click()
                    return True
            except:
                continue

        # JS 兜底
        try:
            js = """
            const btns = document.querySelectorAll('button, a, span');
            for (let b of btns) {
                const t = (b.innerText || b.textContent || '').trim();
                if (t.includes('投递') || t.includes('申请职位') || t.includes('立即申请')) {
                    b.click();
                    return t;
                }
            }
            return '';
            """
            result = tab.run_js(js)
            if result:
                self.log(f"       >> JS点击投递按钮: {result}")
                return True
        except:
            pass

        return False

    def _check_captcha(self, tab) -> bool:
        """检测是否有验证码/真人验证"""
        captcha_selectors = [
            'text:请完成安全验证',
            'text:拖动滑块',
            'text:请点击图中',
            'text:验证码',
            'text:安全验证',
            '.captcha',
            '.verify-code',
            '.geetest',
            '.slider-captcha',
            '#captcha',
            '.nc_wrapper',
            '.nc_scale',
            '.slider',
        ]
        for sel in captcha_selectors:
            try:
                if tab.ele(sel, timeout=0.3):
                    return True
            except:
                continue
        # JS 检测滑块验证
        try:
            js = """
            return document.querySelector('.nc_wrapper, .nc_scale, .geetest_box, .captcha') !== null;
            """
            if tab.run_js(js):
                return True
        except:
            pass
        return False

    def _find_chat_input(self, tab) -> bool:
        """精准查找可见的聊天输入框（排除隐藏的 textarea 或非聊天用途的输入框）"""
        js = """
        let inputs = document.querySelectorAll('textarea, [contenteditable="true"], .chat-input, .message-input');
        for (let el of inputs) {
            // 必须可见
            if (el.offsetParent !== null) {
                // 排除页面底部非弹窗的输入框（搜索框等）
                let inPopup = el.closest('.dialog, .modal, .popup, .chat, .message-box, ' +
                                          '.greeting-box, .dialog-wrapper');
                if (inPopup) {
                    return true;
                }
                // 或者是 contenteditable 且较小（聊天输入框特征）
                if (el.getAttribute('contenteditable') === 'true') {
                    let rect = el.getBoundingClientRect();
                    if (rect.height < 200) {
                        return true;
                    }
                }
            }
        }
        return false;
        """
        try:
            result = tab.run_js(js)
            return result is True or result == 'true'
        except:
            return False

    def _gen_greeting(self, resume_text, custom_greeting, job_title, company, job_detail):
        """生成打招呼语"""
        from config import GREETING_MESSAGE
        if self.resume_analyzer and resume_text:
            try:
                return self.resume_analyzer.generate_greeting_message(
                    job_title, company, resume_text, job_detail)
            except:
                pass
        return custom_greeting or GREETING_MESSAGE

    def _fill_and_send_chat(self, tab, greeting) -> bool:
        """在聊天弹窗中填写并发送打招呼语"""
        self.log(f"       >> 打招呼语: {greeting[:60]}...")

        # 填写输入框
        js_fill = """
        let inputBox = document.querySelector('.chat-input') ||
                      document.querySelector('textarea:not([style*="display: none"])') ||
                      document.querySelector('[contenteditable="true"]') ||
                      document.querySelector('.message-input');

        if (inputBox) {
            if (inputBox.getAttribute('contenteditable') === 'true') {
                inputBox.innerText = arguments[0];
            } else {
                inputBox.value = arguments[0];
            }
            inputBox.dispatchEvent(new Event('input', { bubbles: true }));
            inputBox.dispatchEvent(new Event('change', { bubbles: true }));
            inputBox.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            inputBox.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', bubbles: true }));
            return '已填写';
        }
        return '未找到输入框';
        """
        try:
            fill_result = tab.run_js(js_fill, greeting)
            self.log(f"       >> 填写结果: {fill_result}")
            if fill_result != '已填写':
                return False
        except Exception as e:
            self.log(f"       >> 填写异常: {e}")
            return False

        time.sleep(0.5)

        # 点击发送按钮
        js_send = """
        const buttons = document.querySelectorAll('button');
        for (let btn of buttons) {
            if (btn.innerText && (btn.innerText.includes('发送') || btn.innerText.includes('提交')) && !btn.disabled) {
                btn.click();
                return '已点击发送';
            }
        }
        let sendBtn = document.querySelector('.send-btn:not([disabled])') ||
                      document.querySelector('.btn-send:not([disabled])') ||
                      document.querySelector('.btn-primary:not([disabled])');
        if (sendBtn) {
            sendBtn.click();
            return '已点击发送';
        }
        return '未找到发送按钮';
        """
        try:
            send_result = tab.run_js(js_send)
            self.log(f"       >> 发送结果: {send_result}")
            time.sleep(1)
            return send_result == '已点击发送'
        except Exception as e:
            self.log(f"       >> 发送异常: {e}")
            return False

    def _confirm_dialog(self, tab) -> bool:
        """处理确认弹窗（如"确定投递该职位"）"""
        confirm_selectors = [
            'text:确定',
            'text:确认',
            'text:提交',
            'text:投递',
            '.confirm-btn',
            '.ok-btn',
            '.btn-confirm',
            '.sure-btn',
        ]
        for sel in confirm_selectors:
            try:
                btn = tab.ele(sel, timeout=0.5)
                if btn:
                    btn.click()
                    self.log(f"       >> 点击确认按钮: {sel}")
                    return True
            except:
                continue
        return False

    def _check_delivery_success(self, tab) -> bool:
        """检测投递是否成功"""
        # CSS 文本匹配
        success_selectors = [
            'text:已投递',
            'text:投递成功',
            'text:申请成功',
            'text:已申请',
            'text:简历已发送',
            'text:沟通中',
            '.delivery-success',
            '.apply-success',
            '.success-tip',
            '.success-toast',
            '.toast-success',
        ]
        for sel in success_selectors:
            try:
                if tab.ele(sel, timeout=0.5):
                    self.log(f"       >> 检测到成功标识: {sel}")
                    return True
            except:
                continue

        # JS 检测：按钮文字变更 + 页面文本匹配
        try:
            js = """
            // 检查按钮文字是否变为已投递
            const btns = document.querySelectorAll('button, a, span, div');
            for (let b of btns) {
                const t = (b.innerText || b.textContent || '').trim();
                if (t.includes('已投递') || t.includes('已申请') || t.includes('投递成功')) {
                    return true;
                }
            }
            // 检查页面可见文本
            const bodyText = document.body ? (document.body.innerText || document.body.textContent || '') : '';
            if (bodyText.includes('投递成功') || bodyText.includes('已投递') || bodyText.includes('简历已发送')) {
                return true;
            }
            return false;
            """
            result = tab.run_js(js)
            if result is True or result == 'true':
                self.log(f"       >> JS检测到投递成功")
                return True
        except:
            pass

        return False

    def _no_error_message(self, tab) -> bool:
        """检查页面没有错误提示"""
        error_selectors = [
            'text:投递失败',
            'text:简历不完整',
            'text:请先完善',
            'text:今日投递已达上限',
            'text:请先登录',
            '.error-tip',
            '.error-msg',
        ]
        for sel in error_selectors:
            try:
                if tab.ele(sel, timeout=0.3):
                    self.log(f"       >> 检测到错误: {sel}")
                    return False
            except:
                continue
        return True

    def _mark_delivered(self, job_info, job_title, company, job_url):
        """标记投递成功"""
        self.delivery_count += 1
        self.log(f"       >> ✅ 投递成功! 总投递数: {self.delivery_count}")
        self.log_delivery(job_info, success=True)
        match_score = job_info.get('match_score', 0)
        hr_name = job_info.get('hr_name', '')
        self.update_job_status(job_url, JOB_STATUS_DELIVERED, job_title, match_score, company, hr_name)
