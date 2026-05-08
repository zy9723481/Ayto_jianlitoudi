import time
import json
import os
import random
from typing import List, Dict, Optional
from config import COOKIE_FILE

from delivery_base import BaseDeliveryDP, JOB_STATUS_DELIVERED, JOB_STATUS_SKIPPED


class JobDeliveryDP(BaseDeliveryDP):
    """BOSS 直聘投递引擎"""

    platform_name = "BOSS直聘"
    storage_filename = "jobs_storage_boss.json"
    cookie_file = "cookies.json"
    local_port = 9222
    user_data_dir = "browser_data_boss"

    def __init__(self, page, resume_analyzer=None):
        super().__init__(page, resume_analyzer)

    # ═══════════════════════════════════════════════════════
    #  BOSS 直聘特有实现
    # ═══════════════════════════════════════════════════════

    def build_search_url(self, city_code: str, keyword: str) -> str:
        base = f"https://www.zhipin.com/web/geek/jobs?city={city_code}"
        return f"{base}&query={keyword}"

    def get_job_cards(self, page=None) -> List:
        cards = []
        current_page = page or self.page
        try:
            self.log("正在获取岗位卡片...")

            job_card_selectors = [
                '.job-primary',
                '.job-card',
                '.job-item'
            ]

            job_cards = []
            for selector in job_card_selectors:
                try:
                    cards = current_page.eles(selector, timeout=3)
                    if cards:
                        job_cards = cards
                        self.log(f"使用选择器 {selector} 找到 {len(job_cards)} 个岗位卡片")
                        break
                except Exception as e:
                    continue

            if not job_cards:
                try:
                    all_as = current_page.eles('tag:a', timeout=3)
                    self.log(f"页面a元素总数: {len(all_as)}")

                    filtered_links = []
                    seen_urls = set()

                    for idx, a in enumerate(all_as):
                        try:
                            href = a.attr('href') or ''
                            if 'job_detail' in href:
                                job_url = href
                                if not job_url.startswith('http'):
                                    job_url = f"https://www.zhipin.com{job_url}"

                                if job_url in seen_urls:
                                    continue
                                seen_urls.add(job_url)

                                title = a.text.strip() if a.text else "未知"

                                if title and title not in ["查看更多信息", "职位搜索", "", "未知"]:
                                    if job_url and "job_detail" in job_url and len(job_url) > 50:
                                        self.log(f"  岗位链接 {idx + 1}: {job_url} - {title}")
                                        filtered_links.append(a)
                        except Exception as e:
                            continue

                    cards = filtered_links[:30]
                    self.log(f"找到 {len(cards)} 个岗位链接")
                    return cards
                except Exception as e:
                    self.log(f"获取a元素失败: {e}")
                    return []
            else:
                filtered_cards = []
                seen_urls = set()

                for idx, card in enumerate(job_cards):
                    try:
                        job_links = card.eles('tag:a')
                        job_link = None
                        job_url = None
                        title = "未知"

                        for link in job_links:
                            href = link.attr('href') or ''
                            if 'job_detail' in href:
                                job_link = link
                                job_url = href
                                if not job_url.startswith('http'):
                                    job_url = f"https://www.zhipin.com{job_url}"
                                title = link.text.strip() if link.text else "未知"
                                break

                        if job_url and job_url not in seen_urls:
                            seen_urls.add(job_url)
                            if title and title not in ["查看更多信息", "职位搜索", "", "未知"]:
                                if len(job_url) > 50:
                                    self.log(f"  岗位卡片 {idx + 1}: {job_url} - {title}")
                                    filtered_cards.append(card)
                    except Exception as e:
                        continue

                cards = filtered_cards[:30]
                self.log(f"找到 {len(cards)} 个岗位卡片")
                return cards

        except Exception as e:
            self.log(f"获取岗位卡片失败: {e}")
            import traceback
            traceback.print_exc()

        return cards

    def extract_job_info_from_card(self, card) -> Optional[Dict]:
        try:
            title = "未知"
            company = "未知"
            salary = "面议"
            location = "未知"
            publish_time = "未知"
            job_url = None

            if card.tag == 'a':
                job_link = card
            else:
                job_link = None
                all_links = card.eles('tag:a')
                for link in all_links:
                    href = link.attr('href') or ''
                    if 'job_detail' in href:
                        job_link = link
                        break

            if job_link:
                job_url = job_link.attr('href')
                if job_url and not job_url.startswith('http'):
                    job_url = f"https://www.zhipin.com{job_url}"
                title = job_link.text.strip() if job_link.text else "未知"

            try:
                company_selectors = [
                    '.company-name',
                    '.company',
                    '.company-text'
                ]
                for selector in company_selectors:
                    try:
                        company_elements = card.eles(selector, timeout=1)
                        if company_elements:
                            company = company_elements[0].text.strip() if company_elements[0].text else "未知"
                            if company != "未知":
                                break
                    except:
                        pass

                if company == "未知":
                    company_elements = card.eles('tag:span', timeout=1)
                    for elem in company_elements:
                        text = elem.text.strip() if elem.text else ""
                        if text and len(text) > 2 and len(text) < 50:
                            if "公司" in text or "科技" in text or "集团" in text or "有限公司" in text:
                                company = text
                                break
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

        try:
            self.log(f"       >> 访问详情页...")
            new_tab = current_page.new_tab(job_info['url'])

            try:
                self.wait_for_element(new_tab, '.job-name', timeout=3)
            except:
                pass

            detail_parts = []
            hr_name = ""

            try:
                title_elem = self.wait_for_element(new_tab, '.job-name, .name, h1', timeout=2)
                if title_elem and title_elem.text:
                    detail_parts.append(f"岗位名称: {title_elem.text.strip()}")
            except:
                pass

            try:
                salary_elem = self.wait_for_element(new_tab, '.salary, .job-salary', timeout=2)
                if salary_elem and salary_elem.text:
                    detail_parts.append(f"薪资: {salary_elem.text.strip()}")
            except:
                pass

            try:
                company_elem = self.wait_for_element(new_tab, '.company-name, .name, .company-title', timeout=2)
                if company_elem and company_elem.text:
                    detail_parts.append(f"公司: {company_elem.text.strip()}")
            except:
                pass

            try:
                hr_selectors = [
                    '.boss-name',
                    '.recruiter-name',
                    '.hr-name',
                    '.name'
                ]
                for selector in hr_selectors:
                    try:
                        hr_elem = new_tab.ele(selector, timeout=1)
                        if hr_elem and hr_elem.text:
                            hr_text = hr_elem.text.strip()
                            if hr_text and len(hr_text) > 1 and len(hr_text) < 10:
                                hr_name = hr_text
                                self.log(f"       >> 提取到HR姓名: {hr_name}")
                                break
                    except:
                        continue
            except:
                pass

            try:
                detail_selectors = [
                    '.job-detail-section',
                    '.job-detail',
                    '.job-sec',
                    '.job-description'
                ]
                for selector in detail_selectors:
                    try:
                        detail_elem = self.wait_for_element(new_tab, selector, timeout=1)
                        if detail_elem and detail_elem.text:
                            detail_text = detail_elem.text.strip()
                            if len(detail_text) > 50:
                                detail_parts.append(f"岗位详情:\n{detail_text}")
                                break
                    except:
                        pass
            except:
                pass

            self.log(f"       >> 返回列表页...")
            try:
                new_tab.close()
            except:
                pass

            detail_text = "\n\n".join(detail_parts) if detail_parts else "无详情"
            return detail_text, hr_name

        except Exception as e:
            self.log(f"       >> 获取详情失败: {e}")
            try:
                if 'new_tab' in locals():
                    new_tab.close()
            except:
                pass
            return None, None

    def deliver_job(self, job_info: Dict, resume_text: str = None,
                    custom_greeting: str = None, page=None) -> bool:
        from config import GREETING_MESSAGE

        self.log(f"       >> deliver_job 被调用了!")
        self.log(f"       >> 岗位URL: {job_info.get('url')}")
        self.log(f"       >> 当前投递数: {self.delivery_count}/{self.max_delivery}")

        if self.delivery_count >= self.max_delivery:
            self.log(f"       >> 已达到单次最大投递数")
            return False

        if self.check_daily_limit():
            return False

        current_page = page or self.page
        send_success = False
        job_title = job_info.get('title', '')
        company = job_info.get('company', '')

        try:
            if not job_info.get('url'):
                self.log(f"       >> 没有岗位URL")
                return False

            self.log(f"       >> 访问岗位投递...")
            delivery_tab = current_page.new_tab(job_info['url'])

            try:
                self.wait_for_element(delivery_tab, '.start-chat-btn', timeout=3)
            except:
                pass

            chat_btn = None
            chat_selectors = [
                '.start-chat-btn',
                '.btn-startchat',
                '[ka="chat-start"]',
                '.op-btn',
                '.chat-btn',
                '.contact-btn',
                '.btn-primary',
                'text:立即沟通',
                'text:打招呼',
                'text:沟通'
            ]

            for sel in chat_selectors:
                try:
                    chat_btn = delivery_tab.ele(sel, timeout=1)
                    if chat_btn:
                        self.log(f"       >> 找到沟通按钮: {sel}")
                        break
                except:
                    continue

            if chat_btn:
                self.log(f"       >> 点击沟通...")
                try:
                    chat_btn.scroll.to_see()
                except:
                    pass
                chat_btn.click()

                job_detail = job_info.get('job_detail', '')

                if self.resume_analyzer and resume_text:
                    self.log(f"       >> 正在生成个性化打招呼语...")
                    greeting = self.resume_analyzer.generate_greeting_message(
                        job_title, company, resume_text, job_detail)
                    self.log(f"       >> 打招呼语: {greeting[:50]}...")
                else:
                    greeting = custom_greeting or GREETING_MESSAGE

                self.log(f"       >> 等待聊天页面加载...")
                time.sleep(2)

                try:
                    delivery_tab.scroll.to_bottom()
                    time.sleep(0.5)
                except:
                    pass

                self.log(f"       >> 使用JavaScript输入打招呼语...")

                input_success = False
                try:
                    js_input = """
                    let inputBox = document.querySelector('.chat-input') ||
                                  document.querySelector('textarea') ||
                                  document.querySelector('[contenteditable="true"]') ||
                                  document.querySelector('.message-input') ||
                                  document.querySelector('#chat-input');

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

                        return '输入成功';
                    } else {
                        return '未找到输入框';
                    }
                    """

                    input_result = delivery_tab.run_js(js_input, greeting)
                    self.log(f"       >> JavaScript输入结果: {input_result}")
                    input_success = (input_result == '输入成功')
                except Exception as e:
                    self.log(f"       >> JavaScript输入失败: {e}")

                if input_success:
                    self.log(f"       >> 等待按钮激活并发送...")
                    time.sleep(1)

                    try:
                        js_send = """
                        const buttons = document.querySelectorAll('button');
                        for (let btn of buttons) {
                            if (btn.innerText && btn.innerText.includes('发送') && !btn.disabled) {
                                btn.click();
                                return '已点击发送按钮';
                            }
                        }

                        let sendBtn = document.querySelector('.send-btn:not([disabled])') ||
                                      document.querySelector('.btn-send:not([disabled])') ||
                                      document.querySelector('[ka="chat-send"]:not([disabled])') ||
                                      document.querySelector('.btn-primary:not([disabled])');

                        if (sendBtn) {
                            sendBtn.click();
                            return '已点击发送按钮';
                        }

                        return '未找到发送按钮';
                        """
                        send_result = delivery_tab.run_js(js_send)
                        self.log(f"       >> JavaScript发送结果: {send_result}")

                        if send_result == '已点击发送按钮':
                            send_success = True
                            self.delivery_count += 1
                            self.log(f"       >> 投递成功，总投递数: {self.delivery_count}")
                            self.log_delivery(job_info, success=True)
                        else:
                            self.log(f"       >> JavaScript未找到按钮，尝试DrissionPage...")
                            send_selectors = [
                                'text:发送',
                                '.send-btn',
                                '.btn-send',
                                '.send-button',
                                '[ka="chat-send"]'
                            ]
                            for sel in send_selectors:
                                try:
                                    elem = delivery_tab.ele(sel, timeout=2)
                                    if elem:
                                        elem.click()
                                        self.log(f"       >> 使用DrissionPage点击发送按钮: {sel}")
                                        send_success = True
                                        self.delivery_count += 1
                                        self.log(f"       >> 投递成功，总投递数: {self.delivery_count}")
                                        self.log_delivery(job_info, success=True)
                                        break
                                except:
                                    continue
                            if not send_success:
                                self.log_delivery(job_info, success=False, reason="未找到发送按钮")
                    except Exception as e:
                        self.log(f"       >> 发送失败: {e}")
                        self.log_delivery(job_info, success=False, reason=f"发送失败: {e}")
                else:
                    self.log_delivery(job_info, success=False, reason="输入失败")

                job_url = job_info.get('url')
                if job_url and send_success:
                    match_score = job_info.get('match_score', 0)
                    hr_name = job_info.get('hr_name', '')
                    self.update_job_status(job_url, JOB_STATUS_DELIVERED, job_title, match_score, company, hr_name)
                    self.log(f"       >> 岗位状态更新为: 已投递")

                self.log(f"       >> 等待发送完成...")
                time.sleep(2)

                try:
                    delivery_tab.close()
                except:
                    pass

                return send_success
            else:
                self.log(f"       >> 未找到沟通按钮")
                self.log_delivery(job_info, success=False, reason="未找到沟通按钮")
                try:
                    delivery_tab.close()
                except:
                    pass
                return False
        except Exception as e:
            self.log(f"       >> 投递失败: {e}")
            try:
                if 'delivery_tab' in locals():
                    delivery_tab.close()
            except:
                pass
            self.log_delivery(job_info, success=False, reason=str(e))
            return False
