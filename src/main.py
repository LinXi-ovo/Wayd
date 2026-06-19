"""
WAYD (What Are You Doing) - 在干嘛
后台常驻系统托盘版

功能：
- pystray 系统托盘图标 + 右键菜单
- win10toast Windows 原生通知
- threading.Event 事件驱动定时（替代 time.sleep）
- threading.Lock 线程安全共享状态
- signal + atexit 优雅退出
"""

import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
import random
import threading
import os
import json
import subprocess
import signal
import sys
import atexit
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageGrab
import pystray
from win10toast import ToastNotifier

# ── 配置 ──
WORK_START = 9
WORK_END = 23
SCREENSHOT_DIR = "screenshots"
DB_FILE = "whatido.db"
CONFIG_FILE = "config.json"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)

# ── 动态配置（从 config.json 加载）──
cfg_min_interval = 25 * 60    # 默认 25 分钟
cfg_max_interval = 45 * 60    # 默认 45 分钟

def load_config():
    global cfg_min_interval, cfg_max_interval
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
            cfg_min_interval = int(data.get("min_interval", cfg_min_interval))
            cfg_max_interval = int(data.get("max_interval", cfg_max_interval))
    except Exception as e:
        print(f"[config] 加载失败：{e}")

def save_config():
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump({"min_interval": cfg_min_interval, "max_interval": cfg_max_interval}, f, indent=2)
    except Exception as e:
        print(f"[config] 保存失败：{e}")

load_config()

# ── 线程间通信 ──
stop_event = threading.Event()      # 全局停止信号
state_lock = threading.Lock()        # 共享状态保护锁
popup_done = threading.Event()       # 弹窗完成信号
_popup_active = False                # 弹窗是否正在显示
_remaining = 0                       # 距离下次触发剩余秒数

def is_popup_active():
    global _popup_active
    with state_lock:
        return _popup_active

def set_popup_active(val):
    global _popup_active
    with state_lock:
        _popup_active = val

def get_remaining():
    with state_lock:
        return _remaining

def set_remaining(val):
    global _remaining
    with state_lock:
        _remaining = val

def set_interval_config(min_val, max_val):
    global cfg_min_interval, cfg_max_interval
    cfg_min_interval = min_val
    cfg_max_interval = max_val
    save_config()

# ── 数据库 ──
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            doing TEXT,
            next_plan TEXT,
            screenshot_path TEXT,
            ai_analysis TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ── Toast 通知 ──
_toaster = ToastNotifier()
_toast_lock = threading.Lock()

def send_toast(title, message):
    with _toast_lock:
        _toaster.show_toast(
            title, message,
            duration=10, threaded=True,
        )

# ── 托盘图标 ──
def create_tray_image():
    """绘制一个简单的钟表托盘图标"""
    img = Image.new("RGB", (64, 64), color=(0, 120, 215))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, 62, 62], fill=(0, 150, 255), outline="white", width=3)
    draw.ellipse([28, 28, 36, 36], fill="white")
    draw.line((32, 32, 32, 14), fill="white", width=2)
    draw.line((32, 32, 46, 32), fill="white", width=2)
    return img

# ── 核心功能 ──
def take_screenshot():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(SCREENSHOT_DIR, f"cap_{timestamp}.png")
    ImageGrab.grab().save(path)
    return path

def save_record(doing, next_plan, screenshot_path):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT INTO records (timestamp, doing, next_plan, screenshot_path) VALUES (?, ?, ?, ?)",
        (datetime.now().isoformat(), doing, next_plan, screenshot_path)
    )
    conn.commit()
    conn.close()

def popup_window(root):
    """弹出记录窗口（必须在 tk 主线程调用）"""
    if is_popup_active():
        return
    set_popup_active(True)
    popup_done.clear()

    try:
        img_path = take_screenshot()
    except Exception as e:
        img_path = f"截图失败: {e}"

    win = tk.Toplevel(root)
    win.title("⏰ 在干嘛？")
    win.geometry("420x280")
    win.attributes("-topmost", True)
    win.grab_set()

    tk.Label(win, text=f"当前时间：{datetime.now().strftime('%H:%M:%S')}").pack(pady=5)
    tk.Label(win, text="你现在在做什么？").pack(pady=5)
    doing_entry = tk.Entry(win, width=45)
    doing_entry.pack(pady=5)
    doing_entry.focus()

    tk.Label(win, text="下一步计划？").pack(pady=5)
    next_entry = tk.Entry(win, width=45)
    next_entry.pack(pady=5)

    def on_submit():
        doing = doing_entry.get().strip() or "未填写"
        next_plan = next_entry.get().strip() or "未填写"
        save_record(doing, next_plan, img_path)
        win.destroy()

    tk.Button(win, text="提交", command=on_submit, width=20).pack(pady=15)
    win.bind("<Return>", lambda e: on_submit())

    def on_close():
        set_popup_active(False)
        popup_done.set()
        win.destroy()
    win.protocol("WM_DELETE_WINDOW", on_close)

    win.wait_window()
    set_popup_active(False)
    popup_done.set()

