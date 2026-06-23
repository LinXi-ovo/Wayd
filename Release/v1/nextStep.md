好的，回收站添加恢复功能是很有必要的。我们重新设计删除机制：**记录不物理删除，而是标记为“已删除”**，截图移动到回收站文件夹。这样恢复时，记录内容完整，截图也能找回。

---

### 📦 改动方案

1. **数据库增加字段**：`deleted`（0/1）和 `deleted_at`（删除时间）。
2. **删除操作**：标记 `deleted=1`，记录当前时间，并将截图移到 `screenshots/trash/`（**保持原文件名**）。
3. **恢复操作**：将 `deleted` 改回 0，清空 `deleted_at`，截图从回收站移回原目录。
4. **彻底删除（清理）**：物理删除记录和截图文件（或由定时清理任务处理超过30天的已删除记录）。
5. **回收站界面**：专门显示 `deleted=1` 的记录，提供“恢复”和“彻底删除”按钮。
6. **自动清理**：启动时检测 `deleted=1` 且 `deleted_at` 超过30天的记录，自动彻底删除（包括截图）。

---

### 🔧 具体代码修改（基于您之前的 `view.py`）

#### 1. 数据库升级函数（添加到 `view.py` 开头）

```python
def upgrade_db():
    """升级数据库，增加 deleted 和 deleted_at 字段"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # 检查列是否存在
    c.execute("PRAGMA table_info(records)")
    columns = [col[1] for col in c.fetchall()]
    if "deleted" not in columns:
        c.execute("ALTER TABLE records ADD COLUMN deleted INTEGER DEFAULT 0")
    if "deleted_at" not in columns:
        c.execute("ALTER TABLE records ADD COLUMN deleted_at TEXT")
    conn.commit()
    conn.close()
```

在 `__main__` 中调用一次：
```python
if __name__ == "__main__":
    upgrade_db()
    ...
```

> 同样，`main.py` 也应添加此升级逻辑，确保主程序也能兼容新结构。

---

#### 2. 修改删除函数（标记删除 + 移动截图）

替换原来的 `delete_records`：

```python
def delete_records(ids):
    """标记删除记录，截图移至回收站"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # 获取待删除记录的截图路径
    placeholders = ','.join('?' * len(ids))
    c.execute(f"SELECT id, screenshot_path FROM records WHERE id IN ({placeholders})", ids)
    rows = c.fetchall()

    # 创建回收站目录
    trash_dir = os.path.join("screenshots", "trash")
    os.makedirs(trash_dir, exist_ok=True)

    for record_id, path in rows:
        # 移动截图到回收站（保持原文件名）
        if path and os.path.exists(path):
            new_path = os.path.join(trash_dir, os.path.basename(path))
            # 如果回收站已有同名文件，添加序号（但理论上不会，因为截图唯一）
            counter = 1
            while os.path.exists(new_path):
                name, ext = os.path.splitext(os.path.basename(path))
                new_path = os.path.join(trash_dir, f"{name}_{counter}{ext}")
                counter += 1
            try:
                shutil.move(path, new_path)
                print(f"截图移至回收站：{new_path}")
                # 更新数据库中的截图路径为回收站路径（可选，便于恢复时找回）
                c.execute("UPDATE records SET screenshot_path=? WHERE id=?", (new_path, record_id))
            except Exception as e:
                print(f"移动截图失败：{e}")
                # 如果移动失败，仍标记删除，但截图留在原地（可能会丢失，由用户处理）
        elif path:
            print(f"截图不存在：{path}")

    # 标记删除
    now = datetime.now().isoformat()
    c.executemany(f"UPDATE records SET deleted=1, deleted_at=? WHERE id=?", [(now, id) for id in ids])
    conn.commit()
    conn.close()
```

---

#### 3. 修改查询函数，默认只显示未删除的记录

原有的 `get_records` 和 `get_stats` 需要增加 `WHERE deleted=0` 条件，避免显示已删除记录。

例如 `get_records` 中：
```python
query = "SELECT id, timestamp, doing, next_plan, screenshot_path FROM records WHERE deleted=0"
```
其他过滤条件附加 `AND ...`。

同样，`get_stats` 中的计数也要加上 `WHERE deleted=0`。

