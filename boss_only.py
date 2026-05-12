import os
import time
import json
import tkinter as tk
import threading
from tkinter import ttk, scrolledtext, filedialog, messagebox
from datetime import datetime

import bcrypt

from database import init_db, get_db, get_machine_fingerprint, record_delivery, get_today_delivery_stats
from card_system import CARD_TYPES, generate_card_keys, verify_and_activate_card, check_user_license, get_expiry_text
from config import MAX_DELIVERY_COUNT, GREETING_MESSAGE, COOKIE_FILE, ANALYSIS_FILE, CITY_MAP
try:
    from config import MAX_DAILY_DELIVERY
except ImportError:
    MAX_DAILY_DELIVERY = 200

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.log")
DELIVERY_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "delivery_config.json")


def log(msg):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_msg = f"[{timestamp}] {msg}"
    print(log_msg)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_msg + '\n')
    except:
        pass


# ═══════════════════════════════════════════════════════════════════
#  FlatButton — tk.Label based button that ALWAYS renders custom
#  colors on Windows (unlike tk.Button/ttk.Button which may be
#  overridden by the OS theme).
# ═══════════════════════════════════════════════════════════════════

class FlatButton(tk.Label):
    """A clickable label that looks like a flat-styled button.
    Uses tk.Label so custom bg/fg colors are guaranteed to render
    on Windows regardless of OS theme."""

    def __init__(self, parent, text='', bg='#667eea', fg='#ffffff',
                 hover_bg=None, font=None, command=None, width=None,
                 padding=None, cursor='hand2', **kw):
        self._bg = bg
        self._fg = fg
        self._hover_bg = hover_bg or self._adjust_hover(bg)
        self._disabled_bg = '#3a3f55'
        self._disabled_fg = '#6b6f82'
        self._command = command
        self._enabled = True

        if font is None:
            font = ('Microsoft YaHei UI', 10, 'bold')
        if padding is None:
            padding = (20, 10)

        super().__init__(parent, text=text, bg=bg, fg=fg,
                         font=font, cursor=cursor,
                         anchor='center', justify='center', **kw)
        self.pack_config = {'padx': 0, 'pady': 0, 'ipadx': padding[0], 'ipady': padding[1]}

        self.bind('<Enter>', self._on_enter)
        self.bind('<Leave>', self._on_leave)
        if command:
            self.bind('<Button-1>', self._on_click)

    @staticmethod
    def _adjust_hover(c):
        if c.startswith('#'):
            try:
                r, g, b = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
                r = min(255, max(0, r - 20))
                g = min(255, max(0, g - 20))
                b = min(255, max(0, b - 20))
                return f'#{r:02x}{g:02x}{b:02x}'
            except:
                pass
        return c

    def _on_enter(self, e):
        if self._enabled:
            self.config(bg=self._hover_bg)

    def _on_leave(self, e):
        if self._enabled:
            self.config(bg=self._bg)

    def _on_click(self, e):
        if self._enabled and self._command:
            self._command()

    def state(self, states):
        """兼容 ttk 风格: state(['disabled']) / state(['!disabled'])"""
        if 'disabled' in states:
            self._enabled = False
            self.config(bg=self._disabled_bg, fg=self._disabled_fg, cursor='arrow')
        elif '!disabled' in states:
            self._enabled = True
            self.config(bg=self._bg, fg=self._fg, cursor='hand2')

    def pack(self, **kw):
        cfg = dict(self.pack_config)
        cfg.update(kw)
        super().pack(**cfg)

    def enable(self):
        self._enabled = True
        self.config(bg=self._bg, fg=self._fg, cursor='hand2')

    def disable(self):
        self._enabled = False
        self.config(bg=self._disabled_bg, fg=self._disabled_fg, cursor='')

    def set_text(self, text):
        self.config(text=text)


# ═══════════════════════════════════════════════════════════════════
#  Main Application
# ═══════════════════════════════════════════════════════════════════

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BOSS直聘智能投递助手 v3.0 Pro")
        self.geometry("1060x780")
        self.minsize(960, 680)
        self.configure(bg='#0f1119')

        # State
        self.user_id = None
        self.username = None
        self.license_info = None

        # Login mode: None / 'self_ai' / 'builtin'
        self.login_mode = None
        # Mode 1 user AI config
        self.user_ai_config = {
            'api_key': '',
            'base_url': 'https://api.deepseek.com',
            'model': 'deepseek-v4-flash'
        }

        # Delivery state — BOSS
        self.page = None
        self.logged_in = False
        self.delivery = None

        # Shared delivery state
        self.analyzer = None
        self.delivery_running = False
        self.delivery_threads = []
        self.resume_path = None
        self.resume_text = None
        self.analysis_result = None
        self.current_job_index = 0
        self.matched_jobs = []
        self.daily_state = None
        self.boss_started = False
        self.boss_completed = False

        # Setup styles
        self._setup_styles()

        # Container for all pages
        self.container = tk.Frame(self, bg='#0f1119')
        self.container.pack(fill=tk.BOTH, expand=True)

        self.frames = {}
        for F in (LoginFrame, RegisterFrame, ActivateFrame, MainFrame):
            frame = F(self.container, self)
            self.frames[F.__name__] = frame
            frame.place(x=0, y=0, relwidth=1, relheight=1)

        # Initialize DB and show login
        init_db()
        self._ensure_admin()
        self.show_frame('LoginFrame')

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _ensure_admin(self):
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE username='admin'")
        if not cur.fetchone():
            pwd = bcrypt.hashpw('admin123'.encode(), bcrypt.gensalt())
            cur.execute("INSERT INTO users (username, password_hash) VALUES (%s,%s)", ('admin', pwd.decode()))
            conn.commit()
        conn.close()

    def _setup_styles(self):
        style = ttk.Style()
        # Use 'default' theme — it fully supports custom background/foreground
        # colors on Windows, unlike 'clam'/'vista' which may ignore them.
        try:
            style.theme_use('default')
        except:
            pass

        # Colors
        BG = '#0f1119'
        BG2 = '#181b29'
        BG3 = '#1f2335'
        BG4 = '#282d40'
        ACCENT = '#667eea'
        ACCENT_HOVER = '#5a6fd6'
        TEXT = '#e1e4ed'
        TEXT2 = '#9498a8'
        GREEN = '#52c41a'
        RED = '#ff4d4f'
        ORANGE = '#fa8c16'

        style.configure('.', background=BG, foreground=TEXT, fieldbackground=BG3, borderwidth=0)
        style.configure('TFrame', background=BG)
        style.configure('Card.TFrame', background=BG2, relief='flat')
        style.configure('TLabel', background=BG, foreground=TEXT, font=('Microsoft YaHei UI', 10))
        style.configure('Title.TLabel', font=('Microsoft YaHei UI', 18, 'bold'), foreground=TEXT)
        style.configure('Subtitle.TLabel', font=('Microsoft YaHei UI', 10), foreground=TEXT2)
        style.configure('Heading.TLabel', font=('Microsoft YaHei UI', 12, 'bold'), foreground=TEXT)
        style.configure('Green.TLabel', foreground=GREEN, font=('Microsoft YaHei UI', 10, 'bold'))
        style.configure('Red.TLabel', foreground=RED, font=('Microsoft YaHei UI', 10, 'bold'))
        style.configure('Orange.TLabel', foreground=ORANGE, font=('Microsoft YaHei UI', 10, 'bold'))
        style.configure('Small.TLabel', font=('Microsoft YaHei UI', 9), foreground=TEXT2)
        style.configure('Mono.TLabel', font=('Consolas', 10), foreground=TEXT)

        # Accent button (primary actions)
        style.configure('Accent.TButton',
                        background=ACCENT, foreground='#ffffff',
                        borderwidth=0, focusthickness=0, relief='flat',
                        padding=(20, 10),
                        font=('Microsoft YaHei UI', 10, 'bold'))
        style.map('Accent.TButton',
                  background=[('active', ACCENT_HOVER), ('pressed', ACCENT_HOVER), ('disabled', BG4)],
                  foreground=[('disabled', TEXT2)],
                  relief=[('pressed', 'sunken')])

        # Danger button (stop, logout)
        style.configure('Danger.TButton',
                        background=RED, foreground='#ffffff',
                        borderwidth=0, focusthickness=0, relief='flat',
                        padding=(16, 8),
                        font=('Microsoft YaHei UI', 10))
        style.map('Danger.TButton',
                  background=[('active', '#ff3333'), ('disabled', BG4)],
                  relief=[('pressed', 'sunken')])

        # Ghost button (secondary actions)
        style.configure('Ghost.TButton',
                        background=BG3, foreground=TEXT2,
                        borderwidth=0, focusthickness=0, relief='flat',
                        padding=(14, 6),
                        font=('Microsoft YaHei UI', 9))
        style.map('Ghost.TButton',
                  background=[('active', BG4), ('disabled', BG3)],
                  foreground=[('active', TEXT)],
                  relief=[('pressed', 'sunken')])

        # Tab button style
        style.configure('Tab.TButton',
                        background=BG2, foreground=TEXT2,
                        borderwidth=0, focusthickness=0, relief='flat',
                        padding=(16, 8),
                        font=('Microsoft YaHei UI', 11))
        style.map('Tab.TButton',
                  background=[('active', BG3)],
                  foreground=[('active', TEXT)],
                  relief=[('pressed', 'sunken')])

        style.configure('TEntry', fieldbackground=BG3, foreground=TEXT, insertcolor=TEXT,
                        font=('Microsoft YaHei UI', 10), padding=10)
        style.configure('TCombobox', fieldbackground=BG3, foreground=TEXT, arrowcolor=TEXT,
                        font=('Microsoft YaHei UI', 10))
        style.map('TCombobox',
                  fieldbackground=[('readonly', BG3), ('disabled', BG2)],
                  foreground=[('readonly', TEXT), ('disabled', TEXT2)],
                  selectbackground=[('readonly', ACCENT)],
                  selectforeground=[('readonly', '#ffffff')])

        style.configure('TRadiobutton', background=BG, foreground=TEXT2, font=('Microsoft YaHei UI', 9))
        style.map('TRadiobutton', background=[('active', BG)], foreground=[('selected', ACCENT)])

        style.configure('TCheckbutton', background=BG, foreground=TEXT2, font=('Microsoft YaHei UI', 9))
        style.map('TCheckbutton', background=[('active', BG)])

        style.configure('TLabelframe', background=BG, foreground=TEXT2, borderwidth=1, relief='solid')
        style.configure('TLabelframe.Label', background=BG, foreground=TEXT, font=('Microsoft YaHei UI', 10, 'bold'))

        style.configure('Vertical.TProgressbar', background=ACCENT, troughcolor=BG3, borderwidth=0, thickness=4)

        # Store colors for use in tk widgets
        self.c = {
            'bg': BG, 'bg2': BG2, 'bg3': BG3, 'bg4': BG4,
            'accent': ACCENT, 'text': TEXT, 'text2': TEXT2, 'text3': '#5c6073',
            'green': GREEN, 'red': RED, 'orange': ORANGE,
        }

    def show_frame(self, name):
        frame = self.frames[name]
        frame.tkraise()
        frame.on_show()

    def on_close(self):
        self.delivery_running = False
        if self.delivery:
            self.delivery.running = False
        self.destroy()


# ═══════════════════════════════════════════════════════════════════
#  Login Frame
# ═══════════════════════════════════════════════════════════════════

