import shutil
import re
from datetime import timedelta
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from datetime import datetime
import os
import subprocess

import backup
from exporter import export_docx as _export_docx, export_pdf as _export_pdf

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
        ttk.Separator(tool_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(tool_frame, text="📄导出DOCX", command=self.export_docx).pack(side=tk.LEFT, padx=2)
        ttk.Button(tool_frame, text="📄压缩DOCX", command=self.export_docx_compressed).pack(side=tk.LEFT, padx=2)
        ttk.Button(tool_frame, text="📄导出PDF", command=self.export_pdf).pack(side=tk.LEFT, padx=2)
        ttk.Separator(tool_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(tool_frame, text="📦 新建基线", command=self.backup_create_base).pack(side=tk.LEFT, padx=2)
        ttk.Button(tool_frame, text="📦 增量备份", command=self.backup_create_incremental).pack(side=tk.LEFT, padx=2)
        ttk.Button(tool_frame, text="📋 备份历史", command=self.backup_show_history).pack(side=tk.LEFT, padx=2)

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

    # ---------- 导出（委托给 exporter 模块） ----------
    def export_docx(self):
        """导出当前筛选记录为 DOCX"""
        _export_docx(self.current_date_filter, self.current_keyword)

    def export_docx_compressed(self):
        """导出当前筛选记录为 DOCX（图片压缩模式）"""
        _export_docx(self.current_date_filter, self.current_keyword, compressed=True)

    def export_pdf(self):
        """导出当前筛选记录为 PDF"""
        _export_pdf(self.current_date_filter, self.current_keyword)

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


    # ========== 备份功能 ==========

    def backup_create_base(self):
        """创建基线备份（弹出模式选择对话框）"""
        dialog = tk.Toplevel(self.root)
        dialog.title("📦 新建基线备份")
        dialog.geometry("340x200")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="创建基线备份（全量快照）", font=("Arial", 12, "bold")).pack(pady=(0, 10))
        ttk.Separator(frame).pack(fill=tk.X, pady=4)

        mode_var = tk.StringVar(value="text")
        ttk.Radiobutton(frame, text="📝 纯文本（仅记录文字）", variable=mode_var, value="text").pack(anchor=tk.W, pady=4)
        ttk.Radiobutton(frame, text="📷 完整备份（含截图）", variable=mode_var, value="full").pack(anchor=tk.W, pady=4)

        btn_f = ttk.Frame(frame)
        btn_f.pack(fill=tk.X, pady=(12, 0))

        def do_backup():
            mode = mode_var.get()
            result = backup.create_base_backup(mode)
            if result:
                label = "纯文本" if mode == "text" else "完整"
                dialog.destroy()
                messagebox.showinfo(
                    "✅ 基线备份成功",
                    f"模式：{label}\n记录数：{result['record_count']} 条\n备份 ID：{result['id']}\n文件：{result['file']}"
                )
            else:
                messagebox.showwarning("提示", "没有记录可备份，或创建失败。")

        ttk.Button(btn_f, text="开始备份", command=do_backup, width=15).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_f, text="取消", command=dialog.destroy, width=15).pack(side=tk.LEFT, padx=5)

    def backup_create_incremental(self):
        """创建增量备份（选择基线）"""
        chains = backup.get_chains()
        if not chains:
            messagebox.showwarning("提示", "没有可用的基线备份。\n请先创建基线备份。")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("📦 选择基线创建增量备份")
        dialog.geometry("600x400")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text="选择一条基线，在其基础上创建增量备份：", font=("Arial", 10)).pack(pady=(10, 5))

        frame = ttk.Frame(dialog)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        columns = ("id", "mode", "created", "records", "chain_len")
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=12, selectmode="browse")
        tree.heading("id", text="基线 ID")
        tree.heading("mode", text="模式")
        tree.heading("created", text="创建时间")
        tree.heading("records", text="记录数")
        tree.heading("chain_len", text="链长度")
        tree.column("id", width=200)
        tree.column("mode", width=80)
        tree.column("created", width=160)
        tree.column("records", width=80)
        tree.column("chain_len", width=80)

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        for c in chains:
            b = c["base"]
            tree.insert("", tk.END, values=(
                b["id"], "纯文本" if b["mode"] == "text" else "完整",
                b["created_at"], b["record_count"],
                f"1 → {c['length']}"
            ))

        btn_f = ttk.Frame(dialog)
        btn_f.pack(fill=tk.X, pady=10, padx=10)

        def do_incremental():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("提示", "请先选择一条基线。")
                return
            item = tree.item(sel[0])
            base_id = item["values"][0]
            result = backup.create_incremental_backup(base_id)
            if result:
                dialog.destroy()
                messagebox.showinfo(
                    "✅ 增量备份成功",
                    f"新增记录数：{result['record_count']} 条\n"
                    f"备份 ID：{result['id']}\n"
                    f"基于：{result['parent_id']}"
                )
            else:
                messagebox.showwarning("提示", "没有新增记录，跳过增量备份。")

        ttk.Button(btn_f, text="创建增量备份", command=do_incremental, width=20).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_f, text="取消", command=dialog.destroy, width=15).pack(side=tk.LEFT, padx=5)

    def backup_show_history(self):
        """打开备份历史管理窗口"""
        BackupHistoryDialog(self.root)