（如果要用独立回收站窗口，可以单独写一个查询函数，专查 `deleted=1` 的记录。）

---

#### 4. 新增回收站窗口类 `TrashViewer`

这是一个独立的 Toplevel 窗口，显示所有 `deleted=1` 的记录，并提供“恢复”和“彻底删除”按钮。

```python
class TrashViewer:
    def __init__(self, master):
        self.master = master
        self.win = tk.Toplevel(master)
        self.win.title("🗑️ 回收站")
        self.win.geometry("850x500")

        # 标题和按钮
        top_frame = ttk.Frame(self.win)
        top_frame.pack(pady=10, fill=tk.X)
        ttk.Label(top_frame, text="回收站中的记录（可恢复或彻底删除）", font=("Arial", 12)).pack(side=tk.LEFT, padx=10)
        ttk.Button(top_frame, text="恢复选中", command=self.restore_selected).pack(side=tk.RIGHT, padx=5)
        ttk.Button(top_frame, text="彻底删除选中", command=self.permanent_delete_selected).pack(side=tk.RIGHT, padx=5)
        ttk.Button(top_frame, text="刷新", command=self.load_trash).pack(side=tk.RIGHT, padx=5)

        # 表格
        columns = ("id", "timestamp", "doing", "next_plan", "screenshot", "deleted_at")
        self.tree = ttk.Treeview(self.win, columns=columns, show="headings", height=15, selectmode='extended')
        self.tree.heading("id", text="ID")
        self.tree.heading("timestamp", text="原时间")
        self.tree.heading("doing", text="在干嘛")
        self.tree.heading("next_plan", text="下一步")
        self.tree.heading("screenshot", text="截图路径（回收站）")
        self.tree.heading("deleted_at", text="删除时间")
        self.tree.column("id", width=50)
        self.tree.column("timestamp", width=160)
        self.tree.column("doing", width=180)
        self.tree.column("next_plan", width=180)
        self.tree.column("screenshot", width=200)
        self.tree.column("deleted_at", width=160)

        scrollbar = ttk.Scrollbar(self.win, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10,0), pady=(0,10))
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0,10), pady=(0,10))

        self.load_trash()

    def load_trash(self):
        """加载回收站记录（deleted=1）"""
        self.tree.delete(*self.tree.get_children())
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT id, timestamp, doing, next_plan, screenshot_path, deleted_at FROM records WHERE deleted=1 ORDER BY deleted_at DESC")
        rows = c.fetchall()
        conn.close()
        for r in rows:
            # 只显示文件名
            display_path = os.path.basename(r[4]) if r[4] else ""
            self.tree.insert("", tk.END, values=(r[0], r[1], r[2], r[3], display_path, r[5]))

    def get_selected_ids(self):
        items = self.tree.selection()
        ids = []
        for item in items:
            values = self.tree.item(item, 'values')
            if values:
                ids.append(int(values[0]))
        return ids

    def restore_selected(self):
        ids = self.get_selected_ids()
        if not ids:
            messagebox.showwarning("提示", "请选择要恢复的记录")
            return
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        placeholders = ','.join('?' * len(ids))
        # 获取这些记录的截图路径（回收站路径）
        c.execute(f"SELECT id, screenshot_path FROM records WHERE id IN ({placeholders})", ids)
        rows = c.fetchall()
        for record_id, path in rows:
            if path and os.path.exists(path):
                # 移回原目录（假设原路径是 screenshots/原文件名）
                original_dir = "screenshots"
                basename = os.path.basename(path)
                original_path = os.path.join(original_dir, basename)
                # 如果原位置已有同名文件，添加序号
                counter = 1
                while os.path.exists(original_path):
                    name, ext = os.path.splitext(basename)
                    original_path = os.path.join(original_dir, f"{name}_{counter}{ext}")
                    counter += 1
                try:
                    shutil.move(path, original_path)
                    # 更新数据库中的路径
                    c.execute("UPDATE records SET screenshot_path=? WHERE id=?", (original_path, record_id))
                except Exception as e:
                    print(f"恢复截图失败：{e}")
                    continue
            else:
                print(f"截图不存在或路径为空：{path}")
        # 将记录标记为未删除
        c.executemany(f"UPDATE records SET deleted=0, deleted_at=NULL WHERE id=?", [(id,) for id in ids])
        conn.commit()
        conn.close()
        self.load_trash()
        messagebox.showinfo("成功", f"已恢复 {len(ids)} 条记录")

    def permanent_delete_selected(self):
        ids = self.get_selected_ids()
        if not ids:
            messagebox.showwarning("提示", "请选择要彻底删除的记录")
            return
        if not messagebox.askyesno("确认彻底删除", f"将彻底删除选中的 {len(ids)} 条记录及其截图文件，不可恢复！\n确定吗？"):
            return
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        placeholders = ','.join('?' * len(ids))
        # 获取截图路径
        c.execute(f"SELECT screenshot_path FROM records WHERE id IN ({placeholders})", ids)
        paths = c.fetchall()
        for (path,) in paths:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                    print(f"已删除截图：{path}")
                except Exception as e:
                    print(f"删除截图失败：{e}")
        # 物理删除记录
        c.execute(f"DELETE FROM records WHERE id IN ({placeholders})", ids)
        conn.commit()
        conn.close()
        self.load_trash()
        messagebox.showinfo("成功", f"已彻底删除 {len(ids)} 条记录")
```

