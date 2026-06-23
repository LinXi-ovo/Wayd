"""
note.py — 笔记记录工具

记录做题/学习的步骤序列和笔记，支持标签分类（如错题集）。

用法:
  # 添加笔记
  python note.py <步骤序列> <内容> [-t <标签>]
  python note.py a13 "把1抄成了-1" -t x

  # 查询笔记
  python note.py list [-t <标签>] [-k <关键词>] [--date <YYYY-MM-DD>]
  python note.py list -t x          # 查看错题集
  python note.py list -k "抄错"     # 搜索关键词

  # 删除笔记
  python note.py del <id> [<id>...]

  # 查看统计
  python note.py stats

示例:
  python note.py a13 "把1抄成了-1" -t x
  -> 记录：步骤=a13, 内容="把1抄成了-1", 标签="x"(错题集)
"""

import sqlite3
import sys
import os
import argparse
from datetime import datetime

DB_FILE = "whatido.db"
NOTES_TABLE = "notes"


def init_notes_db():
    """初始化笔记表"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS {NOTES_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            step_sequence TEXT,
            content TEXT NOT NULL,
            tags TEXT DEFAULT ''
        )
    """)
    conn.commit()
    conn.close()


def add_note(step_sequence, content, tags=""):
    """添加一条笔记记录"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        f"INSERT INTO {NOTES_TABLE} (timestamp, step_sequence, content, tags) VALUES (?, ?, ?, ?)",
        (datetime.now().isoformat(), step_sequence, content, tags)
    )
    conn.commit()
    note_id = c.lastrowid
    conn.close()
    return note_id


def get_notes(tag=None, keyword=None, date_str=None, limit=100, offset=0):
    """查询笔记，支持标签、关键词、日期过滤和分页"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    query = f"SELECT id, timestamp, step_sequence, content, tags FROM {NOTES_TABLE} WHERE 1=1"
    params = []

    if tag:
        query += " AND tags LIKE ?"
        params.append(f"%{tag}%")
    if keyword:
        query += " AND (content LIKE ? OR step_sequence LIKE ?)"
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    if date_str:
        try:
            query += " AND date(timestamp) = ?"
            params.append(date_str)
        except Exception:
            pass

    query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return rows


def get_note_stats(tag=None, date_str=None):
    """获取笔记统计信息"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # 总笔记数
    count_query = "SELECT COUNT(*) FROM notes WHERE 1=1"
    count_params = []
    if tag:
        count_query += " AND tags LIKE ?"
        count_params.append(f"%{tag}%")
    if date_str:
        count_query += " AND date(timestamp) = ?"
        count_params.append(date_str)
    total = c.execute(count_query, count_params).fetchone()[0]

    # 标签统计（按标签分组计数）
    tag_query = "SELECT tags, COUNT(*) as cnt FROM notes WHERE 1=1"
    tag_params = []
    if date_str:
        tag_query += " AND date(timestamp) = ?"
        tag_params.append(date_str)
    tag_query += " GROUP BY tags ORDER BY cnt DESC LIMIT 10"
    tag_stats = c.execute(tag_query, tag_params).fetchall()

    conn.close()
    return total, tag_stats


def delete_notes(ids):
    """删除笔记（物理删除）"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    placeholders = ",".join("?" * len(ids))
    c.execute(f"DELETE FROM notes WHERE id IN ({placeholders})", ids)
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted


def print_note_row(row):
    """格式化打印一条笔记"""
    note_id, timestamp, step_seq, content, tags = row
    dt = datetime.fromisoformat(timestamp)
    time_str = dt.strftime("%m-%d %H:%M")
    tag_str = f" [{tags}]" if tags else ""
    step_str = f" #{step_seq}" if step_seq else ""
    print(f"  [{note_id:4d}] {time_str}{step_str}{tag_str}")
    print(f"         {content}")
    print()


# ===== CLI 主入口 =====
def main():
    # 预先检查是否为 list / del / stats 子命令（避免与默认 add 冲突）
    raw = [a for a in sys.argv[1:] if not a.startswith("-")]
    is_subcommand = bool(raw) and raw[0] in ("list", "del", "stats")

    parser = argparse.ArgumentParser(
        prog="note.py",
        description="WAYD 笔记记录工具 — 记录步骤序列、笔记和标签",
        epilog="示例: python note.py a13 '把1抄成了-1' -t x",
    )

    if not is_subcommand:
        # ── 默认模式（add）： note <step_sequence> <content> [-t <tag>] ──
        parser.add_argument("step_sequence", nargs="?", default="", help="步骤序列标识（如 a13）")
        parser.add_argument("content", nargs="?", default="", help="笔记内容")
        parser.add_argument("-t", "--tag", default="", help="标签（如 x=错题集）")
        args = parser.parse_args()

        init_notes_db()

        if not args.content:
            print("错误: 请提供笔记内容")
            print("用法: python note.py <步骤序列> <内容> [-t <标签>]")
            print("示例: python note.py a13 '把1抄成了-1' -t x")
            sys.exit(1)

        note_id = add_note(args.step_sequence, args.content, args.tag)
        tag_info = f" 标签=[{args.tag}]" if args.tag else ""
        print(f"✓ 笔记已添加 [ID={note_id}]{tag_info}")
        if args.step_sequence:
            print(f"  步骤: {args.step_sequence}")
        print(f"  内容: {args.content}")
        return

    # ── 子命令模式：list / del / stats ──
    sub = parser.add_subparsers(dest="command", help="子命令")

    list_parser = sub.add_parser("list", help="查询笔记")
    list_parser.add_argument("-t", "--tag", default=None, help="按标签筛选")
    list_parser.add_argument("-k", "--keyword", default=None, help="按关键词搜索")
    list_parser.add_argument("--date", default=None, help="按日期筛选 (YYYY-MM-DD)")
    list_parser.add_argument("-l", "--limit", type=int, default=50, help="每页条数")

    del_parser = sub.add_parser("del", help="删除笔记")
    del_parser.add_argument("ids", nargs="+", type=int, help="笔记ID")

    stats_parser = sub.add_parser("stats", help="笔记统计")
    stats_parser.add_argument("-t", "--tag", default=None, help="按标签统计")
    stats_parser.add_argument("--date", default=None, help="按日期统计 (YYYY-MM-DD)")

    args = parser.parse_args()
    init_notes_db()

    # ── list ──
    if args.command == "list":
        rows = get_notes(tag=args.tag, keyword=args.keyword, date_str=args.date, limit=args.limit)
        if not rows:
            print("(无匹配笔记)")
            return
        print(f"共 {len(rows)} 条笔记:\n")
        for row in rows:
            print_note_row(row)
        return

    # ── del ──
    if args.command == "del":
        deleted = delete_notes(args.ids)
        print(f"✓ 已删除 {deleted} 条笔记")
        return

    # ── stats ──
    if args.command == "stats":
        total, tag_stats = get_note_stats(tag=args.tag, date_str=args.date)
        date_info = f" ({args.date})" if args.date else ""
        print(f"📊 笔记统计{date_info}")
        print(f"  总笔记数: {total}")
        if tag_stats:
            print(f"\n  标签分布:")
            for tag, cnt in tag_stats:
                tag_display = tag if tag else "(无标签)"
                print(f"    [{tag_display}] {cnt} 条")
        return


if __name__ == "__main__":
    main()
