import os
import json
import PyPDF2
import openai
from config import (
    DEEPSEEK_API_KEY, 
    DEEPSEEK_BASE_URL, 
    DEEPSEEK_MODEL,
    RESUME_FILE
)


class ResumeAnalyzer:
    def __init__(self, api_key=None, base_url=None, model=None):
        self.api_key = api_key or DEEPSEEK_API_KEY
        self.base_url = base_url or DEEPSEEK_BASE_URL
        self.model = model or DEEPSEEK_MODEL
        self.client = openai.OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
        self.resume_content = None
        self.resume_text = None
        self.log_callback = None  # 可设置外部日志回调

    def _log(self, msg):
        timestamp = __import__('datetime').datetime.now().strftime('%H:%M:%S')
        log_msg = f"[{timestamp}] [AI] {msg}"
        print(log_msg)
        if self.log_callback:
            try:
                self.log_callback(log_msg)
            except:
                pass

    def extract_text_from_pdf(self, pdf_path):
        try:
            text = ""
            with open(pdf_path, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                for page in reader.pages:
                    text += page.extract_text() + "\n"
            self.resume_text = text
            return text
        except Exception as e:
            print(f"PDF解析失败: {e}")
            return None

    def extract_text_from_docx(self, docx_path):
        try:
            from docx import Document
            doc = Document(docx_path)
            text = ""
            for para in doc.paragraphs:
                text += para.text + "\n"
            self.resume_text = text
            return text
        except ImportError:
            print("请安装python-docx库: pip install python-docx")
            return None
        except Exception as e:
            print(f"Word文档解析失败: {e}")
            return None

    def analyze_resume(self, resume_text=None):
        text = resume_text or self.resume_text
        if not text:
            return None
        
        prompt = f"""请分析以下简历内容，并推荐适合投递的岗位类型和关键词。

简历内容：
{text}

请从以下角度分析：
1. 候选人的核心技能和优势
2. 适合投递的岗位类型（列出5-10个具体岗位名称）
3. 搜索岗位时应使用的关键词
4. 建议投递的行业方向

请以JSON格式返回结果，格式如下：
{{
    "skills": ["技能1", "技能2"],
    "recommended_positions": ["岗位1", "岗位2"],
    "search_keywords": ["关键词1", "关键词2"],
    "recommended_industries": ["行业1", "行业2"]
}}
"""
        
        try:
            import time as _time
            self._log(f"请求简历分析 (模型: {self.model})")
            t0 = _time.time()

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个专业的职业规划顾问，擅长分析简历并推荐合适的岗位。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7
            )

            elapsed = _time.time() - t0
            result = response.choices[0].message.content
            self._log(f"简历分析响应成功 (耗时 {elapsed:.1f}s): {result[:150]}...")

            try:
                json_start = result.find('{')
                json_end = result.rfind('}') + 1
                if json_start != -1 and json_end > json_start:
                    json_str = result[json_start:json_end]
                    data = json.loads(json_str)
                    self._log(f"简历分析解析成功: 推荐{len(data.get('recommended_positions', []))}个岗位")
                    return data
            except:
                pass

            return {"raw_analysis": result}
        except Exception as e:
            self._log(f"简历分析API请求失败: {e}")
            return None

    def calculate_match_score(self, resume_text, job_title, job_detail, company_name=""):
        prompt = f"""请分析简历与岗位的匹配程度。

简历内容：
{resume_text[:2500]}

岗位名称：{job_title}
公司名称：{company_name}
岗位详情：
{job_detail[:2000]}

请从以下维度评估匹配度：
1. 技能匹配度（候选人技能是否符合岗位要求）
2. 经验匹配度（工作年限和经验是否匹配）
3. 行业匹配度（是否有相关行业经验）
4. 岗位职责匹配度（是否能胜任主要工作内容）

请以JSON格式返回结果：
{{
    "score": 85,
    "skill_match": "高/中/低",
    "experience_match": "高/中/低", 
    "industry_match": "高/中/低",
    "reasons": ["匹配原因1", "匹配原因2"],
    "concerns": ["可能的不足1"],
    "job_requirements": ["要求1", "要求2"]
}}

score为0-100的整数，表示总体匹配度。
job_requirements为岗位的主要要求列表。
"""
        
        try:
            import time as _time
            self._log(f"请求匹配度: {job_title} @ {company_name} (模型: {self.model})")
            t0 = _time.time()

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个专业的HR，擅长评估简历与岗位的匹配程度。请客观、准确地进行评估。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )

            elapsed = _time.time() - t0
            result = response.choices[0].message.content
            self._log(f"匹配度响应成功 (耗时 {elapsed:.1f}s): {result[:150]}...")

            try:
                json_start = result.find('{')
                json_end = result.rfind('}') + 1
                if json_start != -1 and json_end > json_start:
                    json_str = result[json_start:json_end]
                    data = json.loads(json_str)
                    score = data.get('match_score', data.get('score', 50))
                    self._log(f"匹配度解析成功: score={score}")
                    return {
                        'score': score,
                        'skill_match': data.get('skill_match', '中'),
                        'experience_match': data.get('experience_match', '中'),
                        'industry_match': data.get('industry_match', '中'),
                        'reasons': data.get('reasons', []),
                        'concerns': data.get('concerns', []),
                        'job_requirements': data.get('job_requirements', [])
                    }
            except Exception as e:
                self._log(f"匹配度JSON解析失败: {e}, 原始: {result[:100]}")

            return {'score': 50, 'reasons': [], 'concerns': [], 'job_requirements': []}
        except Exception as e:
            self._log(f"匹配度API请求失败: {e}")
            return {'score': 50, 'reasons': [], 'concerns': [], 'job_requirements': []}

    def generate_greeting_message(self, job_title, company_name, resume_text=None, job_detail=""):
        text = resume_text or self.resume_text
        
        prompt = f"""请根据简历和岗位详情，生成一段专业、诚实且多样化的打招呼语。

【重要规则 - 绝对不能违反】
1. 绝对不能编造简历中没有的技能、经验或项目
2. 只能使用简历中明确提到的内容
3. 如果简历中没有明确提到的内容，绝对不能在打招呼语中出现
4. 不要过度引申或夸大简历内容
5. 绝对不要提及HR的姓名
6. 每次生成的打招呼语都要不一样，不要重复相同的开场白
7. 不要固定说"拥有X年测试与需求分析结合经验"这种话，要根据简历内容灵活组织语言

简历内容（必须严格基于此生成）：
{text[:2000] if text else '无'}

岗位名称：{job_title}
公司名称：{company_name}
岗位详情：
{job_detail[:1500] if job_detail else '无'}

要求：
1. 长度控制在80-120字
2. 只突出简历中明确提到的技能和经验
3. 绝对不能编造任何简历中没有的内容
4. 不要提及HR姓名
5. 表达求职意向，语气专业、真诚
6. 不要使用"贵公司"等过于客套的词
7. 每次生成的打招呼语都要有变化，不要千篇一律
8. 直接返回打招呼内容，不要其他解释

多样化示例格式：
示例1：您好，我有3年软件测试经验，熟练掌握功能测试、接口测试和Python自动化，曾参与电商平台测试项目。对您的{job_title}岗位很感兴趣，希望能进一步沟通！
示例2：您好，我在软件测试领域有丰富的经验，熟悉测试流程和用例设计，能够独立完成测试任务。对您公司的{job_title}岗位很感兴趣！
示例3：您好，我有多年测试和需求分析相关经验，能够快速理解业务需求并执行测试。对您的{job_title}岗位很感兴趣，希望有机会交流！"""
        
        try:
            import time as _time
            self._log(f"请求生成打招呼语: {job_title} @ {company_name}")
            t0 = _time.time()

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个诚实且有创意的求职助手，帮助生成专业、诚实且多样化的打招呼语，绝对不能编造任何简历中没有的内容。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.5
            )

            elapsed = _time.time() - t0
            result = response.choices[0].message.content.strip()
            self._log(f"打招呼语生成成功 (耗时 {elapsed:.1f}s): {result[:80]}...")
            return result
        except Exception as e:
            self._log(f"打招呼语API请求失败: {e}")
            return f"您好，我对{company_name}的{job_title}岗位很感兴趣，我有相关经验，希望能有机会进一步沟通，谢谢！"
    
    def organize_job_detail(self, job_detail):
        """整理岗位详情"""
        prompt = f"""请整理以下岗位详情，使其更加清晰、结构化。

岗位详情：
{job_detail}

要求：
1. 提取并整理岗位职责
2. 提取并整理任职要求
3. 去除无关信息（如广告、举报链接等）
4. 使用清晰的标题和列表格式
5. 保持内容的完整性和准确性

直接返回整理后的内容，不要其他解释。"""
        
        try:
            import time as _time
            self._log(f"请求整理岗位详情")
            t0 = _time.time()

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个专业的HR助手，擅长整理和结构化岗位信息。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )

            elapsed = _time.time() - t0
            result = response.choices[0].message.content.strip()
            self._log(f"岗位详情整理成功 (耗时 {elapsed:.1f}s)")
            return result
        except Exception as e:
            self._log(f"岗位详情API请求失败: {e}")
            return job_detail
