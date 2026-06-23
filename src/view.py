import shutil
import re
from datetime import timedelta
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import datetime
import os
import subprocess

DB_FILE = "whatido.db"

# ---------- 数据库操作函数 ----------
def get_records(limit=100, offset=0, date_filter=None, keyword=None):
    """获取记录，支持日期过滤、关键词搜索、分页"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    query = "SELECT id, timestamp, doing, next_plan, screenshot_path FROM records WHERE 1=1"
    params = []
    if date_filter:
        query += " AND date(timestamp) = ?"
        params.append(date_filter)
    if keyword:
        query += " AND (doing LIKE ? OR next_plan LIKE ?)"
        like = f"%{keyword}%"
        params.extend([like, like])
    query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return rows

def get_stats(date_filter=None, keyword=None):
    """获取统计信息（支持过滤条件）"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # 总记录数（符合过滤条件的）
    count_query = "SELECT COUNT(*) FROM records WHERE 1=1"
    count_params = []
    if date_filter:
        count_query += " AND date(timestamp) = ?"
        count_params.append(date_filter)
    if keyword:
        count_query += " AND (doing LIKE ? OR next_plan LIKE ?)"
        like = f"%{keyword}%"
        count_params.extend([like, like])
    total = c.execute(count_query, count_params).fetchone()[0]

    # 今日记录数（或指定日期）
    if date_filter:
        today_count = c.execute("SELECT COUNT(*) FROM records WHERE date(timestamp) = ?", (date_filter,)).fetchone()[0]
    else:
        today = datetime.now().strftime("%Y-%m-%d")
        today_count = c.execute("SELECT COUNT(*) FROM records WHERE date(timestamp) = ?", (today,)).fetchone()[0]

    # 最常做的活动（同样受过滤条件影响）
    top_query = "SELECT doing, COUNT(*) as cnt FROM records WHERE 1=1"
    top_params = []
    if date_filter:
        top_query += " AND date(timestamp) = ?"
        top_params.append(date_filter)
    if keyword:
        top_query += " AND (doing LIKE ? OR next_plan LIKE ?)"
        top_params.extend([like, like])
    top_query += " GROUP BY doing ORDER BY cnt DESC LIMIT 1"
    top_doing = c.execute(top_query, top_params).fetchone()
    conn.close()
    return total, today_count, top_doing

def add_record(doing, next_plan):
    """新增记录（不截图）"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT INTO records (timestamp, doing, next_plan, screenshot_path) VALUES (?, ?, ?, ?)",
        (datetime.now().isoformat(), doing, next_plan, "")
    )
    conn.commit()
    conn.close()

def update_record(record_id, doing, next_plan):
    """更新记录"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE records SET doing=?, next_plan=? WHERE id=?", (doing, next_plan, record_id))
    conn.commit()
    conn.close()