# ── 后台工作线程 ──
def worker_loop(root):
    """后台循环：等待随机间隔 → 提前通知 → 弹窗记录"""
    while not stop_event.is_set():
        now = datetime.now()
        hour = now.hour

        if WORK_START <= hour < WORK_END:
            interval = random.randint(cfg_min_interval, cfg_max_interval)
            notify_at = max(interval - 30, 5)
            remaining = interval

            # 第一阶段：等待到通知时间
            while remaining > notify_at and not stop_event.is_set():
                set_remaining(remaining)
                stop_event.wait(1)
                remaining -= 1

            if stop_event.is_set():
                break

            send_toast(
                "🔔 在干嘛 - WAYD",
                "半小时到了，记录一下吧！",
            )

            # 第二阶段：等待到弹窗时间
            while remaining > 0 and not stop_event.is_set():
                set_remaining(remaining)
                stop_event.wait(1)
                remaining -= 1

            set_remaining(0)

            if not stop_event.is_set():
                popup_done.clear()
                root.after(0, lambda: popup_window(root))
                while not popup_done.is_set() and not stop_event.is_set():
                    stop_event.wait(1)

        else:
            set_remaining(-1)  # 非工作时间
            stop_event.wait(3600)

    print("[worker] 工作线程已退出")

# ── 信号处理 ──
def _signal_handler(signum, frame):
    stop_event.set()
    sys.exit(0)

signal.signal(signal.SIGINT, _signal_handler)
try:
    signal.signal(signal.SIGTERM, _signal_handler)
except Exception:
    pass

# ── 退出清理 ──
@atexit.register
def _cleanup():
    stop_event.set()