class LoginFrame(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=app.c['bg'])
        self.app = app

        # Center card
        card = tk.Frame(self, bg=app.c['bg2'], highlightthickness=1, highlightbackground=app.c['bg4'])
        card.place(relx=0.5, rely=0.45, anchor='center', width=380, height=480)

        tk.Frame(card, bg=app.c['accent'], height=3).pack(fill=tk.X)

        inner = tk.Frame(card, bg=app.c['bg2'], padx=36, pady=28)
        inner.pack(fill=tk.BOTH, expand=True)

        # Logo + Title
        logo_frame = tk.Frame(inner, bg=app.c['bg2'])
        logo_frame.pack(pady=(0, 20))

        logo = tk.Canvas(logo_frame, width=44, height=44, bg=app.c['bg2'], highlightthickness=0)
        logo.create_rectangle(0, 0, 44, 44, fill=app.c['accent'], outline='', stipple='')
        logo.create_rectangle(2, 2, 42, 42, fill=app.c['accent'], outline='')
        logo.create_text(22, 22, text='B', fill='#fff', font=('Arial', 22, 'bold'))
        logo.pack()

        tk.Label(inner, text="BOSS直聘智能投递助手", font=('Microsoft YaHei UI', 16, 'bold'),
                 fg=app.c['text'], bg=app.c['bg2']).pack()
        tk.Label(inner, text="专业版 · 商业授权  v3.0 Pro", font=('Microsoft YaHei UI', 9),
                 fg=app.c['text2'], bg=app.c['bg2']).pack(pady=(2, 0))

        # Form
        form = tk.Frame(inner, bg=app.c['bg2'])
        form.pack(fill=tk.X, pady=20)

        # Username
        tk.Label(form, text="用户名", font=('Microsoft YaHei UI', 10), fg=app.c['text2'], bg=app.c['bg2'],
                 anchor='w').pack(fill=tk.X)
        self.username_entry = tk.Entry(form, font=('Microsoft YaHei UI', 11), bg=app.c['bg3'], fg=app.c['text'],
                                       insertbackground=app.c['text'], relief='flat', bd=0, highlightthickness=1,
                                       highlightbackground=app.c['bg4'])
        self.username_entry.pack(fill=tk.X, ipady=7, pady=(4, 10))
        self.username_entry.insert(0, 'admin')
        self._bind_focus(self.username_entry)

        # Password
        tk.Label(form, text="密码", font=('Microsoft YaHei UI', 10), fg=app.c['text2'], bg=app.c['bg2'],
                 anchor='w').pack(fill=tk.X)
        self.password_entry = tk.Entry(form, font=('Microsoft YaHei UI', 11), bg=app.c['bg3'], fg=app.c['text'],
                                       insertbackground=app.c['text'], relief='flat', bd=0, highlightthickness=1,
                                       highlightbackground=app.c['bg4'], show='•')
        self.password_entry.pack(fill=tk.X, ipady=7, pady=(4, 4))
        self.password_entry.insert(0, 'admin123')
        self.password_entry.bind('<Return>', lambda e: self.do_login())
        self._bind_focus(self.password_entry)

        self.error_label = tk.Label(form, text='', font=('Microsoft YaHei UI', 9), fg=app.c['red'], bg=app.c['bg2'])
        self.error_label.pack(fill=tk.X, pady=(2, 0))

        # Buttons
        btn_frame = tk.Frame(inner, bg=app.c['bg2'])
        btn_frame.pack(fill=tk.X, pady=(10, 0))

        self.login_btn = FlatButton(btn_frame, text="登  录", bg=app.c['accent'], fg='#ffffff',
                                     command=self.do_login)
        self.login_btn.pack(fill=tk.X)

        FlatButton(inner, text="还没有账号？立即注册 →", bg=app.c['bg3'], fg=app.c['accent'],
                   hover_bg=app.c['bg4'], font=('Microsoft YaHei UI', 9), padding=(14, 6),
                   command=lambda: app.show_frame('RegisterFrame')).pack(pady=(12, 0))

    def _bind_focus(self, entry):
        def on_focus_in(e):
            e.widget.config(highlightbackground=self.app.c['accent'])

        def on_focus_out(e):
            e.widget.config(highlightbackground=self.app.c['bg4'])

        entry.bind('<FocusIn>', on_focus_in)
        entry.bind('<FocusOut>', on_focus_out)

    def on_show(self):
        self.error_label.config(text='')
        self.login_btn.state(['!disabled'])
        self.login_btn.config(text='登  录')

    def do_login(self):
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()

        if not username or not password:
            self.error_label.config(text='请输入用户名和密码')
            return

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cur.fetchone()
        conn.close()

        if not user:
            self.error_label.config(text='用户名或密码错误')
            return
        if user['is_banned']:
            self.error_label.config(text='账号已被禁用，请联系客服')
            return

        if not bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
            self.error_label.config(text='用户名或密码错误')
            return

        # Update last login
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE users SET last_login=%s WHERE id=%s",
                     (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), user['id']))
        conn.commit()
        conn.close()

        self.app.user_id = user['id']
        self.app.username = user['username']
        log(f"用户登录: {username}")

        # Show mode selection dialog
        self._show_mode_selection()

    def _show_mode_selection(self):
        c = self.app.c
        dialog = tk.Toplevel(self, bg=c['bg2'])
        dialog.title('选择登录模式')
        dialog.geometry('440x340')
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        # Center on parent
        dialog.update_idletasks()
        px = self.winfo_rootx() + (self.winfo_width() - 440) // 2
        py = self.winfo_rooty() + (self.winfo_height() - 340) // 2
        dialog.geometry(f'+{px}+{py}')

        tk.Frame(dialog, bg=c['accent'], height=3).pack(fill=tk.X)

        inner = tk.Frame(dialog, bg=c['bg2'], padx=28, pady=24)
        inner.pack(fill=tk.BOTH, expand=True)

        tk.Label(inner, text='选择登录模式', font=('Microsoft YaHei UI', 14, 'bold'),
                 fg=c['text'], bg=c['bg2']).pack(pady=(0, 16))

        self.mode_var = tk.StringVar(value='self_ai')

        # Mode 1 card
        mode1_frame = tk.Frame(inner, bg=c['bg3'], highlightthickness=2,
                               highlightbackground=c['accent'], cursor='hand2')
        mode1_frame.pack(fill=tk.X, pady=(0, 8))

        mode1_inner = tk.Frame(mode1_frame, bg=c['bg3'], padx=14, pady=10)
        mode1_inner.pack(fill=tk.X)

        rb1 = tk.Radiobutton(mode1_inner, text='自有AI Key模式', variable=self.mode_var,
                             value='self_ai', font=('Microsoft YaHei UI', 11, 'bold'),
                             bg=c['bg3'], fg=c['text'], selectcolor=c['bg3'],
                             activebackground=c['bg3'], activeforeground=c['text'])
        rb1.pack(anchor='w')

        tk.Label(mode1_inner, text='使用自己的DeepSeek API Key，不验证卡密，天数不限制',
                 font=('Microsoft YaHei UI', 9), fg=c['text2'], bg=c['bg3'],
                 justify='left').pack(anchor='w', pady=(2, 0))

        def select_mode1(e=None):
            self.mode_var.set('self_ai')
            mode1_frame.config(highlightbackground=c['accent'])
            mode2_frame.config(highlightbackground=c['bg4'])

        for child in mode1_frame.winfo_children():
            child.bind('<Button-1>', select_mode1)
            for gc in child.winfo_children():
                gc.bind('<Button-1>', select_mode1)
        mode1_frame.bind('<Button-1>', select_mode1)

        # Mode 2 card
        mode2_frame = tk.Frame(inner, bg=c['bg3'], highlightthickness=2,
                               highlightbackground=c['bg4'], cursor='hand2')
        mode2_frame.pack(fill=tk.X, pady=(0, 12))

        mode2_inner = tk.Frame(mode2_frame, bg=c['bg3'], padx=14, pady=10)
        mode2_inner.pack(fill=tk.X)

        rb2 = tk.Radiobutton(mode2_inner, text='内置API模式', variable=self.mode_var,
                             value='builtin', font=('Microsoft YaHei UI', 11, 'bold'),
                             bg=c['bg3'], fg=c['text'], selectcolor=c['bg3'],
                             activebackground=c['bg3'], activeforeground=c['text'])
        rb2.pack(anchor='w')

        tk.Label(mode2_inner, text='使用软件内置AI接口，需卡密验证。试用3天，月卡30天(可叠加)',
                 font=('Microsoft YaHei UI', 9), fg=c['text2'], bg=c['bg3'],
                 justify='left').pack(anchor='w', pady=(2, 0))

        def select_mode2(e=None):
            self.mode_var.set('builtin')
            mode2_frame.config(highlightbackground=c['accent'])
            mode1_frame.config(highlightbackground=c['bg4'])

        for child in mode2_frame.winfo_children():
            child.bind('<Button-1>', select_mode2)
            for gc in child.winfo_children():
                gc.bind('<Button-1>', select_mode2)
        mode2_frame.bind('<Button-1>', select_mode2)

        # Error label
        self.mode_error_label = tk.Label(inner, text='', font=('Microsoft YaHei UI', 9),
                                         fg=c['red'], bg=c['bg2'])
        self.mode_error_label.pack(fill=tk.X)

        # Confirm button
        def confirm():
            login_mode = self.mode_var.get()
            self.app.login_mode = login_mode

            if login_mode == 'self_ai':
                self.app.license_info = {'active': True, 'reason': '自有Key模式', 'expires_at': None, 'card_type': 'self_ai'}
                dialog.destroy()
                self.app.show_frame('MainFrame')
            else:
                self.app.license_info = check_user_license(self.app.user_id)
                dialog.destroy()
                if self.app.license_info['active']:
                    self.app.show_frame('MainFrame')
                else:
                    self.app.show_frame('ActivateFrame')

        FlatButton(inner, text='确认进入', bg=c['accent'], fg='#ffffff',
                   command=confirm).pack(fill=tk.X, pady=(8, 0))


# ═══════════════════════════════════════════════════════════════════
#  Register Frame
# ═══════════════════════════════════════════════════════════════════

class RegisterFrame(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=app.c['bg'])
        self.app = app

        card = tk.Frame(self, bg=app.c['bg2'], highlightthickness=1, highlightbackground=app.c['bg4'])
        card.place(relx=0.5, rely=0.45, anchor='center', width=380, height=430)

        tk.Frame(card, bg=app.c['accent'], height=3).pack(fill=tk.X)

        inner = tk.Frame(card, bg=app.c['bg2'], padx=36, pady=30)
        inner.pack(fill=tk.BOTH, expand=True)

        tk.Label(inner, text="创建账号", font=('Microsoft YaHei UI', 16, 'bold'),
                 fg=app.c['text'], bg=app.c['bg2']).pack(pady=(0, 4))
        tk.Label(inner, text="注册后使用卡密激活软件", font=('Microsoft YaHei UI', 9),
                 fg=app.c['text2'], bg=app.c['bg2']).pack(pady=(0, 16))

        form = tk.Frame(inner, bg=app.c['bg2'])
        form.pack(fill=tk.X)

        # Username
        tk.Label(form, text="用户名 (至少3个字符)", font=('Microsoft YaHei UI', 10), fg=app.c['text2'],
                 bg=app.c['bg2']).pack(anchor='w')
        self.username_entry = tk.Entry(form, font=('Microsoft YaHei UI', 11), bg=app.c['bg3'], fg=app.c['text'],
                                       insertbackground=app.c['text'], relief='flat', bd=0, highlightthickness=1,
                                       highlightbackground=app.c['bg4'])
        self.username_entry.pack(fill=tk.X, ipady=7, pady=(4, 10))
        self._bind_focus(self.username_entry)

        # Password
        tk.Label(form, text="密码 (至少6个字符)", font=('Microsoft YaHei UI', 10), fg=app.c['text2'],
                 bg=app.c['bg2']).pack(anchor='w')
        self.password_entry = tk.Entry(form, font=('Microsoft YaHei UI', 11), bg=app.c['bg3'], fg=app.c['text'],
                                       insertbackground=app.c['text'], relief='flat', bd=0, highlightthickness=1,
                                       highlightbackground=app.c['bg4'], show='•')
        self.password_entry.pack(fill=tk.X, ipady=7, pady=(4, 10))
        self._bind_focus(self.password_entry)

        # Confirm
        tk.Label(form, text="确认密码", font=('Microsoft YaHei UI', 10), fg=app.c['text2'],
                 bg=app.c['bg2']).pack(anchor='w')
        self.confirm_entry = tk.Entry(form, font=('Microsoft YaHei UI', 11), bg=app.c['bg3'], fg=app.c['text'],
                                      insertbackground=app.c['text'], relief='flat', bd=0, highlightthickness=1,
                                      highlightbackground=app.c['bg4'], show='•')
        self.confirm_entry.pack(fill=tk.X, ipady=7, pady=(4, 4))
        self.confirm_entry.bind('<Return>', lambda e: self.do_register())
        self._bind_focus(self.confirm_entry)

        self.msg_label = tk.Label(form, text='', font=('Microsoft YaHei UI', 9), bg=app.c['bg2'])
        self.msg_label.pack(fill=tk.X, pady=(2, 0))

        # Button
        btn_frame = tk.Frame(inner, bg=app.c['bg2'])
        btn_frame.pack(fill=tk.X, pady=(16, 0))

        self.reg_btn = ttk.Button(btn_frame, text="注  册", style='Accent.TButton',
                                  command=self.do_register)
        self.reg_btn.pack(fill=tk.X)

        ttk.Button(inner, text="已有账号？返回登录", style='Ghost.TButton',
                   command=lambda: app.show_frame('LoginFrame')).pack(pady=(12, 0))

    def _bind_focus(self, entry):
        def on_in(e): e.widget.config(highlightbackground=self.app.c['accent'])

        def on_out(e): e.widget.config(highlightbackground=self.app.c['bg4'])

        entry.bind('<FocusIn>', on_in)
        entry.bind('<FocusOut>', on_out)

    def on_show(self):
        self.msg_label.config(text='', fg=self.app.c['text2'])

    def do_register(self):
        username = self.username_entry.get().strip()
        password = self.password_entry.get()
        confirm = self.confirm_entry.get()

        if len(username) < 3:
            self.msg_label.config(text='用户名至少3个字符', fg=self.app.c['red'])
            return
        if len(password) < 6:
            self.msg_label.config(text='密码至少6个字符', fg=self.app.c['red'])
            return
        if password != confirm:
            self.msg_label.config(text='两次密码输入不一致', fg=self.app.c['red'])
            return

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE username=%s", (username,))
        if cur.fetchone():
            conn.close()
            self.msg_label.config(text='用户名已存在', fg=self.app.c['red'])
            return

        pwd_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        cur.execute("INSERT INTO users (username, password_hash) VALUES (%s,%s)", (username, pwd_hash.decode()))
        conn.commit()
        conn.close()

        log(f"新用户注册: {username}")
        self.msg_label.config(text='注册成功！正在跳转登录...', fg=self.app.c['green'])
        self.after(1200, lambda: self.app.show_frame('LoginFrame'))


