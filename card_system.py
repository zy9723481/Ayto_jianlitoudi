import hashlib
import secrets
import string
from datetime import datetime, timedelta
from database import get_db

CARD_TYPES = {
    'trial':    {'label': '试用卡(3天)',  'days': 3},
    'monthly':  {'label': '月卡(30天)',   'days': 30},
    'quarterly':{'label': '季卡(90天)',   'days': 90},
    'yearly':   {'label': '年卡(365天)',  'days': 365},
    'permanent':{'label': '永久卡',       'days': 0},
}

SEGMENT_LENGTH = 4
SEGMENT_COUNT = 4


def _to_datetime(val):
    """将数据库返回值统一转为 datetime 对象（兼容 MySQL datetime 和 SQLite 字符串）"""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    try:
        return datetime.strptime(val, '%Y-%m-%d %H:%M:%S')
    except:
        return None


def _generate_segment():
    chars = string.ascii_uppercase + string.digits
    chars = chars.replace('O','').replace('0','').replace('I','').replace('1','').replace('L','')
    return ''.join(secrets.choice(chars) for _ in range(SEGMENT_LENGTH))


def generate_card_keys(card_type, count=1):
    if card_type not in CARD_TYPES:
        raise ValueError(f"Invalid card type: {card_type}")

    days = CARD_TYPES[card_type]['days']
    conn = get_db()
    cur = conn.cursor()
    generated = []

    for _ in range(count):
        while True:
            segments = [_generate_segment() for _ in range(SEGMENT_COUNT)]
            card_key = '-'.join(segments)
            card_hash = hashlib.sha256(card_key.encode()).hexdigest()
            cur.execute("SELECT id FROM cards WHERE card_hash=%s", (card_hash,))
            if not cur.fetchone():
                break

        cur.execute(
            "INSERT INTO cards (card_key, card_hash, card_type, duration_days) VALUES (%s,%s,%s,%s)",
            (card_key, card_hash, card_type, days)
        )
        generated.append(card_key)

    conn.commit()
    conn.close()
    return generated


def verify_and_activate_card(card_key, user_id, machine_fp):
    card_hash = hashlib.sha256(card_key.strip().upper().encode()).hexdigest()
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM cards WHERE card_hash=%s", (card_hash,))
    card = cur.fetchone()
    if not card:
        conn.close()
        return False, "卡密无效，请检查是否输入正确"

    if card['status'] == 'used':
        conn.close()
        return False, "此卡密已被使用"
    if card['status'] == 'disabled':
        conn.close()
        return False, "此卡密已被禁用"
    if card['status'] == 'expired':
        conn.close()
        return False, "此卡密已过期"

    now = datetime.now()
    days = card['duration_days']
    expires_at = None if days == 0 else (now + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')

    # Check if user already has active license — stack/replace logic
    cur.execute("SELECT * FROM licenses WHERE user_id=%s AND is_active=1", (user_id,))
    existing = cur.fetchall()

    if existing:
        # Extend from the latest expiry or now
        latest_expiry = None
        for lic in existing:
            if lic['expires_at']:
                exp = _to_datetime(lic['expires_at'])
                if exp and (latest_expiry is None or exp > latest_expiry):
                    latest_expiry = exp

        if card['card_type'] == 'permanent':
            expires_at = None
        elif latest_expiry and latest_expiry > now:
            expires_at = (latest_expiry + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')

        # Deactivate old licenses
        cur.execute("UPDATE licenses SET is_active=0 WHERE user_id=%s", (user_id,))

    cur.execute(
        "UPDATE cards SET status='used', used_by=%s, used_at=%s, expires_at=%s, machine_fp=%s WHERE id=%s",
        (user_id, now.strftime('%Y-%m-%d %H:%M:%S'), expires_at, machine_fp, card['id'])
    )

    cur.execute(
        "INSERT INTO licenses (user_id, card_id, machine_fp, expires_at, is_active) VALUES (%s,%s,%s,%s,1)",
        (user_id, card['id'], machine_fp, expires_at)
    )

    conn.commit()
    conn.close()

    if card['card_type'] == 'permanent':
        return True, "永久卡激活成功，永久有效！"
    else:
        exp_str = expires_at[:10] if expires_at else '永久'
        return True, f"{CARD_TYPES[card['card_type']]['label']}激活成功，到期时间: {exp_str}"


def check_user_license(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM licenses WHERE user_id=%s AND is_active=1 ORDER BY activated_at DESC LIMIT 1",
        (user_id,)
    )
    lic = cur.fetchone()
    conn.close()

    if not lic:
        return {'active': False, 'reason': '未激活', 'expires_at': None, 'card_type': None}

    if lic['expires_at']:
        exp = _to_datetime(lic['expires_at'])
        if exp and datetime.now() > exp:
            return {'active': False, 'reason': '已过期', 'expires_at': lic['expires_at'], 'card_type': None}

    # Get card type
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT card_type, duration_days FROM cards WHERE id=%s", (lic['card_id'],))
    card = cur.fetchone()
    conn.close()

    return {
        'active': True,
        'reason': '正常',
        'expires_at': lic['expires_at'],
        'card_type': card['card_type'] if card else 'unknown',
        'activated_at': lic['activated_at']
    }


def get_expiry_text(expires_at):
    if not expires_at:
        return '永久有效'
    exp = _to_datetime(expires_at)
    if exp is None:
        return '永久有效'
    days_left = (exp - datetime.now()).days
    if days_left < 0:
        return '已过期'
    elif days_left == 0:
        return '今日到期'
    elif days_left <= 3:
        return f'剩余 {days_left} 天 (即将到期)'
    else:
        return f'剩余 {days_left} 天'
