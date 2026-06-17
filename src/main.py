import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
import random
import threading
import time
import os
from datetime import datetime
from PIL import ImageGrab  # 截图

# ---------- 配置 ----------
WORK_START = 0   # 每日开始弹窗时间（小时）
WORK_END = 22    # 每日结束弹窗时间（小时）
MIN_INTERVAL = 5   # 随机间隔下限（整数秒）
MAX_INTERVAL =  15 # 随机间隔上限（整数秒）
SCREENSHOT_DIR = "screenshots"
DB_FILE = "whatido.db"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)

# ---------- 数据库初始化 ----------
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

# ---------- 核心功能 ----------
def take_screenshot():
    """截取全屏并保存，返回文件路径"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(SCREENSHOT_DIR, f"cap_{timestamp}.png")
    ImageGrab.grab().save(path)
    return path

def save_record(doing, next_plan, screenshot_path):
    """存入数据库"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT INTO records (timestamp, doing, next_plan, screenshot_path) VALUES (?, ?, ?, ?)",
        (datetime.now().isoformat(), doing, next_plan, screenshot_path)
    )
    conn.commit()
    conn.close()

def popup_window():
    """先截图，再弹出输入窗口"""
    # 1. 先截图（无论用户是否提交，都保存这一刻的屏幕）
    try:
        img_path = take_screenshot()
    except Exception as e:
        img_path = f"截图失败: {e}"

    # 2. 创建输入窗口
    win = tk.Toplevel()
    win.title("⏰ 在干嘛？")
    win.geometry("400x250")
    win.attributes("-topmost", True)
    win.grab_set()

    # 时间显示
    tk.Label(win, text=f"当前时间：{datetime.now().strftime('%H:%M:%S')}").pack(pady=5)
    tk.Label(win, text="你现在在做什么？").pack(pady=5)
    doing_entry = tk.Entry(win, width=40)
    doing_entry.pack(pady=5)
    doing_entry.focus()

    tk.Label(win, text="下一步计划？").pack(pady=5)
    next_entry = tk.Entry(win, width=40)
    next_entry.pack(pady=5)

    def on_submit():
        doing = doing_entry.get().strip() or "未填写"
        next_plan = next_entry.get().strip() or "未填写"
        # 直接使用已捕获的截图路径
        save_record(doing, next_plan, img_path)
        win.destroy()
        # 预留AI触发点
        # trigger_ai_analysis(doing, next_plan, img_path)

    tk.Button(win, text="提交", command=on_submit, width=20).pack(pady=15)
    win.bind("<Return>", lambda e: on_submit())

    # 3. 等待窗口关闭（阻塞）
    win.wait_window()

# ---------- 定时调度 ----------
def schedule_loop():
    """后台循环，按随机间隔弹出"""
    while True:
        # 检查是否在工作时间内
        now = datetime.now()
        if WORK_START <= now.hour < WORK_END:
            popup_window()
        # 随机间隔（分钟→秒）
        interval_seconds = random.randint(int(MIN_INTERVAL), int(MAX_INTERVAL)) # * 60 秒
        time.sleep(interval_seconds)

# ---------- 可选：简易AI分析（预留接口）----------
def trigger_ai_analysis(doing, next_plan, screenshot_path):
    """
    此处可接入本地模型或云端 API，分析当前记录。
    例如：检测是否偏离计划、给出即时建议等。
    本示例仅打印日志。
    """
    print(f"[AI] 分析记录：Doing={doing}, Next={next_plan}")

# ---------- 启动系统托盘图标（简化版，用主窗口代替）----------
if __name__ == "__main__":
    # 创建主窗口（隐藏，仅作为托盘承载）
    root = tk.Tk()
    root.title("在干嘛 - 后台运行")
    root.geometry("200x100")
    root.withdraw()  # 默认隐藏主窗口

    # 可在系统托盘中显示（此处省略，使用简单菜单）
    def show_about():
        messagebox.showinfo("在干嘛", "随机弹窗记录工具 v0.1\n截图保存在本地，AI预留")

    # 右键菜单（简单）
    menu = tk.Menu(root, tearoff=0)
    menu.add_command(label="显示主界面", command=lambda: root.deiconify())
    menu.add_command(label="关于", command=show_about)
    menu.add_command(label="退出", command=root.quit)

    def popup_menu(event):
        menu.post(event.x_root, event.y_root)

    # 绑定右键（仅在主窗口显示时有效，此处简化）
    root.bind("<Button-3>", popup_menu)

    # 启动后台线程
    t = threading.Thread(target=schedule_loop, daemon=True)
    t.start()

    # 进入消息循环
    root.mainloop()