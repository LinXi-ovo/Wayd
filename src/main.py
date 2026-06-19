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
from tkinter import messagebox
import sqlite3
import random
import threading
import os
import signal
import sys
import atexit
from datetime import datetime
from PIL import Image, ImageDraw, ImageGrab
import pystray
from win10toast import ToastNotifier

# ── 配置 ──
WORK_START = 9
WORK_END = 23
MIN_INTERVAL = 25 * 60
MAX_INTERVAL = 45 * 60
SCREENSHOT_DIR = "screenshots"
DB_FILE = "whatido.db"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)

# ── 线程间通信 ──
stop_event = threading.Event()      # 全局停止信号
state_lock = threading.Lock()        # 共享状态保护锁
popup_done = threading.Event()       # 弹窗完成信号
_popup_active = False                # 弹窗是否正在显示

def is_popup_active():
    global _popup_active
    with state_lock:
        return _popup_active

def set_popup_active(val):
    global _popup_active
    with state_lock:
        _popup_active = val

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
            interval = random.randint(MIN_INTERVAL, MAX_INTERVAL)
            notify_at = max(interval - 30, 5)

            # 第一阶段：等待到通知时间
            if stop_event.wait(notify_at):
                break

            if not stop_event.is_set():
                send_toast(
                    "🔔 在干嘛 - WAYD",
                    "半小时到了，记录一下吧！",
                )

            # 第二阶段：等待到弹窗时间
            remaining = interval - notify_at
            if stop_event.wait(remaining):
                break

            if not stop_event.is_set():
                popup_done.clear()
                root.after(0, lambda: popup_window(root))
                # 等待弹窗结束，同时每秒检查停止信号
                while not popup_done.is_set() and not stop_event.is_set():
                    stop_event.wait(1)

        else:
            # 非工作时间：每小时检查一次
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
    root.title("在干嘛 - WAYD")
    root.geometry("300x100")
    root.withdraw()

    # 托盘菜单回调
    def _show_window(icon, item):
        root.deiconify()
        root.lift()
        root.focus_force()

    def _record_now(icon, item):
        root.after(0, lambda: popup_window(root))

    def _show_status(icon, item):
        now_str = datetime.now().strftime("%H:%M:%S")
        popup = "是" if is_popup_active() else "否"
        root.after(0, lambda: messagebox.showinfo(
            "WAYD 状态",
            f"运行状态：正常\n当前时间：{now_str}\n弹窗中：{popup}"
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

    # 窗口关闭事件（托盘右键退出才是正确退出方式）
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
