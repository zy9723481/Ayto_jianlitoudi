import os

# ── MySQL 数据库配置 ──
DB_HOST = 'your-db-host'
DB_PORT = 3306
DB_USER = 'your-db-user'
DB_PASSWORD = 'your-db-password'
DB_NAME = 'boostoudi'

# DeepSeek API 配置 (请替换为您自己的API Key: https://platform.deepseek.com)
DEEPSEEK_API_KEY = "sk-your-api-key-here"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"

# 应用配置
APP_NAME = "BOSS直聘智能投递助手"
APP_VERSION = "3.0.0 Pro"
APP_HOST = "127.0.0.1"
APP_PORT = 5000

BOSS_LOGIN_URL = "https://www.zhipin.com/web/user/?ka=header-login"
BOSS_RESUME_URL = "https://www.zhipin.com/web/geek/resume"

MAX_DELIVERY_COUNT = 100
GREETING_MESSAGE = "您好，我对贵公司的岗位很感兴趣，希望能有机会进一步沟通，谢谢！"

CITY_CODE = "101010100"

CITY_MAP = {
    "101010100": "北京",
    "101020100": "上海",
    "101280100": "广州",
    "101280600": "深圳",
    "101110100": "西安",
    "101120100": "济南",
    "101120200": "青岛",
    "101130100": "南京",
    "101130200": "无锡",
    "101130500": "苏州",
    "101140100": "杭州",
    "101140200": "宁波",
    "101150100": "合肥",
    "101160100": "福州",
    "101160200": "厦门",
    "101170100": "南昌",
    "101180100": "郑州",
    "101190100": "武汉",
    "101200100": "长沙",
    "101210100": "海口",
    "101220100": "成都",
    "101230100": "贵阳",
    "101240100": "昆明",
    "101250100": "兰州",
    "101260100": "沈阳",
    "101260200": "大连",
    "101260300": "鞍山",
    "101270100": "呼和浩特",
    "101280200": "韶关",
    "101280300": "汕头",
    "101280400": "佛山",
    "101280500": "江门",
    "101280700": "珠海",
    "101280800": "肇庆",
    "101280900": "惠州",
    "101281000": "东莞",
    "101281100": "中山",
    "101290100": "南宁",
    "101300100": "石家庄",
    "101300200": "唐山",
    "101310100": "太原",
    "101320100": "哈尔滨",
    "101330100": "长春",
    "101340100": "银川",
    "101350100": "西宁",
    "101360100": "乌鲁木齐",
    "101370100": "拉萨",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

COOKIE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.json")
RESUME_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume.pdf")
ANALYSIS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resume_analysis.json")

FLASK_HOST = "127.0.0.1"
FLASK_PORT = 5000

# 智联招聘配置
ZHI_LIAN_LOGIN_URL = "https://www.zhaopin.com/"
ZHI_LIAN_SEARCH_URL = "https://sou.zhaopin.com/"
ZHI_LIAN_COOKIE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies_zhilian.json")

# 智联招聘城市代码（与 BOSS CITY_MAP 城市名对应，代码体系不同）
ZHI_LIAN_CITY_MAP = {
    "530": "北京",
    "538": "上海",
    "562": "广州",
    "765": "深圳",
    "536": "天津",
    "551": "重庆",
    "635": "杭州",
    "639": "南京",
    "631": "苏州",
    "642": "无锡",
    "632": "常州",
    "636": "宁波",
    "640": "武汉",
    "653": "成都",
    "619": "西安",
    "662": "长沙",
    "600": "郑州",
    "666": "济南",
    "667": "青岛",
    "602": "大连",
    "601": "沈阳",
    "627": "长春",
    "623": "哈尔滨",
    "613": "石家庄",
    "614": "太原",
    "648": "合肥",
    "685": "福州",
    "686": "厦门",
    "665": "南昌",
    "673": "南宁",
    "690": "海口",
    "680": "贵阳",
    "707": "昆明",
    "692": "兰州",
    "720": "呼和浩特",
    "734": "乌鲁木齐",
    "721": "银川",
    "716": "西宁",
    "689": "拉萨",
    "668": "烟台",
    "755": "佛山",
    "769": "东莞",
    "760": "中山",
    "752": "惠州",
    "603": "鞍山",
    "604": "抚顺",
    "612": "唐山",
    "650": "韶关",
    "651": "汕头",
    "654": "江门",
    "655": "肇庆",
    "656": "珠海",
}