# ── 主入口 ──
def main():
    root = tk.Tk()
    root.title("在干嘛 - WAYD 控制面板")
    root.geometry("380x300")
    root.resizable(False, False)
    root.withdraw()

    # ── 控制面板界面 ──
    stats_text = tk.StringVar(value="📈 统计加载中...")
    remain_text = tk.StringVar(value="距离下次触发：--")

    def build_panel():
        for w in root.winfo_children():
            w.destroy()

        main_frame = ttk.Frame(root, padding=16)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="⏰ 在干嘛 - WAYD", font=("Arial", 14, "bold")).pack(pady=(0, 8))
        ttk.Separator(main_frame).pack(fill=tk.X, pady=4)

        info_frame = ttk.Frame(main_frame)
        info_frame.pack(fill=tk.X, pady=4)

        ttk.Label(info_frame, textvariable=stats_text, font=("Arial", 10)).pack(anchor=tk.W, pady=2)
        refresh_stats()

        ttk.Label(info_frame, textvariable=remain_text, font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=2)

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Button(btn_frame, text="📊 打开数据浏览", command=open_viewer, width=25).pack(pady=3)
        ttk.Button(btn_frame, text="📝 立即记录", command=lambda: popup_window(root), width=25).pack(pady=3)
        ttk.Button(btn_frame, text="⚙️ 设置", command=open_settings, width=25).pack(pady=3)
        ttk.Button(btn_frame, text="🔄 刷新", command=refresh_all, width=25).pack(pady=3)

        update_remaining_display()

    def update_remaining_display():
        r = get_remaining()
        if r < 0:
            remain_text.set("⏳ 当前非工作时间")
        elif r == 0:
            remain_text.set("⏳ 即将触发...")
        else:
            minutes = r // 60
            seconds = r % 60
            remain_text.set(f"⏳ 距离下次触发：{minutes}分{seconds}秒")
        if not stop_event.is_set():
            root.after(1000, update_remaining_display)

    def refresh_all():
        refresh_stats()
        update_remaining_display()

    def refresh_stats():
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            today = datetime.now().strftime("%Y-%m-%d")
            total = c.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            today_count = c.execute("SELECT COUNT(*) FROM records WHERE date(timestamp)=?", (today,)).fetchone()[0]
            top = c.execute("SELECT doing, COUNT(*) as c FROM records WHERE date(timestamp)=? GROUP BY doing ORDER BY c DESC LIMIT 1", (today,)).fetchone()
            conn.close()
            top_text = f" | 今日最多：{top[0]}" if top else ""
            stats_text.set(f"📈 总记录：{total}  今日：{today_count}{top_text}")
        except Exception:
            stats_text.set("📈 统计加载失败")

    def open_viewer():
        viewer_path = os.path.join(os.path.dirname(__file__), "view.py")
        if os.path.exists(viewer_path):
            subprocess.Popen([sys.executable, viewer_path], shell=True)
        else:
            messagebox.showerror("错误", f"找不到 view.py：{viewer_path}")
        root.withdraw()

    def open_settings():
        dialog = tk.Toplevel(root)
        dialog.title("⚙️ 间隔设置")
        dialog.geometry("320x200")
        dialog.resizable(False, False)
        dialog.transient(root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="设置弹窗间隔时间", font=("Arial", 12, "bold")).pack(pady=(0, 10))
        ttk.Separator(frame).pack(fill=tk.X, pady=4)

        ttk.Label(frame, text="下限（秒）：").pack(anchor=tk.W, pady=(6, 0))
        min_var = tk.StringVar(value=str(cfg_min_interval))
        min_entry = ttk.Entry(frame, textvariable=min_var, width=15)
        min_entry.pack(anchor=tk.W, pady=2)

        ttk.Label(frame, text="上限（秒）：").pack(anchor=tk.W, pady=(6, 0))
        max_var = tk.StringVar(value=str(cfg_max_interval))
        max_entry = ttk.Entry(frame, textvariable=max_var, width=15)
        max_entry.pack(anchor=tk.W, pady=2)

        def on_save():
            try:
                new_min = int(min_var.get().strip())
                new_max = int(max_var.get().strip())
                if new_min <= 0 or new_max <= 0:
                    raise ValueError("必须为正数")
                if new_min > new_max:
                    raise ValueError("下限不能大于上限")
                set_interval_config(new_min, new_max)
                dialog.destroy()
                messagebox.showinfo("成功", f"间隔已更新：{new_min} ~ {new_max} 秒")
            except ValueError as e:
                messagebox.showerror("输入错误", str(e))

        btn_f = ttk.Frame(frame)
        btn_f.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(btn_f, text="保存", command=on_save, width=12).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_f, text="取消", command=dialog.destroy, width=12).pack(side=tk.LEFT, padx=5)

    def _show_window(icon, item):
        build_panel()
        root.deiconify()
        root.lift()
        root.focus_force()

    def _record_now(icon, item):
        root.after(0, lambda: popup_window(root))

    def _show_status(icon, item):
        now_str = datetime.now().strftime("%H:%M:%S")
        popup = "是" if is_popup_active() else "否"
        r = get_remaining()
        remain_str = "非工作时间" if r < 0 else f"{r}秒后"
        root.after(0, lambda: messagebox.showinfo(
            "WAYD 状态",
            f"运行状态：正常\n当前时间：{now_str}\n弹窗中：{popup}\n"
            f"间隔设置：{cfg_min_interval}s ~ {cfg_max_interval}s\n距离下次：{remain_str}"
        ))

    def _quit_app(icon, item):
        stop_event.set()
        icon.stop()
        root.quit()

    # 创建托盘图标与菜单
    menu = pystray.Menu(
        pystray.MenuItem("显示窗口", _show_window, default=True),
        pystray.MenuItem("立即记录", _record_now),
        pystray.MenuItem("状态", _show_status),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", _quit_app),
    )
    icon = pystray.Icon("wayd", create_tray_image(), "在干嘛 - WAYD", menu)

    def _on_closing():
        root.withdraw()

    root.protocol("WM_DELETE_WINDOW", _on_closing)

    # 启动线程
    t_icon = threading.Thread(target=icon.run, daemon=False, name="tray-icon")
    t_worker = threading.Thread(target=worker_loop, args=(root,), daemon=False, name="worker")

    t_icon.start()
    t_worker.start()

    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        t_worker.join(timeout=3)
        icon.stop()
        t_icon.join(timeout=3)

if __name__ == "__main__":
    main()