class BackupHistoryDialog:
    """备份历史管理窗口 — 显示所有备份链，支持查看内容和删除"""
    def __init__(self, master):
        self.master = master
        self.win = tk.Toplevel(master)
        self.win.title("📋 备份历史")
        self.win.geometry("900x550")

        top = ttk.Frame(self.win)
        top.pack(pady=8, fill=tk.X)
        ttk.Label(top, text="所有备份链", font=("Arial", 12, "bold")).pack(side=tk.LEFT, padx=10)
        ttk.Button(top, text="🔄 刷新", command=self.load_data).pack(side=tk.RIGHT, padx=5)
        ttk.Button(top, text="查看内容", command=self.view_content).pack(side=tk.RIGHT, padx=5)
        ttk.Button(top, text="删除", command=self.delete_selected).pack(side=tk.RIGHT, padx=5)

        columns = ("type", "id", "mode", "created", "records", "file")
        self.tree = ttk.Treeview(self.win, columns=columns, show="tree headings", height=20, selectmode="browse")
        for col, label in [("type", "类型"), ("id", "ID"), ("mode", "模式"), ("created", "创建时间"), ("records", "记录数"), ("file", "文件")]:
            self.tree.heading(col, text=label)
        self.tree.column("type", width=80)
        self.tree.column("id", width=200)
        self.tree.column("mode", width=70)
        self.tree.column("created", width=170)
        self.tree.column("records", width=70)
        self.tree.column("file", width=250)

        scrollbar = ttk.Scrollbar(self.win, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10,0), pady=(0,10))
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0,10), pady=(0,10))

        self.load_data()

    def load_data(self):
        self.tree.delete(*self.tree.get_children())
        chains = backup.get_chains()
        for c in chains:
            base = c["base"]
            parent_iid = self.tree.insert("", tk.END, values=(
                "📦 基线", base["id"],
                "纯文本" if base["mode"] == "text" else "完整",
                base["created_at"], base["record_count"], base["file"]
            ), open=True)
            for inc in c.get("chain", [])[1:]:
                self.tree.insert(parent_iid, tk.END, values=(
                    "➕ 增量", inc["id"],
                    "-", inc["created_at"], inc["record_count"], inc["file"]
                ))
        if not chains:
            self.tree.insert("", tk.END, values=("-", "（暂无备份）", "", "", "", ""))

    def get_selected_entry_id(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择一条备份。")
            return None
        values = self.tree.item(sel[0], "values")
        if not values or len(values) < 2:
            return None
        eid = values[1]
        if eid and (eid.startswith("base_") or eid.startswith("inc_")):
            return eid
        return None

    def view_content(self):
        eid = self.get_selected_entry_id()
        if not eid:
            return
        detail = backup.get_backup_detail(eid)
        if not detail:
            messagebox.showerror("错误", "备份条目不存在。")
            return

        records = backup.get_all_records_in_chain_up_to(eid)
        if not records:
            messagebox.showinfo("内容", "该备份无记录数据。")
            return

        dlg = tk.Toplevel(self.win)
        dlg.title(f"📋 备份内容 — {eid}")
        dlg.geometry("700x400")

        info = ttk.Label(dlg, text=f"记录数：{len(records)} 条 | 模式：{'纯文本' if detail['mode']=='text' else '完整'} | 文件：{detail['file']}")
        info.pack(pady=5)

        txt = tk.Text(dlg, wrap=tk.WORD, font=("Consolas", 9))
        txt.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        for i, r in enumerate(records, 1):
            txt.insert(tk.END, f"#{i}  ID:{r['id']}  {r['timestamp']}\n")
            txt.insert(tk.END, f"    在干嘛：{r['doing']}\n")
            txt.insert(tk.END, f"    下一步：{r['next_plan']}\n")
            sp = r.get("screenshot_path", "")
            if sp:
                txt.insert(tk.END, f"    截图：{os.path.basename(sp) if os.path.exists(sp) else sp}\n")
            txt.insert(tk.END, f"    {'─' * 50}\n")

        txt.config(state=tk.DISABLED)
        scrollbar = ttk.Scrollbar(dlg, orient=tk.VERTICAL, command=txt.yview)
        txt.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=5, padx=(0,10))

        ttk.Button(dlg, text="关闭", command=dlg.destroy, width=15).pack(pady=8)

    def delete_selected(self):
        eid = self.get_selected_entry_id()
        if not eid:
            return
        detail = backup.get_backup_detail(eid)
        if not detail:
            return
        if detail.get("child_id"):
            messagebox.showwarning("无法删除", "该备份有后继增量备份，请先删除子节点。")
            return
        if not messagebox.askyesno("确认删除", f"确定要删除备份「{eid}」？\n此操作不可恢复！"):
            return
        if backup.delete_backup(eid):
            messagebox.showinfo("成功", f"已删除备份：{eid}")
            self.load_data()
        else:
            messagebox.showerror("错误", "删除失败，请检查是否有子节点未删除。")


if __name__ == "__main__":
    if not os.path.exists(DB_FILE):
        messagebox.showerror("错误", f"数据库文件 {DB_FILE} 不存在，请先运行主程序记录数据。")
        exit(1)
    backup.init_backup_dir()
    root = tk.Tk()
    app = Viewer(root)
    root.mainloop()