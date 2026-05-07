import pymysql
import os
import uuid
import hashlib
import platform
import subprocess
from datetime import datetime

# MySQL 配置 — 从 config 导入，不硬编码敏感信息
try:
    from config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME
except ImportError:
    # 安全回退：部署时请在 config.py 中配置真实值
    DB_HOST = 'localhost'
    DB_PORT = 3306
    DB_USER = 'root'
    DB_PASSWORD = ''
    DB_NAME = 'boostoudi'


def get_db():
    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False
    )
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(100) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            email VARCHAR(200) DEFAULT '',
            created_at DATETIME NOT NULL DEFAULT NOW(),
            last_login DATETIME,
            is_banned TINYINT DEFAULT 0
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS cards (
            id INT AUTO_INCREMENT PRIMARY KEY,
            card_key VARCHAR(255) NOT NULL UNIQUE,
            card_hash VARCHAR(255) NOT NULL UNIQUE,
            card_type VARCHAR(20) NOT NULL,
            duration_days INT NOT NULL DEFAULT 0,
            status VARCHAR(20) NOT NULL DEFAULT 'unused',
            created_at DATETIME NOT NULL DEFAULT NOW(),
            used_by INT,
            used_at DATETIME,
            expires_at DATETIME,
            machine_fp VARCHAR(100) DEFAULT ''
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS licenses (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            card_id INT NOT NULL,
            machine_fp VARCHAR(100) NOT NULL DEFAULT '',
            activated_at DATETIME NOT NULL DEFAULT NOW(),
            expires_at DATETIME,
            is_active TINYINT DEFAULT 1
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS delivery_log (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            company VARCHAR(255) DEFAULT '',
            job_title VARCHAR(255) DEFAULT '',
            match_score INT DEFAULT 0,
            success TINYINT DEFAULT 0,
            platform VARCHAR(20) DEFAULT 'boss',
            created_at DATETIME NOT NULL DEFAULT NOW()
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # 兼容旧表：添加 platform 列（如果不存在）
    try:
        cur.execute("ALTER TABLE delivery_log ADD COLUMN platform VARCHAR(20) DEFAULT 'boss'")
    except:
        pass

    conn.commit()
    conn.close()


def get_machine_fingerprint():
    fp_parts = []
    try:
        fp_parts.append(platform.node())
        fp_parts.append(platform.machine())
    except:
        pass
    try:
        if os.name == 'nt':
            r = subprocess.run(['wmic', 'csproduct', 'get', 'uuid'], capture_output=True, text=True, timeout=5)
            if r.stdout:
                fp_parts.append(r.stdout.strip())
    except:
        pass
    try:
        import uuid as _uuid
        fp_parts.append(str(_uuid.getnode()))
    except:
        pass
    raw = '|'.join(fp_parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def record_delivery(user_id, company, job_title, match_score, success, platform='boss'):
    """记录一次投递到数据库"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO delivery_log (user_id, company, job_title, match_score, success, platform) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (user_id, company, job_title, match_score, 1 if success else 0, platform)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"记录投递日志失败: {e}")


def get_today_delivery_count(user_id, platform=None):
    """获取今日投递总数，可选按平台过滤"""
    try:
        conn = get_db()
        cur = conn.cursor()
        if platform:
            cur.execute(
                "SELECT COUNT(*) as cnt FROM delivery_log "
                "WHERE user_id=%s AND platform=%s AND DATE(created_at)=CURDATE() AND success=1",
                (user_id, platform)
            )
        else:
            cur.execute(
                "SELECT COUNT(*) as cnt FROM delivery_log "
                "WHERE user_id=%s AND DATE(created_at)=CURDATE() AND success=1",
                (user_id,)
            )
        result = cur.fetchone()
        conn.close()
        return result['cnt'] if result else 0
    except Exception as e:
        print(f"查询今日投递数失败: {e}")
        return 0


def get_today_delivery_stats(user_id):
    """获取今日投递统计（按平台分）"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT platform, COUNT(*) as cnt FROM delivery_log "
            "WHERE user_id=%s AND DATE(created_at)=CURDATE() AND success=1 "
            "GROUP BY platform",
            (user_id,)
        )
        rows = cur.fetchall()
        conn.close()
        stats = {'boss': 0, 'zhilian': 0, 'total': 0}
        for row in rows:
            p = row['platform'] or 'boss'
            stats[p] = row['cnt']
            stats['total'] += row['cnt']
        return stats
    except Exception as e:
        print(f"查询今日投递统计失败: {e}")
        return {'boss': 0, 'zhilian': 0, 'total': 0}
