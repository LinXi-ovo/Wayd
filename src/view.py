import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import os

DB_FILE = "whatido.db"  # 与主程序一致

def get_records(limit=100, offset=0, date_filter=None):
    """从数据库获取记录，支持日期过滤和分页"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    query = "SELECT id, timestamp, doing, next_plan, screenshot_path FROM records"
    params = []
    if date_filter:
        query += " WHERE date(timestamp) = ?"
        params.append(date_filter)
    query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return rows

def get_stats(date_filter=None):
    """获取统计信息"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # 总记录数
    total = c.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    # 今日记录数（若未过滤则计算今日，若已过滤则计算过滤日期）
    if date_filter:
        today_count = c.execute("SELECT COUNT(*) FROM records WHERE date(timestamp) = ?", (date_filter,)).fetchone()[0]
    else:
        today = datetime.now().strftime("%Y-%m-%d")
        today_count = c.execute("SELECT COUNT(*) FROM records WHERE date(timestamp) = ?", (today,)).fetchone()[0]
    # 最常做的活动（doing 出现次数最多的）
    top_doing = c.execute("SELECT doing, COUNT(*) as cnt FROM records GROUP BY doing ORDER BY cnt DESC LIMIT 1").fetchone()
    conn.close()
    return total, today_count, top_doing

class Viewer:
    def __init__(self, root):
        self.root = root
        self.root.title("📋 在干嘛 - 历史记录查看器")
        self.root.geometry("900x600")

        # 顶部：日期筛选 + 刷新按钮
        top_frame = ttk.Frame(root)
        top_frame.pack(pady=10, fill=tk.X)

        ttk.Label(top_frame, text="筛选日期 (YYYY-MM-DD):").pack(side=tk.LEFT, padx=5)
        self.date_var = tk.StringVar()
        date_entry = ttk.Entry(top_frame, textvariable=self.date_var, width=15)
        date_entry.pack(side=tk.LEFT, padx=5)
        ttk.Button(top_frame, text="筛选", command=self.refresh).pack(side=tk.LEFT, padx=5)
        ttk.Button(top_frame, text="显示全部", command=self.show_all).pack(side=tk.LEFT, padx=5)

        # 统计信息标签
        self.stats_label = ttk.Label(root, text="", font=("Arial", 10))
        self.stats_label.pack(pady=5)

        # 表格区域 (Treeview)
        columns = ("id", "timestamp", "doing", "next_plan", "screenshot")
        self.tree = ttk.Treeview(root, columns=columns, show="headings", height=20)
        self.tree.heading("id", text="ID")
        self.tree.heading("timestamp", text="时间")
        self.tree.heading("doing", text="在干嘛")
        self.tree.heading("next_plan", text="下一步")
        self.tree.heading("screenshot", text="截图路径")
        self.tree.column("id", width=50)
        self.tree.column("timestamp", width=180)
        self.tree.column("doing", width=200)
        self.tree.column("next_plan", width=200)
        self.tree.column("screenshot", width=250)

        scrollbar = ttk.Scrollbar(root, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10,0), pady=(0,10))
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0,10), pady=(0,10))

        # 底部：分页控制
        bottom_frame = ttk.Frame(root)
        bottom_frame.pack(pady=10)
        self.page = 0
        self.page_size = 100
        ttk.Button(bottom_frame, text="上一页", command=self.prev_page).pack(side=tk.LEFT, padx=5)
        ttk.Button(bottom_frame, text="下一页", command=self.next_page).pack(side=tk.LEFT, padx=5)
        self.page_label = ttk.Label(bottom_frame, text="第 1 页")
        self.page_label.pack(side=tk.LEFT, padx=10)

        # 初始化加载
        self.current_date_filter = None
        self.refresh()

    def refresh(self):
        date_str = self.date_var.get().strip()
        self.current_date_filter = date_str if date_str else None
        self.page = 0
        self.load_page()

    def show_all(self):
        self.date_var.set("")
        self.current_date_filter = None
        self.page = 0
        self.load_page()

    def load_page(self):
        records = get_records(limit=self.page_size, offset=self.page * self.page_size,
                              date_filter=self.current_date_filter)
        self.tree.delete(*self.tree.get_children())
        for r in records:
            # 缩短截图路径显示
            short_path = os.path.basename(r[4]) if r[4] and os.path.exists(r[4]) else r[4]
            self.tree.insert("", tk.END, values=(r[0], r[1], r[2], r[3], short_path))
        # 更新统计
        total, today_count, top_doing = get_stats(self.current_date_filter)
        top_text = f"最常做：{top_doing[0]} ({top_doing[1]}次)" if top_doing else "无记录"
        self.stats_label.config(text=f"📊 总记录数：{total} ｜ 当前筛选记录数：{len(records)} ｜ {top_text}")
        self.page_label.config(text=f"第 {self.page+1} 页")

    def prev_page(self):
        if self.page > 0:
            self.page -= 1
            self.load_page()

    def next_page(self):
        # 检查是否有下一页（通过尝试加载下一页判断）
        test = get_records(limit=1, offset=(self.page+1)*self.page_size, date_filter=self.current_date_filter)
        if test:
            self.page += 1
            self.load_page()
        else:
            messagebox.showinfo("提示", "已是最后一页")

if __name__ == "__main__":
    # 检查数据库是否存在
    if not os.path.exists(DB_FILE):
        messagebox.showerror("错误", f"数据库文件 {DB_FILE} 不存在，请先运行主程序记录数据。")
        exit(1)
    root = tk.Tk()
    app = Viewer(root)
    root.mainloop()