---

#### 5. 在主界面添加“回收站”按钮

在 `Viewer.__init__` 的工具栏中添加：
```python
ttk.Button(tool_frame, text="🗑️ 回收站", command=self.open_trash).pack(side=tk.LEFT, padx=2)
```

并添加方法：
```python
def open_trash(self):
    TrashViewer(self.root)
```

---

#### 6. 自动清理过期已删除记录（启动时执行）

在 `upgrade_db()` 之后添加清理函数：
```python
def clean_expired_trash():
    """自动清理超过30天的已删除记录（物理删除记录和截图）"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    cutoff = (datetime.now() - timedelta(days=30)).isoformat()
    c.execute("SELECT id, screenshot_path FROM records WHERE deleted=1 AND deleted_at < ?", (cutoff,))
    rows = c.fetchall()
    for record_id, path in rows:
        if path and os.path.exists(path):
            try:
                os.remove(path)
                print(f"清理过期截图：{path}")
            except Exception as e:
                print(f"清理截图失败：{e}")
    # 物理删除记录
    c.execute("DELETE FROM records WHERE deleted=1 AND deleted_at < ?", (cutoff,))
    conn.commit()
    conn.close()
```

在 `__main__` 中调用：
```python
if __name__ == "__main__":
    upgrade_db()
    clean_expired_trash()
    ...
```

---

### 📌 同步修改 `main.py`

确保 `main.py` 中的数据库初始化也包含新增字段。可以调用同样的 `upgrade_db()` 函数（建议将数据库操作提取到单独模块，如 `db.py`，便于复用）。

如果暂时不想大改，只需在 `main.py` 的 `init_db()` 中增加：
```python
c.execute('''
    CREATE TABLE IF NOT EXISTS records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        doing TEXT,
        next_plan TEXT,
        screenshot_path TEXT,
        ai_analysis TEXT,
        deleted INTEGER DEFAULT 0,
        deleted_at TEXT
    )
''')
```

---

### ✅ 最终效果

- **删除记录**：记录被标记为已删除，截图移到 `screenshots/trash/`（保持原名）。
- **回收站**：可以查看所有已删除记录，**恢复**后记录回到主列表，截图回到原目录。
- **彻底删除**：从回收站中彻底删除记录和截图。
- **自动清理**：启动时自动清理超过30天的已删除记录（包括截图）。

---

### 🚨 注意事项

- 如果 `screenshots/trash/` 中有同名文件，移动和恢复时都会自动加序号（`_1`, `_2`...）避免冲突。
- 恢复时，原截图路径会被更新为新的路径（因为可能加了序号），但数据库中的路径会同步更新。
- 建议将数据库升级逻辑放在两个程序启动时都执行，确保兼容性。

---

现在您的“在干嘛”工具拥有了完整的回收站功能，误删后可以轻松恢复。如果需要我整合成一个完整的 `view.py` 文件，请告诉我，我可以贴出完整代码。😊