def delete_records(ids):
    """删除记录，截图移至回收站（screenshots/trash/），并标记删除时间"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # 获取截图路径
    placeholders = ','.join('?' * len(ids))
    c.execute(f"SELECT id, screenshot_path FROM records WHERE id IN ({placeholders})", ids)
    rows = c.fetchall()

    # 创建回收站目录
    trash_dir = os.path.join("screenshots", "trash")
    os.makedirs(trash_dir, exist_ok=True)

    for record_id, path in rows:
        if path and os.path.exists(path):
            # 构造新文件名：原文件名_del_当前时间戳.扩展名
            base, ext = os.path.splitext(os.path.basename(path))
            del_time = datetime.now().strftime("%Y%m%d_%H%M%S")
            new_name = f"{base}_del_{del_time}{ext}"
            new_path = os.path.join(trash_dir, new_name)
            try:
                shutil.move(path, new_path)
                print(f"截图移至回收站：{new_path}")
            except Exception as e:
                print(f"⚠️ 移动截图失败 {path}：{e}")
        elif path:
            print(f"截图文件不存在：{path}")

    # 删除数据库记录
    c.execute(f"DELETE FROM records WHERE id IN ({placeholders})", ids)
    conn.commit()
    conn.close()

def clean_trash():
    """清理 trash 目录中超过 30 天的截图文件"""
    trash_dir = os.path.join("screenshots", "trash")
    if not os.path.exists(trash_dir):
        return
    now = datetime.now()
    for filename in os.listdir(trash_dir):
        filepath = os.path.join(trash_dir, filename)
        # 文件名格式：原名称_del_YYYYMMDD_HHMMSS.ext
        match = re.search(r'_del_(\d{8}_\d{6})\.', filename)
        if match:
            del_time_str = match.group(1)  # 例如 "20250618_153000"
            try:
                del_dt = datetime.strptime(del_time_str, "%Y%m%d_%H%M%S")
                if (now - del_dt).days >= 30:
                    os.remove(filepath)
                    print(f"已清理过期回收文件：{filename}")
            except ValueError:
                pass  # 日期解析失败，忽略
        # 如果没有删除时间标记，则保留（可能是手动放入的）


# ---------- 主界面 ----------
class Viewer:
    def __init__(self, root):
        self.root = root
        self.root.title("📋 在干嘛 - 历史记录管理")
        self.root.geometry("950x650")

        self.path_map = {}
        self.current_date_filter = None
        self.current_keyword = None
        self.page = 0
        self.page_size = 100

        # 顶部搜索 + 筛选
        top_frame = ttk.Frame(root)
        top_frame.pack(pady=10, fill=tk.X)

        ttk.Label(top_frame, text="日期 (YYYY-MM-DD):").pack(side=tk.LEFT, padx=5)
        self.date_var = tk.StringVar()
        date_entry = ttk.Entry(top_frame, textvariable=self.date_var, width=15)
        date_entry.pack(side=tk.LEFT, padx=5)

        ttk.Label(top_frame, text="关键词:").pack(side=tk.LEFT, padx=5)
        self.keyword_var = tk.StringVar()
        keyword_entry = ttk.Entry(top_frame, textvariable=self.keyword_var, width=15)
        keyword_entry.pack(side=tk.LEFT, padx=5)

        ttk.Button(top_frame, text="搜索", command=self.refresh).pack(side=tk.LEFT, padx=5)
        ttk.Button(top_frame, text="重置", command=self.reset_filters).pack(side=tk.LEFT, padx=5)

        # 操作工具栏
        tool_frame = ttk.Frame(root)
        tool_frame.pack(pady=5, fill=tk.X)
        ttk.Button(tool_frame, text="全选", command=self.select_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(tool_frame, text="取消全选", command=self.deselect_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(tool_frame, text="新增", command=self.add_record_dialog).pack(side=tk.LEFT, padx=2)
        ttk.Button(tool_frame, text="编辑", command=self.edit_record).pack(side=tk.LEFT, padx=2)
        ttk.Button(tool_frame, text="删除选中", command=self.delete_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(tool_frame, text="📝 笔记", command=self.open_notes_viewer).pack(side=tk.LEFT, padx=2)

        # 统计信息
        self.stats_label = ttk.Label(root, text="", font=("Arial", 10))
        self.stats_label.pack(pady=5)

        # 表格
        columns = ("id", "timestamp", "doing", "next_plan", "screenshot")
        self.tree = ttk.Treeview(root, columns=columns, show="headings", height=20, selectmode='extended')
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

        self.tree.bind("<Double-1>", self.on_double_click)

        # 底部翻页
        bottom_frame = ttk.Frame(root)
        bottom_frame.pack(pady=10)
        ttk.Button(bottom_frame, text="上一页", command=self.prev_page).pack(side=tk.LEFT, padx=5)
        ttk.Button(bottom_frame, text="下一页", command=self.next_page).pack(side=tk.LEFT, padx=5)
        self.page_label = ttk.Label(bottom_frame, text="第 1 页")
        self.page_label.pack(side=tk.LEFT, padx=10)

        self.refresh()
        clean_trash() #清理回收站内超过30天的记录

    # ---------- 数据加载 ----------
    def refresh(self):
        date_str = self.date_var.get().strip()
        self.current_date_filter = date_str if date_str else None
        keyword = self.keyword_var.get().strip()
        self.current_keyword = keyword if keyword else None
        self.page = 0
        self.load_page()

    def reset_filters(self):
        self.date_var.set("")
        self.keyword_var.set("")
        self.current_date_filter = None
        self.current_keyword = None
        self.page = 0
        self.load_page()

    def load_page(self):
        self.path_map.clear()
        self.tree.delete(*self.tree.get_children())

        records = get_records(
            limit=self.page_size,
            offset=self.page * self.page_size,
            date_filter=self.current_date_filter,
            keyword=self.current_keyword
        )

        for r in records:
            full_path = r[4]
            display_path = os.path.basename(full_path) if full_path and os.path.exists(full_path) else full_path
            item_id = self.tree.insert("", tk.END, values=(r[0], r[1], r[2], r[3], display_path))
            self.path_map[item_id] = full_path

        # 统计
        total, today_count, top_doing = get_stats(self.current_date_filter, self.current_keyword)
        top_text = f"最常做：{top_doing[0]} ({top_doing[1]}次)" if top_doing else "无记录"
        self.stats_label.config(text=f"📊 总记录数：{total} ｜ 今日记录数：{today_count} ｜ {top_text}")
        self.page_label.config(text=f"第 {self.page+1} 页")

    def prev_page(self):
        if self.page > 0:
            self.page -= 1
            self.load_page()

    def next_page(self):
        # 检查是否有下一页（取1条测试）
        test = get_records(limit=1, offset=(self.page+1)*self.page_size,
                           date_filter=self.current_date_filter, keyword=self.current_keyword)
        if test:
            self.page += 1
            self.load_page()
        else:
            messagebox.showinfo("提示", "已是最后一页")

    # ---------- 选择操作 ----------
    def select_all(self):
        items = self.tree.get_children()
        self.tree.selection_set(items)

    def deselect_all(self):
        self.tree.selection_remove(self.tree.selection())

    def get_selected_ids(self):
        """返回选中记录的ID列表"""
        selected_items = self.tree.selection()
        ids = []
        for item in selected_items:
            values = self.tree.item(item, 'values')
            if values:
                ids.append(int(values[0]))  # ID 在第一列
        return ids

    # ---------- 新增 ----------
    def add_record_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("新增记录")
        dialog.geometry("300x150")
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="在干嘛？").pack(pady=5)
        doing_entry = tk.Entry(dialog, width=30)
        doing_entry.pack(pady=5)

        tk.Label(dialog, text="下一步？").pack(pady=5)
        next_entry = tk.Entry(dialog, width=30)
        next_entry.pack(pady=5)

        def submit():
            doing = doing_entry.get().strip() or "未填写"
            next_plan = next_entry.get().strip() or "未填写"
            add_record(doing, next_plan)
            dialog.destroy()
            self.refresh()
            messagebox.showinfo("成功", "记录已添加")

        tk.Button(dialog, text="确定", command=submit).pack(pady=10)

    # ---------- 编辑 ----------
    def edit_record(self):
        ids = self.get_selected_ids()
        if len(ids) != 1:
            messagebox.showwarning("提示", "请选择且仅选择一条记录进行编辑")
            return
        record_id = ids[0]
        # 获取当前数据
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT doing, next_plan FROM records WHERE id=?", (record_id,))
        row = c.fetchone()
        conn.close()
        if not row:
            messagebox.showerror("错误", "记录不存在")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("编辑记录")
        dialog.geometry("300x150")
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="在干嘛？").pack(pady=5)
        doing_entry = tk.Entry(dialog, width=30)
        doing_entry.insert(0, row[0])
        doing_entry.pack(pady=5)

        tk.Label(dialog, text="下一步？").pack(pady=5)
        next_entry = tk.Entry(dialog, width=30)
        next_entry.insert(0, row[1])
        next_entry.pack(pady=5)

        def submit():
            doing = doing_entry.get().strip() or "未填写"
            next_plan = next_entry.get().strip() or "未填写"
            update_record(record_id, doing, next_plan)
            dialog.destroy()
            self.refresh()
            messagebox.showinfo("成功", "记录已更新")

        tk.Button(dialog, text="确定", command=submit).pack(pady=10)

    # ---------- 删除 ----------
    def delete_selected(self):
        ids = self.get_selected_ids()
        if not ids:
            messagebox.showwarning("提示", "请先选择要删除的记录")
            return
        if messagebox.askyesno("确认删除", f"确定要删除选中的 {len(ids)} 条记录吗？\n此操作不可撤销！"):
            delete_records(ids)
            self.refresh()
            messagebox.showinfo("成功", f"已删除 {len(ids)} 条记录")

    # ---------- 双击查看截图 ----------
    def on_double_click(self, event):
        selected = self.tree.selection()
        if not selected:
            return
        item = selected[0]
        full_path = self.path_map.get(item)
        if not full_path:
            messagebox.showwarning("提示", "该记录没有截图信息。")
            return
        if not os.path.exists(full_path):
            messagebox.showerror("错误", f"截图文件不存在：\n{full_path}")
            return
        try:
            os.startfile(full_path)
        except Exception as e:
            messagebox.showerror("打开失败", f"无法打开截图：{e}")

    # ---------- 笔记视图 ----------
    def open_notes_viewer(self):
        """打开笔记查看器窗口"""
        # 确保 notes 表存在
        from note import init_notes_db
        init_notes_db()
        NotesViewer(self.root)


# ═══════════════════════════════════════════════
#  笔记查看器
# ═══════════════════════════════════════════════
class NotesViewer:
    """笔记浏览窗口，支持标签/关键词/日期筛选"""

    def __init__(self, master):
        self.master = master
        self.win = tk.Toplevel(master)
        self.win.title("📝 WAYD 笔记查看器")
        self.win.geometry("860x600")

        self.current_tag = None
        self.current_keyword = None
        self.current_date = None
        self.page = 0
        self.page_size = 100

        # ── 顶部筛选栏 ──
        top_frame = ttk.Frame(self.win)
        top_frame.pack(pady=8, fill=tk.X)

        ttk.Label(top_frame, text="标签:").pack(side=tk.LEFT, padx=5)
        self.tag_var = tk.StringVar()
        tag_entry = ttk.Entry(top_frame, textvariable=self.tag_var, width=12)
        tag_entry.pack(side=tk.LEFT, padx=5)

        ttk.Label(top_frame, text="关键词:").pack(side=tk.LEFT, padx=5)
        self.keyword_var = tk.StringVar()
        kw_entry = ttk.Entry(top_frame, textvariable=self.keyword_var, width=15)
        kw_entry.pack(side=tk.LEFT, padx=5)

        ttk.Label(top_frame, text="日期:").pack(side=tk.LEFT, padx=5)
        self.date_var = tk.StringVar()
        date_entry = ttk.Entry(top_frame, textvariable=self.date_var, width=12)
        date_entry.pack(side=tk.LEFT, padx=5)

        ttk.Button(top_frame, text="搜索", command=self.refresh, width=6).pack(side=tk.LEFT, padx=3)
        ttk.Button(top_frame, text="重置", command=self.reset_filters, width=6).pack(side=tk.LEFT, padx=3)

        # ── 操作工具栏 ──
        tool_frame = ttk.Frame(self.win)
        tool_frame.pack(pady=4, fill=tk.X)
        ttk.Button(tool_frame, text="新增笔记", command=self.add_note_dialog).pack(side=tk.LEFT, padx=2)
        ttk.Button(tool_frame, text="删除选中", command=self.delete_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(tool_frame, text="统计", command=self.show_stats).pack(side=tk.LEFT, padx=2)

        # ── 统计信息 ──
        self.stats_label = ttk.Label(self.win, text="", font=("Arial", 10))
        self.stats_label.pack(pady=4)

        # ── 表格 ──
        columns = ("id", "timestamp", "step_sequence", "content", "tags")
        self.tree = ttk.Treeview(self.win, columns=columns, show="headings", height=18, selectmode="extended")
        self.tree.heading("id", text="ID")
        self.tree.heading("timestamp", text="时间")
        self.tree.heading("step_sequence", text="步骤")
        self.tree.heading("content", text="笔记内容")
        self.tree.heading("tags", text="标签")

        self.tree.column("id", width=50, anchor=tk.CENTER)
        self.tree.column("timestamp", width=160)
        self.tree.column("step_sequence", width=80, anchor=tk.CENTER)
        self.tree.column("content", width=340)
        self.tree.column("tags", width=120, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(self.win, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0), pady=(0, 8))
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 10), pady=(0, 8))

        # ── 底部翻页 ──
        bottom_frame = ttk.Frame(self.win)
        bottom_frame.pack(pady=6)
        ttk.Button(bottom_frame, text="上一页", command=self.prev_page).pack(side=tk.LEFT, padx=5)
        self.page_label = ttk.Label(bottom_frame, text="第 1 页")
        self.page_label.pack(side=tk.LEFT, padx=10)
        ttk.Button(bottom_frame, text="下一页", command=self.next_page).pack(side=tk.LEFT, padx=5)

        self.load_page()

    # ── 数据库操作 ──
    def _get_notes(self):
        """从 note 模块查询笔记"""
        from note import get_notes, get_note_stats
        rows = get_notes(
            tag=self.current_tag,
            keyword=self.current_keyword,
            date_str=self.current_date,
            limit=self.page_size,
            offset=self.page * self.page_size,
        )
        total, tag_stats = get_note_stats(tag=self.current_tag, date_str=self.current_date)
        return rows, total, tag_stats

    # ── 加载 / 刷新 ──
    def refresh(self):
        self.current_tag = self.tag_var.get().strip() or None
        self.current_keyword = self.keyword_var.get().strip() or None
        self.current_date = self.date_var.get().strip() or None
        self.page = 0
        self.load_page()

    def reset_filters(self):
        self.tag_var.set("")
        self.keyword_var.set("")
        self.date_var.set("")
        self.current_tag = None
        self.current_keyword = None
        self.current_date = None
        self.page = 0
        self.load_page()

    def load_page(self):
        self.tree.delete(*self.tree.get_children())
        rows, total, tag_stats = self._get_notes()

        for r in rows:
            self.tree.insert("", tk.END, values=r)

        # 更新统计
        parts = [f"📊 总笔记数：{total}"]
        if tag_stats and not self.current_tag:
            top_tags = ", ".join(f"[{t}]{c}" for t, c in tag_stats[:3] if t)
            if top_tags:
                parts.append(f"热门标签：{top_tags}")
        self.stats_label.config(text="  |  ".join(parts))
        self.page_label.config(text=f"第 {self.page + 1} 页")

    def prev_page(self):
        if self.page > 0:
            self.page -= 1
            self.load_page()

    def next_page(self):
        from note import get_notes
        test = get_notes(
            tag=self.current_tag, keyword=self.current_keyword,
            date_str=self.current_date, limit=1,
            offset=(self.page + 1) * self.page_size,
        )
        if test:
            self.page += 1
            self.load_page()
        else:
            messagebox.showinfo("提示", "已是最后一页")

    # ── 获取选中 ID ──
    def get_selected_ids(self):
        ids = []
        for item in self.tree.selection():
            values = self.tree.item(item, "values")
            if values:
                ids.append(int(values[0]))
        return ids

    # ── 新增笔记 ──
    def add_note_dialog(self):
        dialog = tk.Toplevel(self.win)
        dialog.title("新增笔记")
        dialog.geometry("380x200")
        dialog.transient(self.win)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="步骤序列:").grid(row=0, column=0, sticky=tk.W, pady=4)
        seq_entry = ttk.Entry(frame, width=30)
        seq_entry.grid(row=0, column=1, pady=4, padx=5)
        seq_entry.focus()

        ttk.Label(frame, text="笔记内容:").grid(row=1, column=0, sticky=tk.W, pady=4)
        content_entry = ttk.Entry(frame, width=30)
        content_entry.grid(row=1, column=1, pady=4, padx=5)

        ttk.Label(frame, text="标签:").grid(row=2, column=0, sticky=tk.W, pady=4)
        tag_entry = ttk.Entry(frame, width=30)
        tag_entry.grid(row=2, column=1, pady=4, padx=5)
        tag_entry.insert(0, "x")  # 默认错题集标签

        def submit():
            seq = seq_entry.get().strip()
            content = content_entry.get().strip()
            tag = tag_entry.get().strip()
            if not content:
                messagebox.showwarning("提示", "笔记内容不能为空")
                return
            from note import add_note
            note_id = add_note(seq, content, tag)
            dialog.destroy()
            self.refresh()
            messagebox.showinfo("成功", f"笔记已添加 [ID={note_id}]")

        btn_f = ttk.Frame(frame)
        btn_f.grid(row=3, column=0, columnspan=2, pady=12)
        ttk.Button(btn_f, text="确定", command=submit, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_f, text="取消", command=dialog.destroy, width=10).pack(side=tk.LEFT, padx=5)

    # ── 删除笔记 ──
    def delete_selected(self):
        ids = self.get_selected_ids()
        if not ids:
            messagebox.showwarning("提示", "请先选择要删除的笔记")
            return
        if messagebox.askyesno("确认删除", f"确定要删除选中的 {len(ids)} 条笔记吗？"):
            from note import delete_notes
            deleted = delete_notes(ids)
            self.refresh()
            messagebox.showinfo("成功", f"已删除 {deleted} 条笔记")

    # ── 统计弹窗 ──
    def show_stats(self):
        from note import get_note_stats
        total, tag_stats = get_note_stats()
        msg = [f"📊 总笔记数：{total}"]
        if tag_stats:
            msg.append("\n\n标签分布：")
            for tag, cnt in tag_stats:
                tag_display = tag if tag else "(无标签)"
                msg.append(f"  [{tag_display}] {cnt} 条")
        messagebox.showinfo("笔记统计", "\n".join(msg), parent=self.win)
    if not os.path.exists(DB_FILE):
        messagebox.showerror("错误", f"数据库文件 {DB_FILE} 不存在，请先运行主程序记录数据。")
        exit(1)
    root = tk.Tk()
    app = Viewer(root)
    root.mainloop()