# ═══════════════════════════════════════════════════════════════════
#  Activate Frame
# ═══════════════════════════════════════════════════════════════════

class ActivateFrame(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=app.c['bg'])
        self.app = app

        card = tk.Frame(self, bg=app.c['bg2'], highlightthickness=1, highlightbackground=app.c['bg4'])
        card.place(relx=0.5, rely=0.45, anchor='center', width=520, height=500)

        tk.Frame(card, bg=app.c['accent'], height=3).pack(fill=tk.X)

        inner = tk.Frame(card, bg=app.c['bg2'], padx=36, pady=28)
        inner.pack(fill=tk.BOTH, expand=True)

        tk.Label(inner, text="激活软件授权", font=('Microsoft YaHei UI', 16, 'bold'),
                 fg=app.c['text'], bg=app.c['bg2']).pack(pady=(0, 4))
        tk.Label(inner, text="请输入您购买的卡密以激活软件功能", font=('Microsoft YaHei UI', 9),
                 fg=app.c['text2'], bg=app.c['bg2']).pack(pady=(0, 16))

        # Plan cards
        plans_frame = tk.Frame(inner, bg=app.c['bg2'])
        plans_frame.pack(fill=tk.X, pady=(0, 16))

        plan_data = [
            ('trial', '试用卡', '3天', '免费体验'),
            ('monthly', '月卡', '30天', '稳定投递'),
            ('quarterly', '季卡', '90天', '超值优惠'),
            ('yearly', '年卡', '365天', '年度旗舰'),
            ('permanent', '永久卡', '终身', '永久权益'),
        ]

        self.plan_widgets = {}
        for i, (ptype, name, days, desc) in enumerate(plan_data):
            pf = tk.Frame(plans_frame, bg=app.c['bg3'], highlightthickness=2,
                          highlightbackground=app.c['bg4'], cursor='hand2')
            pf.grid(row=0, column=i, padx=4, sticky='nsew')
            pf._ptype = ptype
            plans_frame.columnconfigure(i, weight=1)

            tk.Label(pf, text=name, font=('Microsoft YaHei UI', 10, 'bold'), fg=app.c['text'],
                     bg=app.c['bg3']).pack(pady=(10, 2))
            tk.Label(pf, text=days, font=('Microsoft YaHei UI', 16, 'bold'), fg=app.c['accent'],
                     bg=app.c['bg3']).pack()
            tk.Label(pf, text=desc, font=('Microsoft YaHei UI', 8), fg=app.c['text2'],
                     bg=app.c['bg3']).pack(pady=(0, 10))

            pf.bind('<Button-1>', lambda e, p=ptype, w=pf: self._select_plan(p, w))
            for child in pf.winfo_children():
                child.bind('<Button-1>', lambda e, p=ptype, w=pf: self._select_plan(p, w))

            self.plan_widgets[ptype] = pf

        # Card key input
        tk.Label(inner, text="卡密", font=('Microsoft YaHei UI', 10), fg=app.c['text2'],
                 bg=app.c['bg2']).pack(anchor='w')
        self.key_entry = tk.Entry(inner, font=('Consolas', 13), bg=app.c['bg3'], fg=app.c['accent'],
                                  insertbackground=app.c['text'], relief='flat', bd=0, highlightthickness=1,
                                  highlightbackground=app.c['bg4'], justify='center')
        self.key_entry.pack(fill=tk.X, ipady=8, pady=(4, 6))
        self.key_entry.insert(0, 'XXXX-XXXX-XXXX-XXXX')
        self._bind_focus(self.key_entry)
        self.key_entry.bind('<FocusIn>', self._clear_placeholder)
        self.key_entry.bind('<KeyRelease>', self._format_key)

        self.msg_label = tk.Label(inner, text='', font=('Microsoft YaHei UI', 9), bg=app.c['bg2'])
        self.msg_label.pack(fill=tk.X, pady=(2, 0))

        # Buttons
        btn_frame = tk.Frame(inner, bg=app.c['bg2'])
        btn_frame.pack(fill=tk.X, pady=(12, 0))

        self.activate_btn = ttk.Button(btn_frame, text="立即激活", style='Accent.TButton',
                                       command=self.do_activate)
        self.activate_btn.pack(fill=tk.X)

        ttk.Button(inner, text="稍后激活，先进入软件", style='Ghost.TButton',
                   command=lambda: app.show_frame('MainFrame')).pack(pady=(10, 0))

        # 购买入口（占位）
        buy_row = tk.Frame(inner, bg=app.c['bg2'])
        buy_row.pack(fill=tk.X, pady=(12, 0))

        tk.Label(buy_row, text='需要购买卡密？', font=('Microsoft YaHei UI', 9),
                 fg=app.c['text2'], bg=app.c['bg2']).pack(side=tk.LEFT)
        buy_btn = tk.Label(buy_row, text='联系客服购买', font=('Microsoft YaHei UI', 9, 'underline'),
                          fg=app.c['accent'], bg=app.c['bg2'], cursor='hand2')
        buy_btn.pack(side=tk.LEFT, padx=(4, 0))
        buy_btn.bind('<Button-1>', lambda e: messagebox.showinfo('购买卡密',
                                                                  '购买功能即将上线，敬请期待！\n请联系客服获取卡密。'))

    def _bind_focus(self, entry):
        entry.bind('<FocusIn>', lambda e: e.widget.config(highlightbackground=self.app.c['accent']))
        entry.bind('<FocusOut>', lambda e: e.widget.config(highlightbackground=self.app.c['bg4']))

    def _clear_placeholder(self, e):
        if self.key_entry.get() == 'XXXX-XXXX-XXXX-XXXX':
            self.key_entry.delete(0, tk.END)

    def _format_key(self, e):
        val = e.widget.get().upper().replace('-', '').replace(' ', '')
        val = ''.join(c for c in val if c in 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789')
        val = val[:16]
        parts = [val[i:i + 4] for i in range(0, len(val), 4)]
        formatted = '-'.join(parts)
        e.widget.delete(0, tk.END)
        e.widget.insert(0, formatted)

    def _select_plan(self, ptype, widget):
        for w in self.plan_widgets.values():
            w.config(highlightbackground=self.app.c['bg4'], bg=self.app.c['bg3'])
            for c in w.winfo_children():
                c.config(bg=self.app.c['bg3'])
        widget.config(highlightbackground=self.app.c['accent'],
                      bg=self._lighten(self.app.c['accent']))
        for c in widget.winfo_children():
            c.config(bg=self._lighten(self.app.c['accent']))

    def _lighten(self, hex_color, factor=0.12):
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        r = min(255, int(r + (255 - r) * factor))
        g = min(255, int(g + (255 - g) * factor))
        b = min(255, int(b + (255 - b) * factor))
        return f'#{r:02x}{g:02x}{b:02x}'

    def on_show(self):
        self.msg_label.config(text='')

    def do_activate(self):
        card_key = self.key_entry.get().strip().upper()
        if not card_key or card_key == 'XXXX-XXXX-XXXX-XXXX':
            self.msg_label.config(text='请输入有效卡密', fg=self.app.c['red'])
            return

        self.activate_btn.state(['disabled'])
        self.activate_btn.config(text='激活中...')
        self.msg_label.config(text='')

        def _run():
            machine_fp = get_machine_fingerprint()
            success, message = verify_and_activate_card(card_key, self.app.user_id, machine_fp)
            self.app.license_info = check_user_license(self.app.user_id)
            self.after(0, lambda: self._on_result(success, message))

        threading.Thread(target=_run, daemon=True).start()

    def _on_result(self, success, message):
        self.activate_btn.state(['!disabled'])
        self.activate_btn.config(text='立即激活')
        if success:
            self.msg_label.config(text=message, fg=self.app.c['green'])
            log(f"卡密激活成功: {message}")
            self.after(1500, lambda: self.app.show_frame('MainFrame'))
        else:
            self.msg_label.config(text=message, fg=self.app.c['red'])


# ═══════════════════════════════════════════════════════════════════
#  Main Application Frame (原 AutoDeliveryApp 功能)
# ═══════════════════════════════════════════════════════════════════

class MainFrame(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=app.c['bg'])
        self.app = app
        self.setup_ui()

    def setup_ui(self):
        c = self.app.c

        # ── Top status bar ──
        top_bar = tk.Frame(self, bg=c['bg2'], height=36)
        top_bar.pack(fill=tk.X, side=tk.TOP)
        top_bar.pack_propagate(False)

        user_frame = tk.Frame(top_bar, bg=c['bg2'])
        user_frame.pack(side=tk.LEFT, padx=12)

        tk.Label(user_frame, text='👤', font=('Segoe UI', 11), bg=c['bg2'], fg=c['text']).pack(side=tk.LEFT)
        self.user_label = tk.Label(user_frame, text='', font=('Microsoft YaHei UI', 9),
                                   bg=c['bg2'], fg=c['text'])
        self.user_label.pack(side=tk.LEFT, padx=(4, 0))

        right_frame = tk.Frame(top_bar, bg=c['bg2'])
        right_frame.pack(side=tk.RIGHT, padx=12)

        self.license_indicator = tk.Canvas(right_frame, width=8, height=8, bg=c['bg2'], highlightthickness=0)
        self.license_indicator.pack(side=tk.LEFT, padx=(0, 4))
        self.license_label = tk.Label(right_frame, text='', font=('Microsoft YaHei UI', 9),
                                      bg=c['bg2'])
        self.license_label.pack(side=tk.LEFT, padx=(0, 12))

        self.logout_btn = ttk.Button(right_frame, text='退出登录', style='Danger.TButton',
                                     command=self.do_logout)
        self.logout_btn.pack(side=tk.LEFT)

        # ── Main Content Area ──
        main_area = tk.Frame(self, bg=c['bg'])
        main_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

        # ── Tabs ──
        tab_bar = tk.Frame(main_area, bg=c['bg'])
        tab_bar.pack(fill=tk.X, pady=(0, 6))

        self.tab_frames = {}
        self.tab_btns = {}

        # 始终构建所有页签按钮，显示/隐藏由 on_show() 根据 login_mode 决定
        all_tabs = [
            ('delivery', '投递控制'),
            ('resume', '简历分析'),
            ('ai_config', 'AI模型'),
            ('activate', '卡密管理'),
        ]

        for key, label in all_tabs:
            btn = ttk.Button(tab_bar, text=label, style='Tab.TButton',
                             command=lambda k=key: self._switch_tab(k))
            btn.pack(side=tk.LEFT, padx=(0, 4))
            self.tab_btns[key] = btn

        self.tab_active_line = tk.Frame(tab_bar, bg=c['accent'], height=2)
        self.tab_active_line.place(x=0, y=36, width=80)

        # ── Tab Content Area ──
        container = tk.Frame(main_area, bg=c['bg'])
        container.pack(fill=tk.BOTH, expand=True)

        # 始终构建所有页签内容，显示/隐藏由 on_show() 根据 login_mode 决定
        self.tab_frames['delivery'] = self._build_delivery_tab(container)
        self.tab_frames['resume'] = self._build_resume_tab(container)
        self.tab_frames['ai_config'] = self._build_ai_config_tab(container)
        self.tab_frames['activate'] = self._build_activate_tab(container)
        self.tab_frames['manual'] = self._build_manual_tab(container)

        for f in self.tab_frames.values():
            f.place(x=0, y=0, relwidth=1, relheight=1)

        self._switch_tab('delivery')

    # ── Tab Switching ──

    def _switch_tab(self, key):
        for k, btn in self.tab_btns.items():
            if k == key:
                btn.configure(style='Accent.TButton')
            else:
                btn.configure(style='Tab.TButton')
        self.tab_frames[key].tkraise()

    # ── Delivery Tab ─────────────────────────────────────────────

    def _build_delivery_tab(self, parent):
        c = self.app.c
        frame = tk.Frame(parent, bg=c['bg'])

        # 初始化投递计数器
        self.boss_session_count = 0

        # ── 投递统计面板 ──
        stats_panel = tk.Frame(frame, bg=c['bg2'], highlightthickness=1, highlightbackground=c['bg4'])
        stats_panel.pack(fill=tk.X, pady=(0, 6))

        stats_inner = tk.Frame(stats_panel, bg=c['bg2'], padx=16, pady=10)
        stats_inner.pack(fill=tk.X)

        # 今日统计标题行
        stats_title_row = tk.Frame(stats_inner, bg=c['bg2'])
        stats_title_row.pack(fill=tk.X)

        tk.Label(stats_title_row, text='📊 投递统计', font=('Microsoft YaHei UI', 11, 'bold'),
                 fg=c['text'], bg=c['bg2']).pack(side=tk.LEFT)

        # 今日总投递数
        self.today_total_label = tk.Label(stats_title_row, text='今日总投递: 0',
                                          font=('Microsoft YaHei UI', 12, 'bold'),
                                          fg=c['accent'], bg=c['bg2'])
        self.today_total_label.pack(side=tk.LEFT, padx=20)

        # 本次投递状态行
        stats_detail_row = tk.Frame(stats_inner, bg=c['bg2'])
        stats_detail_row.pack(fill=tk.X, pady=(6, 0))

        tk.Label(stats_detail_row, text='本次投递', font=('Microsoft YaHei UI', 9),
                 fg=c['text2'], bg=c['bg2']).pack(side=tk.LEFT)

        self.boss_count_label = tk.Label(stats_detail_row, text='BOSS: 0', font=('Microsoft YaHei UI', 10, 'bold'),
                                          fg=c['accent'], bg=c['bg2'])
        self.boss_count_label.pack(side=tk.LEFT, padx=(12, 0))

        # 状态指示
        self.status_text = tk.Label(stats_detail_row, text='就绪', font=('Microsoft YaHei UI', 9),
                                     fg=c['text2'], bg=c['bg2'])
        self.status_text.pack(side=tk.RIGHT)

        self.count_label = self.boss_count_label  # 向后兼容

        # ── 主内容区：左配置 + 右日志 ──
        main_content = tk.Frame(frame, bg=c['bg'])
        main_content.pack(fill=tk.BOTH, expand=True)

        left = tk.Frame(main_content, bg=c['bg'])
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))

        right = tk.Frame(main_content, bg=c['bg'])
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(4, 0))

        # ── Left: Platform Login Card ──
        login_card = tk.Frame(left, bg=c['bg2'], highlightthickness=1, highlightbackground=c['bg4'])
        login_card.pack(fill=tk.X, pady=(0, 6))

        login_inner = tk.Frame(login_card, bg=c['bg2'], padx=14, pady=10)
        login_inner.pack(fill=tk.X)

        # 标题行
        login_header = tk.Frame(login_inner, bg=c['bg2'])
        login_header.pack(fill=tk.X, pady=(0, 6))

        tk.Label(login_header, text='🔗 平台连接', font=('Microsoft YaHei UI', 11, 'bold'),
                 fg=c['text'], bg=c['bg2']).pack(side=tk.LEFT)

        # 平台标识
        tk.Label(login_header, text='BOSS直聘', font=('Microsoft YaHei UI', 9),
                 fg=c['accent'], bg=c['bg2']).pack(side=tk.LEFT, padx=(16, 0))

        # BOSS 登录行
        boss_row = tk.Frame(login_inner, bg=c['bg2'])
        boss_row.pack(fill=tk.X, pady=(2, 3))

        boss_tag = tk.Frame(boss_row, bg=c['accent'], padx=0, pady=0, width=4, height=20)
        boss_tag.pack(side=tk.LEFT, padx=(0, 8))
        boss_tag.pack_propagate(False)

        tk.Label(boss_row, text='BOSS直聘', font=('Microsoft YaHei UI', 9, 'bold'),
                 fg=c['accent'], bg=c['bg2'], width=8, anchor='w').pack(side=tk.LEFT)

        self.boss_login_btn = ttk.Button(boss_row, text='打开浏览器登录', style='Accent.TButton',
                                          command=self.get_boss_qr_code)
        self.boss_login_btn.pack(side=tk.LEFT)

        ttk.Button(boss_row, text='验证', style='Ghost.TButton',
                   command=self._check_saved_login).pack(side=tk.LEFT, padx=(4, 0))

        ttk.Button(boss_row, text='清空', style='Ghost.TButton',
                   command=lambda: self._clear_browser_cache('boss')).pack(side=tk.LEFT, padx=(4, 0))

        self.boss_login_status_label = tk.Label(boss_row, text='未登录', font=('Microsoft YaHei UI', 9, 'bold'),
                                                 fg=c['red'], bg=c['bg2'])
        self.boss_login_status_label.pack(side=tk.LEFT, padx=12)

        # 保留旧引用兼容
        self.login_btn = self.boss_login_btn
        self.login_status_label = self.boss_login_status_label

        # ── Left: Config Card ──
        cfg_card = tk.Frame(left, bg=c['bg2'], highlightthickness=1, highlightbackground=c['bg4'])
        cfg_card.pack(fill=tk.BOTH, expand=True)

        # 彩色顶条
        tk.Frame(cfg_card, bg=c['accent'], height=2).pack(fill=tk.X)

        cfg_inner = tk.Frame(cfg_card, bg=c['bg2'], padx=14, pady=12)
        cfg_inner.pack(fill=tk.BOTH, expand=True)

        # 标题行带分隔线
        cfg_title_row = tk.Frame(cfg_inner, bg=c['bg2'])
        cfg_title_row.pack(fill=tk.X, pady=(0, 8))

        tk.Label(cfg_title_row, text='⚙ 投递配置', font=('Microsoft YaHei UI', 11, 'bold'),
                 fg=c['text'], bg=c['bg2']).pack(side=tk.LEFT)

        tk.Frame(cfg_inner, bg=c['bg4'], height=1).pack(fill=tk.X, pady=(0, 8))

        # Scrolled config content
        cfg_scroll = tk.Frame(cfg_inner, bg=c['bg2'])
        cfg_scroll.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        # Mode
        row1 = tk.Frame(cfg_scroll, bg=c['bg2'])
        row1.pack(fill=tk.X, pady=2)

        tk.Label(row1, text='投递模式', font=('Microsoft YaHei UI', 9), fg=c['text2'],
                 bg=c['bg2'], width=10, anchor='w').pack(side=tk.LEFT)
        self.mode_var = tk.StringVar(value='auto')
        tk.Radiobutton(row1, text='自动投递', variable=self.mode_var, value='auto',
                       font=('Microsoft YaHei UI', 9), bg=c['bg2'], fg=c['text2'],
                       selectcolor=c['bg3'], activebackground=c['bg2'],
                       activeforeground=c['text']).pack(side=tk.LEFT, padx=(0, 10))
        tk.Radiobutton(row1, text='人工审核', variable=self.mode_var, value='manual',
                       font=('Microsoft YaHei UI', 9), bg=c['bg2'], fg=c['text2'],
                       selectcolor=c['bg3'], activebackground=c['bg2'],
                       activeforeground=c['text']).pack(side=tk.LEFT)

        # Threshold
        row2 = tk.Frame(cfg_scroll, bg=c['bg2'])
        row2.pack(fill=tk.X, pady=2)

        tk.Label(row2, text='匹配阈值(%)', font=('Microsoft YaHei UI', 9), fg=c['text2'],
                 bg=c['bg2'], width=10, anchor='w').pack(side=tk.LEFT)
        self.threshold_var = tk.StringVar(value='60')
        tk.Entry(row2, textvariable=self.threshold_var, font=('Microsoft YaHei UI', 9),
                 bg=c['bg3'], fg=c['text'], insertbackground=c['text'], relief='flat',
                 bd=0, width=6, highlightthickness=1, highlightbackground=c['bg4']).pack(side=tk.LEFT)

        # Stop mode
        row3 = tk.Frame(cfg_scroll, bg=c['bg2'])
        row3.pack(fill=tk.X, pady=2)

        tk.Label(row3, text='停止模式', font=('Microsoft YaHei UI', 9), fg=c['text2'],
                 bg=c['bg2'], width=10, anchor='w').pack(side=tk.LEFT)
        self.stop_mode_var = tk.StringVar(value='count')
        tk.Radiobutton(row3, text='按数量', variable=self.stop_mode_var, value='count',
                       command=self._on_stop_mode,
                       font=('Microsoft YaHei UI', 9), bg=c['bg2'], fg=c['text2'],
                       selectcolor=c['bg3'], activebackground=c['bg2']).pack(side=tk.LEFT, padx=(0, 10))
        tk.Radiobutton(row3, text='按时间', variable=self.stop_mode_var, value='time',
                       command=self._on_stop_mode,
                       font=('Microsoft YaHei UI', 9), bg=c['bg2'], fg=c['text2'],
                       selectcolor=c['bg3'], activebackground=c['bg2']).pack(side=tk.LEFT)

        # Count / Time
        row4 = tk.Frame(cfg_scroll, bg=c['bg2'])
        row4.pack(fill=tk.X, pady=2)

        tk.Label(row4, text='投递数量', font=('Microsoft YaHei UI', 9), fg=c['text2'],
                 bg=c['bg2'], width=10, anchor='w').pack(side=tk.LEFT)
        self.max_count_var = tk.StringVar(value=str(MAX_DELIVERY_COUNT))
        self.max_count_entry = tk.Entry(row4, textvariable=self.max_count_var, font=('Microsoft YaHei UI', 9),
                                        bg=c['bg3'], fg=c['text'], insertbackground=c['text'], relief='flat',
                                        bd=0, width=6, highlightthickness=1, highlightbackground=c['bg4'])
        self.max_count_entry.pack(side=tk.LEFT)

        tk.Label(row4, text='  运行时间(分)', font=('Microsoft YaHei UI', 9), fg=c['text2'],
                 bg=c['bg2']).pack(side=tk.LEFT, padx=(12, 0))
        self.max_time_var = tk.StringVar(value='60')
        self.max_time_entry = tk.Entry(row4, textvariable=self.max_time_var, font=('Microsoft YaHei UI', 9),
                                       bg=c['bg3'], fg=c['text'], insertbackground=c['text'], relief='flat',
                                       bd=0, width=6, highlightthickness=1, highlightbackground=c['bg4'],
                                       state='disabled')
        self.max_time_entry.pack(side=tk.LEFT)

        # 每日上限
        row4b = tk.Frame(cfg_scroll, bg=c['bg2'])
        row4b.pack(fill=tk.X, pady=2)

        tk.Label(row4b, text='每日上限', font=('Microsoft YaHei UI', 9), fg=c['text2'],
                 bg=c['bg2'], width=10, anchor='w').pack(side=tk.LEFT)
        self.max_daily_var = tk.StringVar(value=str(MAX_DAILY_DELIVERY))
        self.max_daily_entry = tk.Entry(row4b, textvariable=self.max_daily_var, font=('Microsoft YaHei UI', 9),
                                        bg=c['bg3'], fg=c['text'], insertbackground=c['text'], relief='flat',
                                        bd=0, width=6, highlightthickness=1, highlightbackground=c['bg4'])
        self.max_daily_entry.pack(side=tk.LEFT)
        tk.Label(row4b, text=' (0=不限制)', font=('Microsoft YaHei UI', 8), fg=c['text3'],
                 bg=c['bg2']).pack(side=tk.LEFT, padx=(4, 0))

        # City
        row5 = tk.Frame(cfg_scroll, bg=c['bg2'])
        row5.pack(fill=tk.X, pady=2)

        tk.Label(row5, text='目标城市', font=('Microsoft YaHei UI', 9), fg=c['text2'],
                 bg=c['bg2'], width=10, anchor='w').pack(side=tk.LEFT)
        city_names = sorted(CITY_MAP.values())
        self.city_var = tk.StringVar(value='北京')
        self.city_combo = ttk.Combobox(row5, textvariable=self.city_var, values=city_names,
                                       state='readonly', width=12, font=('Microsoft YaHei UI', 9))
        self.city_combo.pack(side=tk.LEFT)

        # Keywords
        row6 = tk.Frame(cfg_scroll, bg=c['bg2'])
        row6.pack(fill=tk.X, pady=2)

        tk.Label(row6, text='标题关键词', font=('Microsoft YaHei UI', 9), fg=c['text2'],
                 bg=c['bg2'], width=10, anchor='w').pack(side=tk.LEFT)
        self.title_keywords_var = tk.StringVar(value='测试,自动化测试,Python,开发,工程师')
        self.title_keywords_entry = tk.Entry(row6, textvariable=self.title_keywords_var, font=('Microsoft YaHei UI', 9),
                 bg=c['bg3'], fg=c['text'], insertbackground=c['text'], relief='flat',
                 bd=0, highlightthickness=1, highlightbackground=c['bg4'])
        self.title_keywords_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 常用技能标签
        skill_tags_row = tk.Frame(cfg_scroll, bg=c['bg2'])
        skill_tags_row.pack(fill=tk.X, pady=(1, 4))

        tk.Label(skill_tags_row, text='', font=('Microsoft YaHei UI', 9),
                 bg=c['bg2'], width=10).pack(side=tk.LEFT)  # 占位对齐

        skill_presets = [
            ('测试', ['测试', '软件测试', '自动化测试', '功能测试', '性能测试']),
            ('开发', ['Python', 'Java', '前端', '后端', '全栈', 'Go']),
            ('运维', ['运维', 'DevOps', 'Linux', 'Docker', 'K8s']),
            ('数据', ['数据分析', '大数据', 'SQL', 'ETL', '数据仓库']),
            ('产品', ['产品经理', '需求分析', '项目管理', '运营']),
        ]

        def add_skill_tags(keywords):
            current = self.title_keywords_var.get().strip()
            existing = set(k.strip() for k in current.split(',') if k.strip())
            new = set(keywords)
            merged = existing | new
            self.title_keywords_var.set(', '.join(merged))

        tags_frame = tk.Frame(skill_tags_row, bg=c['bg2'])
        tags_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        for name, keywords in skill_presets:
            btn = tk.Label(tags_frame, text=name, font=('Microsoft YaHei UI', 8),
                          fg=c['accent'], bg=c['bg3'], cursor='hand2',
                          padx=8, pady=1)
            btn.pack(side=tk.LEFT, padx=(0, 4))
            btn.bind('<Button-1>', lambda e, kw=keywords: add_skill_tags(kw))
            btn.bind('<Enter>', lambda e, b=btn: b.config(bg=c['bg4']))
            btn.bind('<Leave>', lambda e, b=btn: b.config(bg=c['bg3']))

        # 提示文字
        tk.Label(skill_tags_row, text='点击标签快速添加', font=('Microsoft YaHei UI', 7),
                 fg=c['text3'], bg=c['bg2']).pack(side=tk.LEFT, padx=(4, 0))

        # Reprocess checkbox
        row7 = tk.Frame(cfg_scroll, bg=c['bg2'])
        row7.pack(fill=tk.X, pady=4)
        self.reprocess_var = tk.BooleanVar(value=False)
        tk.Checkbutton(row7, text='重新处理已跳过岗位', variable=self.reprocess_var,
                       font=('Microsoft YaHei UI', 9), bg=c['bg2'], fg=c['text2'],
                       selectcolor=c['bg3'], activebackground=c['bg2']).pack(side=tk.LEFT)

        # Action buttons
        btn_row = tk.Frame(cfg_scroll, bg=c['bg2'])
        btn_row.pack(fill=tk.X, pady=(10, 0))

        self.start_btn = ttk.Button(btn_row, text='开始搜索投递', style='Accent.TButton',
                                    command=self.start_search_thread)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.start_btn.state(['disabled'])

        self.stop_btn = ttk.Button(btn_row, text='停止', style='Danger.TButton',
                                   command=self.stop_delivery)
        self.stop_btn.pack(side=tk.LEFT)
        self.stop_btn.state(['disabled'])

        # ── Right: Log Panels ──
        # BOSS 日志卡片
        boss_log_card = tk.Frame(right, bg=c['bg2'], highlightthickness=1, highlightbackground=c['bg4'])
        boss_log_card.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        # 彩色顶条
        tk.Frame(boss_log_card, bg=c['accent'], height=2).pack(fill=tk.X)

        boss_log_inner = tk.Frame(boss_log_card, bg=c['bg2'], padx=14, pady=10)
        boss_log_inner.pack(fill=tk.BOTH, expand=True)

        boss_log_header = tk.Frame(boss_log_inner, bg=c['bg2'])
        boss_log_header.pack(fill=tk.X, pady=(0, 4))

        tk.Label(boss_log_header, text='● BOSS直聘 运行日志', font=('Microsoft YaHei UI', 10, 'bold'),
                 fg=c['accent'], bg=c['bg2']).pack(side=tk.LEFT)
        ttk.Button(boss_log_header, text='清空', style='Ghost.TButton',
                   command=lambda: self._clear_platform_log('boss')).pack(side=tk.RIGHT)

        self.boss_log_text = scrolledtext.ScrolledText(boss_log_inner, font=('Consolas', 10), bg='#0a0c14',
                                                        fg=c['text2'], insertbackground=c['text'],
                                                        relief='flat', bd=0, highlightthickness=1,
                                                        highlightbackground=c['bg4'])
        self.boss_log_text.pack(fill=tk.BOTH, expand=True)

        # 通用日志（保留兼容）
        self.log_text = self.boss_log_text

        # Tag colors
        for log_widget in [self.boss_log_text]:
            log_widget.tag_config('success', foreground=c['green'])
            log_widget.tag_config('error', foreground=c['red'])
            log_widget.tag_config('info', foreground='#1890ff')
            log_widget.tag_config('warn', foreground=c['orange'])
            log_widget.tag_config('dim', foreground=c['text2'])

        return frame

    # ── Resume Tab ──────────────────────────────────────────────

    def _build_resume_tab(self, parent):
        c = self.app.c
        frame = tk.Frame(parent, bg=c['bg'])

        left = tk.Frame(frame, bg=c['bg'])
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))

        right = tk.Frame(frame, bg=c['bg'])
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(4, 0))

        # Upload card
        upload_card = tk.Frame(left, bg=c['bg2'], highlightthickness=1, highlightbackground=c['bg4'])
        upload_card.pack(fill=tk.BOTH, expand=True)

        upload_inner = tk.Frame(upload_card, bg=c['bg2'], padx=14, pady=12)
        upload_inner.pack(fill=tk.BOTH, expand=True)

        tk.Label(upload_inner, text='简历上传', font=('Microsoft YaHei UI', 11, 'bold'),
                 fg=c['text'], bg=c['bg2']).pack(anchor='w')

        self.resume_path_label = tk.Label(upload_inner, text='未选择简历文件', font=('Microsoft YaHei UI', 9),
                                          fg=c['text2'], bg=c['bg2'])
        self.resume_path_label.pack(anchor='w', pady=(8, 4))

        btn_row = tk.Frame(upload_inner, bg=c['bg2'])
        btn_row.pack(fill=tk.X)

        ttk.Button(btn_row, text='选择简历文件', style='Accent.TButton',
                   command=self._select_resume).pack(side=tk.LEFT)

        self.analyze_btn = ttk.Button(btn_row, text='分析简历', style='Ghost.TButton',
                                      command=self._start_analyze)
        self.analyze_btn.pack(side=tk.LEFT, padx=8)
        self.analyze_btn.state(['disabled'])

        self.analyze_status_label = tk.Label(upload_inner, text='', font=('Microsoft YaHei UI', 9),
                                             fg=c['text2'], bg=c['bg2'])
        self.analyze_status_label.pack(anchor='w', pady=(8, 0))

        # Analysis result
        result_card = tk.Frame(right, bg=c['bg2'], highlightthickness=1, highlightbackground=c['bg4'])
        result_card.pack(fill=tk.BOTH, expand=True)

        result_inner = tk.Frame(result_card, bg=c['bg2'], padx=14, pady=12)
        result_inner.pack(fill=tk.BOTH, expand=True)

        tk.Label(result_inner, text='分析结果', font=('Microsoft YaHei UI', 11, 'bold'),
                 fg=c['text'], bg=c['bg2']).pack(anchor='w')

        self.analysis_text = scrolledtext.ScrolledText(result_inner, font=('Microsoft YaHei UI', 10),
                                                       bg=c['bg3'], fg=c['text2'],
                                                       insertbackground=c['text'], relief='flat', bd=0,
                                                       highlightthickness=1, highlightbackground=c['bg4'])
        self.analysis_text.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        return frame

    # ── Manual Tab ──────────────────────────────────────────────

    def _build_manual_tab(self, parent):
        c = self.app.c
        frame = tk.Frame(parent, bg=c['bg'])

        left = tk.Frame(frame, bg=c['bg'])
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))

        right = tk.Frame(frame, bg=c['bg'])
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(4, 0))

        # Job info
        job_card = tk.Frame(left, bg=c['bg2'], highlightthickness=1, highlightbackground=c['bg4'])
        job_card.pack(fill=tk.BOTH, expand=True)

        job_inner = tk.Frame(job_card, bg=c['bg2'], padx=14, pady=12)
        job_inner.pack(fill=tk.BOTH, expand=True)

        tk.Label(job_inner, text='岗位信息', font=('Microsoft YaHei UI', 11, 'bold'),
                 fg=c['text'], bg=c['bg2']).pack(anchor='w')

        fields = [
            ('岗位名称:', 'job_title'),
            ('公司名称:', 'job_company'),
            ('薪资范围:', 'job_salary'),
            ('发布时间:', 'job_time'),
            ('匹配度:', 'job_match'),
        ]
        for label, key in fields:
            row = tk.Frame(job_inner, bg=c['bg2'])
            row.pack(fill=tk.X, pady=1)
            tk.Label(row, text=label, font=('Microsoft YaHei UI', 9), fg=c['text2'],
                     bg=c['bg2'], width=8, anchor='w').pack(side=tk.LEFT)
            lbl = tk.Label(row, text='-', font=('Microsoft YaHei UI', 9), fg=c['text'],
                           bg=c['bg2'], anchor='w')
            lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
            setattr(self, f'{key}_label', lbl)

        tk.Label(job_inner, text='岗位详情:', font=('Microsoft YaHei UI', 9), fg=c['text2'],
                 bg=c['bg2'], anchor='w').pack(fill=tk.X, pady=(8, 1))

        self.job_detail_text = scrolledtext.ScrolledText(job_inner, font=('Microsoft YaHei UI', 9),
                                                         bg=c['bg3'], fg=c['text2'],
                                                         insertbackground=c['text'], relief='flat', bd=0,
                                                         highlightthickness=1, highlightbackground=c['bg4'],
                                                         height=8)
        self.job_detail_text.pack(fill=tk.BOTH, expand=True)

        self.job_progress_label = tk.Label(job_inner, text='', font=('Microsoft YaHei UI', 9),
                                           fg=c['text2'], bg=c['bg2'])
        self.job_progress_label.pack(anchor='e', pady=(4, 0))

        # Greeting + actions
        action_card = tk.Frame(right, bg=c['bg2'], highlightthickness=1, highlightbackground=c['bg4'])
        action_card.pack(fill=tk.BOTH, expand=True)

        action_inner = tk.Frame(action_card, bg=c['bg2'], padx=14, pady=12)
        action_inner.pack(fill=tk.BOTH, expand=True)

        tk.Label(action_inner, text='打招呼语 & 操作', font=('Microsoft YaHei UI', 11, 'bold'),
                 fg=c['text'], bg=c['bg2']).pack(anchor='w')

        self.greeting_text = scrolledtext.ScrolledText(action_inner, font=('Microsoft YaHei UI', 10),
                                                       bg=c['bg3'], fg=c['text'],
                                                       insertbackground=c['text'], relief='flat', bd=0,
                                                       highlightthickness=1, highlightbackground=c['bg4'],
                                                       height=5)
        self.greeting_text.pack(fill=tk.BOTH, expand=True, pady=(8, 8))

        btn_row = tk.Frame(action_inner, bg=c['bg2'])
        btn_row.pack(fill=tk.X)

        self.deliver_btn = ttk.Button(btn_row, text='投递此岗位', style='Accent.TButton',
                                       command=self._manual_deliver)
        self.deliver_btn.state(['disabled'])
        self.deliver_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.skip_btn = ttk.Button(btn_row, text='跳过，下一个', style='Ghost.TButton',
                                   command=self._skip_job)
        self.skip_btn.state(['disabled'])
        self.skip_btn.pack(side=tk.LEFT)

        return frame

    # ── Activate Tab (in main frame) ────────────────────────────

    def _build_activate_tab(self, parent):
        c = self.app.c
        frame = tk.Frame(parent, bg=c['bg'])

        card = tk.Frame(frame, bg=c['bg2'], highlightthickness=1, highlightbackground=c['bg4'])
        card.pack(fill=tk.BOTH, expand=True, padx=40, pady=20)

        inner = tk.Frame(card, bg=c['bg2'], padx=24, pady=20)
        inner.pack(fill=tk.BOTH, expand=True)

        tk.Label(inner, text='卡密管理', font=('Microsoft YaHei UI', 14, 'bold'),
                 fg=c['text'], bg=c['bg2']).pack(anchor='w', pady=(0, 12))

        # Current license info
        self.license_info_frame = tk.Frame(inner, bg=c['bg3'], padx=14, pady=12,
                                           highlightthickness=1, highlightbackground=c['bg4'])
        self.license_info_frame.pack(fill=tk.X)

        self.license_detail_label = tk.Label(self.license_info_frame, text='', font=('Microsoft YaHei UI', 10),
                                             fg=c['text'], bg=c['bg3'], justify='left')
        self.license_detail_label.pack(anchor='w')

        # New activation
        sep = tk.Frame(inner, bg=c['bg4'], height=1)
        sep.pack(fill=tk.X, pady=16)

        tk.Label(inner, text='激活新卡密', font=('Microsoft YaHei UI', 11, 'bold'),
                 fg=c['text'], bg=c['bg2']).pack(anchor='w', pady=(0, 8))

        key_row = tk.Frame(inner, bg=c['bg2'])
        key_row.pack(fill=tk.X)

        self.activate_key_entry = tk.Entry(key_row, font=('Consolas', 13), bg=c['bg3'], fg=c['accent'],
                                           insertbackground=c['text'], relief='flat', bd=0,
                                           highlightthickness=1, highlightbackground=c['bg4'],
                                           justify='center', width=24)
        self.activate_key_entry.pack(side=tk.LEFT, ipady=7, padx=(0, 10))
        self.activate_key_entry.insert(0, 'XXXX-XXXX-XXXX-XXXX')
        self.activate_key_entry.bind('<FocusIn>', self._clear_activate_placeholder)
        self.activate_key_entry.bind('<KeyRelease>', self._format_activate_key2)

        ttk.Button(key_row, text='激活', style='Accent.TButton',
                   command=self._activate_in_main).pack(side=tk.LEFT)

        self.activate_msg_label = tk.Label(inner, text='', font=('Microsoft YaHei UI', 9),
                                           bg=c['bg2'])
        self.activate_msg_label.pack(anchor='w', pady=(8, 0))

        # 购买入口
        buy_row = tk.Frame(inner, bg=c['bg2'])
        buy_row.pack(fill=tk.X, pady=(12, 0))

        tk.Label(buy_row, text='需要购买卡密？', font=('Microsoft YaHei UI', 9),
                 fg=c['text2'], bg=c['bg2']).pack(side=tk.LEFT)
        buy_btn = tk.Label(buy_row, text='联系客服购买', font=('Microsoft YaHei UI', 9, 'underline'),
                          fg=c['accent'], bg=c['bg2'], cursor='hand2')
        buy_btn.pack(side=tk.LEFT, padx=(4, 0))
        buy_btn.bind('<Button-1>', lambda e: messagebox.showinfo('购买卡密',
                                                                  '购买功能即将上线，敬请期待！\n请联系客服获取卡密。'))

        return frame

    # ── AI Config Tab (Mode 1) ──────────────────────────────────

    def _build_ai_config_tab(self, parent):
        c = self.app.c
        frame = tk.Frame(parent, bg=c['bg'])

        card = tk.Frame(frame, bg=c['bg2'], highlightthickness=1, highlightbackground=c['bg4'])
        card.pack(fill=tk.BOTH, expand=True, padx=40, pady=20)

        inner = tk.Frame(card, bg=c['bg2'], padx=24, pady=20)
        inner.pack(fill=tk.BOTH, expand=True)

        tk.Label(inner, text='AI模型配置', font=('Microsoft YaHei UI', 14, 'bold'),
                 fg=c['text'], bg=c['bg2']).pack(anchor='w', pady=(0, 4))
        tk.Label(inner, text='配置您自己的DeepSeek API Key，AI调用将使用您的账号',
                 font=('Microsoft YaHei UI', 9), fg=c['text2'], bg=c['bg2']).pack(anchor='w', pady=(0, 16))

        # API Key
        key_section = tk.Frame(inner, bg=c['bg2'])
        key_section.pack(fill=tk.X, pady=(0, 12))

        tk.Label(key_section, text='API Key', font=('Microsoft YaHei UI', 10, 'bold'),
                 fg=c['text'], bg=c['bg2']).pack(anchor='w')
        tk.Label(key_section, text='从 platform.deepseek.com 获取', font=('Microsoft YaHei UI', 8),
                 fg=c['text2'], bg=c['bg2']).pack(anchor='w')

        self.ai_api_key_var = tk.StringVar(value=self.app.user_ai_config.get('api_key', ''))
        self.ai_api_key_entry = tk.Entry(key_section, textvariable=self.ai_api_key_var,
                                         font=('Consolas', 11), bg=c['bg3'], fg=c['text'],
                                         insertbackground=c['text'], relief='flat', bd=0,
                                         highlightthickness=1, highlightbackground=c['bg4'],
                                         show='•')
        self.ai_api_key_entry.pack(fill=tk.X, ipady=7, pady=(6, 0))

        # Show/hide key toggle
        self._show_key = False
        def toggle_key_visible():
            self._show_key = not self._show_key
            self.ai_api_key_entry.config(show='' if self._show_key else '•')
            key_toggle_btn.config(text='隐藏' if self._show_key else '显示')

        key_toggle_btn = ttk.Button(key_section, text='显示', style='Ghost.TButton',
                                    command=toggle_key_visible)
        key_toggle_btn.pack(anchor='w', pady=(4, 0))

        # Base URL
        url_section = tk.Frame(inner, bg=c['bg2'])
        url_section.pack(fill=tk.X, pady=(0, 12))

        tk.Label(url_section, text='API Base URL', font=('Microsoft YaHei UI', 10, 'bold'),
                 fg=c['text'], bg=c['bg2']).pack(anchor='w')
        self.ai_base_url_var = tk.StringVar(value=self.app.user_ai_config.get('base_url', 'https://api.deepseek.com'))
        tk.Entry(url_section, textvariable=self.ai_base_url_var, font=('Consolas', 10),
                 bg=c['bg3'], fg=c['text'], insertbackground=c['text'], relief='flat', bd=0,
                 highlightthickness=1, highlightbackground=c['bg4']).pack(fill=tk.X, ipady=7, pady=(6, 0))

        # Model
        model_section = tk.Frame(inner, bg=c['bg2'])
        model_section.pack(fill=tk.X, pady=(0, 16))

        tk.Label(model_section, text='模型名称', font=('Microsoft YaHei UI', 10, 'bold'),
                 fg=c['text'], bg=c['bg2']).pack(anchor='w')
        self.ai_model_var = tk.StringVar(value=self.app.user_ai_config.get('model', 'deepseek-v4-flash'))
        model_cb = ttk.Combobox(model_section, textvariable=self.ai_model_var,
                                values=['deepseek-v4-flash', 'deepseek-chat', 'deepseek-reasoner'],
                                font=('Consolas', 10), state='readonly')
        model_cb.pack(fill=tk.X, ipady=3, pady=(6, 0))

        # Save + Test buttons
        btn_row = tk.Frame(inner, bg=c['bg2'])
        btn_row.pack(fill=tk.X, pady=(0, 10))

        def save_config():
            api_key = self.ai_api_key_var.get().strip()
            if not api_key:
                self.ai_status_label.config(text='请输入API Key', fg=c['red'])
                return
            self.app.user_ai_config = {
                'api_key': api_key,
                'base_url': self.ai_base_url_var.get().strip(),
                'model': self.ai_model_var.get().strip()
            }
            self.ai_status_label.config(text='配置已保存', fg=c['green'])

        FlatButton(btn_row, text='保存配置', bg=c['accent'], fg='#ffffff',
                   command=save_config).pack(side=tk.LEFT, padx=(0, 8))

        def test_api():
            api_key = self.ai_api_key_var.get().strip()
            if not api_key:
                self.ai_status_label.config(text='请先输入API Key', fg=c['red'])
                return
            self.ai_status_label.config(text='测试中...', fg=c['orange'])
            base_url = self.ai_base_url_var.get().strip()
            model = self.ai_model_var.get().strip()
            threading.Thread(target=lambda: self._test_ai_api(api_key, base_url, model), daemon=True).start()

        FlatButton(btn_row, text='测试连接', bg=c['bg3'], fg=c['text'],
                   hover_bg=c['bg4'], command=test_api).pack(side=tk.LEFT)

        self.ai_status_label = tk.Label(inner, text='', font=('Microsoft YaHei UI', 9),
                                        bg=c['bg2'])
        self.ai_status_label.pack(anchor='w')

        # Usage tips
        tips_frame = tk.Frame(inner, bg=c['bg3'], padx=14, pady=12,
                              highlightthickness=1, highlightbackground=c['bg4'])
        tips_frame.pack(fill=tk.X, pady=(16, 0))

        tk.Label(tips_frame, text='💡 使用说明', font=('Microsoft YaHei UI', 10, 'bold'),
                 fg=c['text'], bg=c['bg3']).pack(anchor='w')

        tips = [
            '1. 前往 platform.deepseek.com 注册并获取API Key',
            '2. 充值后即可使用（费用极低，按量计费）',
            '3. 填入API Key后点击"测试连接"验证是否可用',
            '4. 测试通过后点击"保存配置"即可使用自有Key投递',
            '5. 使用自有Key不限制天数和投递次数',
        ]
        for tip in tips:
            tk.Label(tips_frame, text=tip, font=('Microsoft YaHei UI', 9),
                     fg=c['text2'], bg=c['bg3'], justify='left').pack(anchor='w', pady=(1, 0))

        return frame

    def _test_ai_api(self, api_key, base_url, model):
        try:
            import openai
            client = openai.OpenAI(api_key=api_key, base_url=base_url)
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "回复OK"}],
                max_tokens=5
            )
            result = response.choices[0].message.content
            self.after(0, lambda: self.ai_status_label.config(
                text=f'连接成功! 模型响应: {result}', fg=self.app.c['green']))
        except Exception as e:
            self.after(0, lambda: self.ai_status_label.config(
                text=f'连接失败: {e}', fg=self.app.c['red']))

    # ── On Show (update UI state) ───────────────────────────────

    def on_show(self):
        c = self.app.c

        # Update user info
        mode_label = {'self_ai': '自有Key模式', 'builtin': '内置API模式'}
        mode_text = mode_label.get(self.app.login_mode, '')
        user_display = f"{self.app.username or ''}"
        if mode_text:
            user_display += f" · {mode_text}"
        self.user_label.config(text=user_display)

        # 根据登录模式显示/隐藏页签按钮和内容
        if self.app.login_mode == 'self_ai':
            self.tab_btns['ai_config'].pack(side=tk.LEFT, padx=(0, 4))
            self.tab_btns['activate'].pack_forget()
        else:
            self.tab_btns['activate'].pack(side=tk.LEFT, padx=(0, 4))
            self.tab_btns['ai_config'].pack_forget()

        # Update license
        lic = self.app.license_info
        if self.app.login_mode == 'self_ai':
            # Mode 1: 自有Key，始终有效
            self.license_indicator.create_oval(1, 1, 7, 7, fill=c['green'], outline='')
            self.license_label.config(text='自有Key · 无限制', fg=c['green'])
            if self.app.logged_in:
                self.start_btn.state(['!disabled'])
            else:
                self.start_btn.state(['disabled'])
        elif lic and lic['active']:
            self.license_indicator.create_oval(1, 1, 7, 7, fill=c['green'], outline='')
            exp_text = get_expiry_text(lic.get('expires_at'))
            self.license_label.config(text=f"已激活 · {exp_text}", fg=c['green'])
            self.license_detail_label.config(
                text=f"授权类型: {lic.get('card_type', '-')}\n"
                     f"到期时间: {lic.get('expires_at') or '永久有效'}\n"
                     f"状态: {exp_text}")
            if self.app.logged_in:
                self.start_btn.state(['!disabled'])
            else:
                self.start_btn.state(['disabled'])
        else:
            self.license_indicator.create_oval(1, 1, 7, 7, fill=c['red'], outline='')
            self.license_label.config(text='未激活', fg=c['red'])
            if hasattr(self, 'license_detail_label'):
                self.license_detail_label.config(text='软件未激活，请输入卡密激活')
            self.start_btn.state(['disabled'])

        # Load saved analysis
        self._load_saved_analysis()

        # 检查是否有保存的登录信息，但不自动打开浏览器
        self._update_saved_login_status()

        # 恢复上次的投递配置
        self._load_delivery_config()

        # 刷新今日投递统计
        self._refresh_today_stats()

    def _clear_activate_placeholder(self, e):
        if self.activate_key_entry.get() == 'XXXX-XXXX-XXXX-XXXX':
            self.activate_key_entry.delete(0, tk.END)

    def _format_activate_key2(self, e):
        val = e.widget.get().upper().replace('-', '').replace(' ', '')
        val = ''.join(c for c in val if c in 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789')
        val = val[:16]
        parts = [val[i:i + 4] for i in range(0, len(val), 4)]
        formatted = '-'.join(parts)
        e.widget.delete(0, tk.END)
        e.widget.insert(0, formatted)

    def _activate_in_main(self):
        card_key = self.activate_key_entry.get().strip().upper()
        if not card_key or card_key == 'XXXX-XXXX-XXXX-XXXX':
            self.activate_msg_label.config(text='请输入有效卡密', fg=self.app.c['red'])
            return

        def _run():
            machine_fp = get_machine_fingerprint()
            success, message = verify_and_activate_card(card_key, self.app.user_id, machine_fp)
            self.app.license_info = check_user_license(self.app.user_id)
            self.after(0, lambda: self._on_activate_result(success, message))

        threading.Thread(target=_run, daemon=True).start()

    def _on_activate_result(self, success, message):
        c = self.app.c
        if success:
            self.activate_msg_label.config(text=message, fg=c['green'])
            self.on_show()  # Refresh license display
        else:
            self.activate_msg_label.config(text=message, fg=c['red'])

    def _on_stop_mode(self):
        if self.stop_mode_var.get() == 'count':
            self.max_count_entry.config(state='normal')
            self.max_time_entry.config(state='disabled')
        else:
            self.max_count_entry.config(state='disabled')
            self.max_time_entry.config(state='normal')

    # ── Logging ─────────────────────────────────────────────────

    def log_msg(self, msg, platform=None):
        self.after(0, self._log_msg_ui, msg, platform)

    def _log_msg_ui(self, msg, platform=None):
        timestamp = datetime.now().strftime('%H:%M:%S')
        line = f"[{timestamp}] {msg}\n"
        widget = self.boss_log_text
        widget.insert(tk.END, line)
        widget.see(tk.END)
        log(msg)

    def _clear_platform_log(self, platform):
        self.boss_log_text.delete(1.0, tk.END)
        self.boss_log_text.insert(tk.END, '日志已清空\n')

    def _clear_log(self):
        self.boss_log_text.delete(1.0, tk.END)
        self.boss_log_text.insert(tk.END, '日志已清空\n')

    def _clear_browser_cache(self, platform='boss'):
        """清空浏览器缓存和登录状态，以便重新登录"""
        import shutil
        if not messagebox.askyesno('确认', '确定要清空浏览器缓存和登录状态吗？\n\n这将删除浏览器数据（包括已保存的密码等）。'):
            return

        cookie_file = COOKIE_FILE
        user_data = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'browser_data_boss')
        if self.app.page:
            try:
                self.app.page.quit()
            except:
                pass
            self.app.page = None
        self.app.logged_in = False
        self._update_login_ui(False)
        self.boss_login_status_label.config(text='未登录', fg=self.app.c['red'])

        if os.path.exists(cookie_file):
            try:
                os.remove(cookie_file)
            except Exception as e:
                self.log_msg(f'删除cookie文件失败: {e}')
        if os.path.exists(user_data):
            try:
                shutil.rmtree(user_data, ignore_errors=True)
            except Exception as e:
                self.log_msg(f'删除浏览器数据失败: {e}')

        self.log_msg('浏览器缓存已清空，可重新登录')
        self.start_btn.state(['disabled'])

    # ── BOSS Login ──────────────────────────────────────────────

    def _update_saved_login_status(self):
        """仅检查 cookie 文件是否存在，更新 UI 状态，不自动打开浏览器"""
        if os.path.exists(COOKIE_FILE):
            self.boss_login_status_label.config(text='已保存登录(待验证)', fg=self.app.c['orange'])

    def _check_saved_login(self):
        """手动触发：验证已保存的登录"""
        if os.path.exists(COOKIE_FILE):
            self.log_msg('手动验证BOSS登录状态...')
            self._verify_saved_login()

    def _init_browser(self):
        """初始化浏览器"""
        try:
            from DrissionPage import ChromiumPage, ChromiumOptions

            cookie_file = COOKIE_FILE
            local_port = 9222
            user_data = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'browser_data_boss')

            # 确保用户数据目录存在
            os.makedirs(user_data, exist_ok=True)

            co = ChromiumOptions()
            co.set_paths(local_port=local_port, user_data_path=user_data)
            co.set_argument('--start-maximized')
            co.set_argument('--no-sandbox')
            co.set_argument('--disable-gpu')
            co.set_argument('--disable-blink-features=AutomationControlled')
            co.set_argument('--disable-dev-shm-usage')
            co.set_argument('--disable-software-rasterizer')
            co.set_argument('--disable-web-security')
            co.set_argument('--disable-features=VizDisplayCompositor,TranslateUI')
            co.set_argument('--disable-ipc-flooding-protection')
            co.set_argument('--no-first-run')
            co.set_argument('--no-default-browser-check')
            co.set_argument('--disable-background-networking')
            co.set_user_agent(
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')

            page = ChromiumPage(co)
            self.app.page = page

            # 恢复保存的 cookies
            if os.path.exists(cookie_file):
                try:
                    with open(cookie_file, 'r', encoding='utf-8') as f:
                        cookies = json.load(f)
                    for c in cookies:
                        page.set.cookies(c)
                except:
                    pass

            self.log_msg(f'{platform} 浏览器初始化完成 (端口:{local_port})')
            return True
        except Exception as e:
            self.log_msg(f'初始化{platform}浏览器失败: {e}')
            return False

    def _verify_saved_login(self):
        def _run():
            try:
                if not self.app.page and not self._init_browser():
                    return
                # 如果浏览器被隐藏，先显示
                try:
                    self.app.page.set.window.show()
                except:
                    pass
                self.app.page.get('https://www.zhipin.com/web/geek/resume')
                time.sleep(2)
                url = self.app.page.url
                if 'user' not in url and 'login' not in url:
                    self.app.logged_in = True
                    self._save_platform_cookies()
                    self.after(0, self._update_login_ui, True)
                    self.log_msg('BOSS直聘自动登录成功! 浏览器已隐藏')
                    # 隐藏浏览器
                    try:
                        self.app.page.set.window.hide()
                    except:
                        try:
                            self.app.page.set.window.mini()
                        except:
                            pass
                else:
                    self.log_msg('BOSS登录已过期，请重新登录')
                    # 也隐藏浏览器
                    try:
                        self.app.page.set.window.hide()
                    except:
                        pass
            except Exception as e:
                self.log_msg(f'验证登录状态失败: {e}')

        threading.Thread(target=_run, daemon=True).start()

    # ── BOSS 登录 ──

    def get_boss_qr_code(self):
        self.boss_login_btn.state(['disabled'])
        self.boss_login_btn.config(text='初始化中...')
        self.boss_login_status_label.config(text='初始化中...', fg=self.app.c['orange'])

        def _run():
            try:
                if not self.app.page and not self._init_browser():
                    self.after(0, self.boss_login_btn.config, {'state': 'normal', 'text': '打开浏览器登录'})
                    return
                # 如果浏览器已存在但被隐藏，先显示
                try:
                    self.app.page.set.window.show()
                except:
                    pass
                self.app.page.get('https://www.zhipin.com/web/user/?ka=header-login')
                time.sleep(2)
                self.log_msg('请在BOSS浏览器窗口中扫码登录')
                self.after(0, self.boss_login_status_label.config,
                           {'text': '请扫码登录', 'fg': '#1890ff'})
                self.after(0, self.boss_login_btn.config, {'state': 'normal', 'text': '打开浏览器登录'})
                self._poll_boss_login()
            except Exception as e:
                self.log_msg(f'获取BOSS二维码失败: {e}')
                self.after(0, self.boss_login_status_label.config, {'text': '获取失败', 'fg': self.app.c['red']})
                self.after(0, self.boss_login_btn.config, {'state': 'normal', 'text': '打开浏览器登录'})

        threading.Thread(target=_run, daemon=True).start()

    def _poll_boss_login(self):
        if not self.app.page:
            return
        try:
            url = self.app.page.url
            if 'zhipin.com/web/geek' in url or ('zhipin.com' in url and 'user' not in url and 'login' not in url):
                self.app.logged_in = True
                self._save_platform_cookies()
                self._update_login_ui(True)
                self.log_msg('BOSS直聘登录成功! 浏览器已隐藏(后台运行)')
                # 登录成功后隐藏浏览器窗口
                try:
                    self.app.page.set.window.hide()
                except:
                    try:
                        self.app.page.set.window.mini()
                    except:
                        pass
                return
        except:
            pass
        self.after(1500, self._poll_boss_login)

    def _save_platform_cookies(self, platform='boss'):
        try:
            page = self.app.page
            if not page:
                return
            cookies = page.cookies()
            with open(COOKIE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
        except:
            pass

    def _update_login_ui(self, logged_in):
        c = self.app.c
        if logged_in:
            self.boss_login_status_label.config(text='已连接', fg=c['green'])
            self.boss_login_btn.config(text='重新登录')
        else:
            self.boss_login_status_label.config(text='未登录', fg=c['red'])

        if (self.app.logged_in) and \
                self.app.license_info and self.app.license_info['active']:
            self.start_btn.state(['!disabled'])

    def _save_delivery_config(self):
        config = {
            'mode': self.mode_var.get(),
            'threshold': self.threshold_var.get(),
            'stop_mode': self.stop_mode_var.get(),
            'max_count': self.max_count_var.get(),
            'max_time': self.max_time_var.get(),
            'city': self.city_var.get(),
            'keywords': self.title_keywords_var.get(),
            'reprocess': self.reprocess_var.get(),
            'max_daily': self.max_daily_var.get(),
        }
        try:
            with open(DELIVERY_CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except:
            pass

    def _load_delivery_config(self):
        if not os.path.exists(DELIVERY_CONFIG_FILE):
            return
        try:
            with open(DELIVERY_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            if config.get('mode'):
                self.mode_var.set(config['mode'])
            if config.get('threshold'):
                self.threshold_var.set(config['threshold'])
            if config.get('stop_mode'):
                self.stop_mode_var.set(config['stop_mode'])
                self._on_stop_mode()
            if config.get('max_count'):
                self.max_count_var.set(config['max_count'])
            if config.get('max_time'):
                self.max_time_var.set(config['max_time'])
            if config.get('city'):
                self.city_var.set(config['city'])
            if config.get('keywords'):
                self.title_keywords_var.set(config['keywords'])
            if 'reprocess' in config:
                self.reprocess_var.set(config['reprocess'])
            if 'max_daily' in config:
                self.max_daily_var.set(config['max_daily'])
        except:
            pass

    # ── Resume ──────────────────────────────────────────────────

    def _select_resume(self):
        file_path = filedialog.askopenfilename(
            title='选择简历文件',
            filetypes=[('PDF文件', '*.pdf'), ('Word文档', '*.docx'), ('所有文件', '*.*')]
        )
        if file_path:
            self.app.resume_path = file_path
            self.resume_path_label.config(text=os.path.basename(file_path))
            self.analyze_btn.state(['!disabled'])
            self.log_msg(f'已选择简历: {os.path.basename(file_path)}')

    def _start_analyze(self):
        if not self.app.resume_path:
            return
        self.analyze_btn.state(['disabled'])
        self.analyze_status_label.config(text='分析中...')
        threading.Thread(target=self._analyze_thread, daemon=True).start()

    def _analyze_thread(self):
        try:
            from resume_analyzer import ResumeAnalyzer
            # Mode 1: 使用用户自定义的AI配置
            if self.app.login_mode == 'self_ai':
                config = self.app.user_ai_config
                api_key = config.get('api_key', '').strip()
                if not api_key:
                    self.after(0, lambda: messagebox.showwarning('提示',
                        '请先在「AI模型」页签中配置您的API Key！'))
                    self.after(0, lambda: self.analyze_status_label.config(text='请先配置API Key'))
                    self.after(0, lambda: self.analyze_btn.state(['!disabled']))
                    return
                self.app.analyzer = ResumeAnalyzer(
                    api_key=api_key,
                    base_url=config.get('base_url'),
                    model=config.get('model')
                )
            else:
                self.app.analyzer = ResumeAnalyzer()
            self.app.analyzer.log_callback = lambda msg: self.log_msg(msg)
            path = self.app.resume_path

            if path.endswith('.pdf'):
                text = self.app.analyzer.extract_text_from_pdf(path)
            elif path.endswith('.docx'):
                text = self.app.analyzer.extract_text_from_docx(path)
            else:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()

            if text:
                self.app.resume_text = text
                self.log_msg(f'简历文本长度: {len(text)} 字符')
                self.log_msg('正在调用AI分析简历...')
                result = self.app.analyzer.analyze_resume(text)
                self.app.analysis_result = result
                self.after(0, lambda: self._on_analyze_done(result))
            else:
                self.after(0, lambda: self.analyze_status_label.config(text='无法读取简历'))
                self.after(0, lambda: self.analyze_btn.state(['!disabled']))
        except Exception as e:
            self.log_msg(f'分析失败: {e}')
            self.after(0, lambda: self.analyze_status_label.config(text=f'失败: {e}'))
            self.after(0, lambda: self.analyze_btn.state(['!disabled']))

    def _on_analyze_done(self, result):
        if result:
            self.analyze_status_label.config(text='分析完成!')

            # Build display
            lines = []
            lines.append('╔══════════════════════════════╗')
            lines.append('║     AI 简历分析结果          ║')
            lines.append('╚══════════════════════════════╝')
            lines.append('')

            if 'skills' in result:
                lines.append('【核心技能】')
                for s in result['skills']:
                    lines.append(f'  · {s}')
                lines.append('')
            if 'recommended_positions' in result:
                lines.append('【推荐岗位】')
                for p in result['recommended_positions']:
                    lines.append(f'  · {p}')
                lines.append('')
            if 'search_keywords' in result:
                lines.append('【搜索关键词】')
                for k in result['search_keywords']:
                    lines.append(f'  · {k}')
                self.title_keywords_var.set(','.join(result['search_keywords'][:5]))
                lines.append('')
            if 'recommended_industries' in result:
                lines.append('【推荐行业】')
                for i in result['recommended_industries']:
                    lines.append(f'  · {i}')
                lines.append('')

            display = '\n'.join(lines)
            self.analysis_text.delete(1.0, tk.END)
            self.analysis_text.insert(tk.END, display)

            # Save
            try:
                with open(ANALYSIS_FILE, 'w', encoding='utf-8') as f:
                    json.dump({
                        'analysis_result': result,
                        'resume_text': self.app.resume_text,
                        'save_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }, f, ensure_ascii=False, indent=2)
            except:
                pass

            if (self.app.logged_in) and \
                    self.app.license_info and self.app.license_info['active']:
                self.start_btn.state(['!disabled'])
        else:
            self.analyze_status_label.config(text='分析失败')

        self.analyze_btn.state(['!disabled'])

    def _load_saved_analysis(self):
        if os.path.exists(ANALYSIS_FILE):
            try:
                with open(ANALYSIS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.app.analysis_result = data.get('analysis_result')
                self.app.resume_text = data.get('resume_text')
                if self.app.analysis_result:
                    self.analyze_status_label.config(text='已加载历史分析')
                    if 'search_keywords' in self.app.analysis_result:
                        self.title_keywords_var.set(
                            ','.join(self.app.analysis_result['search_keywords'][:5]))
            except:
                pass

    # ── Delivery ────────────────────────────────────────────────

    def start_search_thread(self):
        if self.app.delivery_running:
            return
        if not self.app.resume_text:
            messagebox.showwarning('提示', '请先选择并分析简历!')
            return

        # Mode 1: 检查是否已配置AI Key
        if self.app.login_mode == 'self_ai':
            api_key = self.app.user_ai_config.get('api_key', '').strip()
            if not api_key:
                messagebox.showwarning('提示', '请先在「AI模型」页签中配置您的API Key！')
                return

        # 保存当前配置
        self._save_delivery_config()

        # 检查BOSS登录状态
        if not self.app.logged_in:
            messagebox.showwarning('提示', 'BOSS直聘未登录，请先登录!')
            return

        # 重置本次投递计数器
        self.boss_session_count = 0
        self.boss_count_label.config(text='BOSS: 0')

        # 创建共享每日计数器（线程安全）
        max_daily = int(self.max_daily_var.get() or 0)
        start_count = 0
        if self.app.user_id and max_daily > 0:
            stats = get_today_delivery_stats(self.app.user_id)
            start_count = stats['total']
        self.app.daily_state = {
            'start_count': start_count,
            'session_count': 0,
            'max_daily': max_daily,
            'lock': threading.Lock()
        }

        # 追踪启动和完成状态
        self.app.boss_started = True
        self.app.boss_completed = False

        self._refresh_today_stats()

        self.app.matched_jobs = []
        self.app.current_job_index = 0
        self.app.delivery_running = True
        self.app.delivery_threads = []
        self.start_btn.state(['disabled'])
        self.stop_btn.state(['!disabled'])

        # 投递开始：隐藏浏览器
        if self.app.page:
            try:
                self.app.page.set.window.hide()
            except:
                try:
                    self.app.page.set.window.mini()
                except:
                    pass

        mode = self.mode_var.get()
        self.status_text.config(text='投递中 (BOSS)...')
        platform = 'boss'
        t = threading.Thread(target=self._search_thread, args=(platform, mode), daemon=True)
        t.start()
        self.app.delivery_threads.append(t)

    def _search_thread(self, platform, mode):
        try:
            from resume_analyzer import ResumeAnalyzer

            if not self.app.analyzer:
                if self.app.login_mode == 'self_ai':
                    config = self.app.user_ai_config
                    self.app.analyzer = ResumeAnalyzer(
                        api_key=config.get('api_key'),
                        base_url=config.get('base_url'),
                        model=config.get('model')
                    )
                else:
                    self.app.analyzer = ResumeAnalyzer()
                self.app.analyzer.log_callback = lambda msg: self.log_msg(msg)
                self.app.analyzer.resume_text = self.app.resume_text

            from job_delivery_dp import JobDeliveryDP
            page = self.app.page
            delivery = JobDeliveryDP(page, self.app.analyzer)
            self.app.delivery = delivery

            stop_mode = self.stop_mode_var.get()
            max_count = int(self.max_count_var.get() or MAX_DELIVERY_COUNT)
            max_time = int(self.max_time_var.get() or 60)
            delivery.max_delivery = max_count
            delivery.stop_mode = stop_mode
            delivery.max_time_seconds = max_time * 60
            delivery.reprocess_skipped = self.reprocess_var.get()
            delivery.daily_state = self.app.daily_state
            delivery.user_id = self.app.user_id

            title_keywords = [k.strip() for k in self.title_keywords_var.get().split(',') if k.strip()]
            threshold = int(self.threshold_var.get() or 60)
            city_name = self.city_var.get()

            from config import CITY_MAP
            city_code = next((code for code, name in CITY_MAP.items() if name == city_name), '101010100')

            # 确保浏览器保持隐藏
            if page:
                try:
                    page.set.window.hide()
                except:
                    pass

            pname = delivery.platform_name
            self.log_msg(f'[{pname}] {"=" * 30}')
            self.log_msg(f'[{pname}] 开始搜索投递 - {city_name} | 阈值: {threshold}%')
            self.log_msg(f'[{pname}] 关键词: {title_keywords}')

            delivery.log_callback = lambda msg, p=pname: self.log_msg(f'[{p}] {msg}')

            if mode == 'auto':
                delivery.search_and_filter_jobs(
                    title_keywords=title_keywords, threshold=threshold,
                    resume_text=self.app.resume_text, mode='auto',
                    city_code=city_code,
                    log_callback=delivery.log_callback,
                    callback=lambda j, s, d: self._auto_callback(j, s, d, delivery, threshold, platform)
                )
                self.app.page = delivery.page
                self.after(0, lambda: self._on_platform_complete(True))
            else:
                delivery.search_and_collect_jobs(
                    title_keywords=title_keywords,
                    resume_text=self.app.resume_text,
                    city_code=city_code,
                    log_callback=delivery.log_callback,
                    callback=self._collect_callback
                )
                self.app.page = delivery.page
                self.after(0, lambda: self._on_platform_complete(False))
        except Exception as e:
            self.log_msg(f'[BOSS] 搜索异常: {e}')
            import traceback
            traceback.print_exc()
            self.after(0, lambda: self._on_platform_complete(True))

    def _auto_callback(self, job_info, match_score, job_detail, delivery, threshold, platform='boss'):
        if not self.app.delivery_running:
            return False
        pname = delivery.platform_name
        self.log_msg(f'[{pname}] 岗位: {job_info["title"]} | {job_info["company"]} | 匹配度: {match_score}%')
        if match_score >= threshold:
            self.log_msg(f'[{pname}]   -> 匹配度达标，开始投递...')
            success = delivery.deliver_job(job_info, self.app.resume_text)
            if success:
                # 记录到数据库
                if self.app.user_id:
                    record_delivery(
                        self.app.user_id,
                        job_info.get('company', '未知'),
                        job_info.get('title', '未知'),
                        match_score, True, platform
                    )
                # 递增共享每日计数器
                if self.app.daily_state:
                    with self.app.daily_state['lock']:
                        self.app.daily_state['session_count'] += 1
                # 更新UI：本次计数 + 今日统计
                cnt = delivery.delivery_count
                self.after(0, lambda c=cnt, p=platform: self._update_delivery_stats(p, c))
                self.log_msg(f'[{pname}]   -> 投递成功!')
            else:
                self.log_msg(f'[{pname}]   -> 投递失败')
            return success
        else:
            self.log_msg(f'[{pname}]   -> 匹配度不足，跳过')
            return False

    def _update_delivery_stats(self, platform, session_count):
        """更新UI上的投递统计：本次计数 + 今日计数"""
        # 更新本次投递计数
        self.boss_session_count = session_count
        self.boss_count_label.config(text=f'BOSS本次: {session_count}')

        # 获取今日数据库统计
        if self.app.user_id:
            stats = get_today_delivery_stats(self.app.user_id)
            self.today_total_label.config(
                text=f'今日总投递: {stats["total"]}'
            )

    def _collect_callback(self, job_info, match_score, job_detail):
        if not self.app.delivery_running:
            return False
        self.app.matched_jobs.append({
            'job_info': job_info, 'match_score': match_score, 'job_detail': job_detail
        })
        self.log_msg(f"收集: {job_info['title']} | {job_info['company']} | {match_score}%")
        return True

    def _on_platform_complete(self, is_auto):
        self.log_msg('[BOSS] 投递完成')

        self.app.boss_completed = True
        self.app.delivery_running = False
        self.start_btn.state(['!disabled'])
        self.stop_btn.state(['disabled'])

        # 投递完成后保持浏览器隐藏
        if self.app.page:
            try:
                self.app.page.set.window.hide()
            except:
                pass

        boss_cnt = self.app.delivery.delivery_count if self.app.delivery else 0

        if is_auto:
            boss_session = self.boss_session_count

            # 刷新今日统计
            self._refresh_today_stats()
            stats = get_today_delivery_stats(self.app.user_id) if self.app.user_id else {'total': 0}

            self.status_text.config(text=f'全部完成! 本次:{boss_session}  今日总:{stats["total"]}')
            self.log_msg(f'全部投递完成! 本次:{boss_session} | 今日总:{stats["total"]}')
        else:
            if self.app.matched_jobs:
                self.status_text.config(text=f'找到 {len(self.app.matched_jobs)} 个匹配岗位')
                self.app.current_job_index = 0
                self._show_current_job()
            else:
                self.status_text.config(text='未找到匹配岗位')

    def _refresh_today_stats(self):
        """从数据库刷新今日投递统计数据"""
        if self.app.user_id:
            stats = get_today_delivery_stats(self.app.user_id)
            self.today_total_label.config(
                text=f'今日总投递: {stats["total"]}'
            )

    def stop_delivery(self):
        self.app.delivery_running = False
        if self.app.delivery:
            self.app.delivery.running = False
        self.log_msg('已停止投递')
        self.stop_btn.state(['disabled'])
        self.start_btn.state(['!disabled'])
        self.status_text.config(text='已停止')
        # 刷新今日统计
        self._refresh_today_stats()

    # ── Manual Review ───────────────────────────────────────────

    def _show_current_job(self):
        idx = self.app.current_job_index
        jobs = self.app.matched_jobs

        if idx >= len(jobs):
            self.job_title_label.config(text='无更多岗位')
            self.deliver_btn.state(['disabled'])
            self.skip_btn.state(['disabled'])
            return

        c = self.app.c
        current = jobs[idx]
        job_info = current['job_info']
        match_score = current['match_score']
        job_detail = current.get('job_detail', '')

        self.job_title_label.config(text=job_info.get('title', '-'))
        self.job_company_label.config(text=job_info.get('company', '-'))
        self.job_salary_label.config(text=job_info.get('salary', '-'))
        self.job_time_label.config(text=job_info.get('publish_time', '-'))

        score_color = c['green'] if match_score >= 80 else (c['orange'] if match_score >= 60 else c['red'])
        self.job_match_label.config(text=f'{match_score}%', fg=score_color)

        organized = job_detail
        if self.app.analyzer and job_detail:
            organized = self.app.analyzer.organize_job_detail(job_detail)

        self.job_detail_text.delete(1.0, tk.END)
        self.job_detail_text.insert(tk.END, organized or '无详情')

        self.job_progress_label.config(text=f'第 {idx + 1} / {len(jobs)} 个')

        self.greeting_text.delete(1.0, tk.END)
        self.greeting_text.insert(tk.END, '正在生成打招呼语...')
        self.deliver_btn.state(['disabled'])
        self.skip_btn.state(['disabled'])

        threading.Thread(target=self._gen_greeting_thread,
                         args=(job_info, organized), daemon=True).start()

    def _gen_greeting_thread(self, job_info, job_detail):
        try:
            if self.app.analyzer and self.app.resume_text:
                greeting = self.app.analyzer.generate_greeting_message(
                    job_info.get('title', ''), job_info.get('company', ''),
                    self.app.resume_text, job_detail)
            else:
                greeting = f"您好，我对{job_info.get('title', '')}岗位很感兴趣。"
            self.after(0, lambda: self._update_greeting(greeting))
        except:
            self.after(0, lambda: self._update_greeting(
                f"您好，我对{job_info.get('title', '')}岗位很感兴趣。"))

    def _update_greeting(self, greeting):
        self.greeting_text.delete(1.0, tk.END)
        self.greeting_text.insert(tk.END, greeting)
        self.deliver_btn.state(['!disabled'])
        self.skip_btn.state(['!disabled'])

    def _manual_deliver(self):
        idx = self.app.current_job_index
        if idx >= len(self.app.matched_jobs):
            return
        current = self.app.matched_jobs[idx]
        greeting = self.greeting_text.get(1.0, tk.END).strip()

        def _run():
            success = self.app.delivery.deliver_job(current['job_info'], self.app.resume_text, greeting)
            if success:
                job_info = current['job_info']
                if self.app.user_id:
                    record_delivery(
                        self.app.user_id,
                        job_info.get('company', '未知'),
                        job_info.get('title', '未知'),
                        current.get('match_score', 0), True, 'boss'
                    )
                cnt = self.app.delivery.delivery_count
                self.after(0, lambda c=cnt: self._update_delivery_stats('boss', c))
                self.log_msg('投递成功!')
            else:
                self.log_msg('投递失败')
            self.app.current_job_index += 1
            self.after(0, self._show_current_job)

        threading.Thread(target=_run, daemon=True).start()

    def _skip_job(self):
        idx = self.app.current_job_index
        if idx < len(self.app.matched_jobs):
            current = self.app.matched_jobs[idx]
            job_url = current['job_info'].get('url')
            if job_url and self.app.delivery:
                self.app.delivery.update_job_status(job_url, 2,
                                                    current['job_info'].get('title', ''),
                                                    current.get('match_score', 0))
        self.log_msg('跳过当前岗位')
        self.app.current_job_index += 1
        self._show_current_job()

    def do_logout(self):
        self.app.delivery_running = False
        if self.app.delivery:
            self.app.delivery.running = False
        self.app.user_id = None
        self.app.username = None
        self.app.login_mode = None
        self.app.logged_in = False
        log('用户退出登录')
        self.app.show_frame('LoginFrame')


# ═══════════════════════════════════════════════════════════════════
#  Entry Point
# ═══════════════════════════════════════════════════════════════════

def main():
    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 程序启动 v3.0 Pro\n")

    app = App()
    app.mainloop()


if __name__ == '__main__':
    main()
