"""
WAYD Backup System — 纯文本 / 完整备份，支持增量链式存储。

工作流程:
  1) 创建 BASE (基线) 备份，记录当前所有数据的快照
  2) 之后创建 INCREMENTAL (增量) 备份，只存新增的记录（和截图）
  3) 每条链从 base 开始，可以串联多个 incremental，形成"基线 → inc1 → inc2"
  4) 备份历史存在 manifest.json 中，可浏览 / 查看内容 / 删除

文件布局:
  backups/
    manifest.json                  — 全局注册表
    base_20260623_120000.txt.json  — 纯文本基线
    base_20260623_120000.full.zip  — 完整基线 (+截图)
    inc_20260624_180000.txt.json   — 纯文本增量
    inc_20260624_180000.full.zip   — 完整增量 (+截图)
"""

import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime

# ── 常量 ──
BACKUP_DIR = "backups"
MANIFEST_FILE = os.path.join(BACKUP_DIR, "manifest.json")
DB_FILE = "whatido.db"


# ============================================================
# 内部辅助函数
# ============================================================

def _ensure_dir():
    """确保备份目录存在"""
    os.makedirs(BACKUP_DIR, exist_ok=True)


def _now_tag():
    """生成用于文件名的时刻标记 (YYYYMMDD_HHMMSS)"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _now_iso():
    """生成 ISO 时间字符串"""
    return datetime.now().isoformat()


def _load_manifest():
    """加载 manifest.json，返回 dict"""
    _ensure_dir()
    if not os.path.exists(MANIFEST_FILE):
        return {"version": 1, "entries": {}}
    try:
        with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {"version": 1, "entries": {}}


def _save_manifest(manifest):
    """原子写入 manifest.json"""
    _ensure_dir()
    tmp = MANIFEST_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    os.replace(tmp, MANIFEST_FILE)


def _find_unique_id(base_name):
    """生成不重复的备份 ID（带防碰撞后缀）"""
    manifest = _load_manifest()
    existing = set(manifest["entries"].keys())
    candidate = base_name
    suffix = 2
    while candidate in existing:
        candidate = f"{base_name}_{suffix}"
        suffix += 1
    return candidate


def _calc_max_record_id():
    """查询当前数据库最大记录 ID"""
    try:
        conn = sqlite3.connect(DB_FILE)
        row = conn.execute("SELECT MAX(id) FROM records").fetchone()
        conn.close()
        return row[0] if row[0] is not None else 0
    except Exception:
        return 0


def _fetch_all_records():
    """获取所有记录"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, timestamp, doing, next_plan, screenshot_path FROM records ORDER BY id")
    rows = c.fetchall()
    conn.close()
    return [
        {"id": r[0], "timestamp": r[1], "doing": r[2], "next_plan": r[3], "screenshot_path": r[4] or ""}
        for r in rows
    ]


def _fetch_records_after(min_id):
    """获取 id > min_id 的所有记录"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, timestamp, doing, next_plan, screenshot_path FROM records WHERE id > ? ORDER BY id", (min_id,))
    rows = c.fetchall()
    conn.close()
    return [
        {"id": r[0], "timestamp": r[1], "doing": r[2], "next_plan": r[3], "screenshot_path": r[4] or ""}
        for r in rows
    ]


def _build_text_file(backup_id, records, meta_extra=None):
    """将 records 写入 JSON 文件，返回文件路径"""
    meta = {
        "id": backup_id,
        "created_at": _now_iso(),
        "record_count": len(records),
        "max_record_id": max((r["id"] for r in records), default=0),
        **(meta_extra or {}),
    }
    payload = {"meta": meta, "records": records}
    fname = f"{backup_id}.txt.json"
    fpath = os.path.join(BACKUP_DIR, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return fpath, fname


def _build_full_zip(backup_id, records, meta_extra=None):
    """将 records + 截图打包为 zip，返回文件路径"""
    meta = {
        "id": backup_id,
        "created_at": _now_iso(),
        "record_count": len(records),
        "max_record_id": max((r["id"] for r in records), default=0),
        **(meta_extra or {}),
    }
    payload = {"meta": meta, "records": records}
    fname = f"{backup_id}.full.zip"
    fpath = os.path.join(BACKUP_DIR, fname)

    with tempfile.TemporaryDirectory() as tmpdir:
        # 写 records.json
        rpath = os.path.join(tmpdir, "records.json")
        with open(rpath, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        # 收集截图文件
        seen = set()
        screenshot_dir = os.path.join(tmpdir, "screenshots")
        os.makedirs(screenshot_dir, exist_ok=True)
        for rec in records:
            sp = rec.get("screenshot_path", "")
            if sp and os.path.exists(sp) and sp not in seen:
                seen.add(sp)
                try:
                    shutil.copy2(sp, os.path.join(screenshot_dir, os.path.basename(sp)))
                except Exception:
                    pass  # 跳过无法拷贝的截图

        # 打包
        with zipfile.ZipFile(fpath, "w", zipfile.ZIP_DEFLATED) as z:
            for dirpath, _dirnames, filenames in os.walk(tmpdir):
                for fn in filenames:
                    full = os.path.join(dirpath, fn)
                    arcname = os.path.relpath(full, tmpdir)
                    z.write(full, arcname)

    return fpath, fname


def _read_records_from_entry(entry):
    """从备份文件读取 records"""
    fpath = os.path.join(BACKUP_DIR, entry["file"])
    if not os.path.exists(fpath):
        return []

    mode = entry.get("mode", "text")
    if mode == "full":
        # zip 包
        with zipfile.ZipFile(fpath, "r") as z:
            with z.open("records.json") as f:
                data = json.load(f)
        return data.get("records", [])
    else:
        # json 文件
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("records", [])


def _walk_chain(manifest, start_id):
    """从 start_id 开始沿 child_id 前进，返回有序列表 [start, ..., last]"""
    entries = manifest["entries"]
    chain = []
    cur = entries.get(start_id)
    while cur:
        chain.append(cur)
        child_id = cur.get("child_id")
        cur = entries.get(child_id) if child_id else None
    return chain


def _get_time_range_str(records):
    """从 records 列表计算时间范围，返回 (from_str, to_str)"""
    times = [r["timestamp"] for r in records if r.get("timestamp")]
    if not times:
        return ("", "")
    times.sort()
    return (times[0], times[-1])


# ============================================================
# 公开 API
# ============================================================

def init_backup_dir():
    """初始化备份目录（确保存在）"""
    _ensure_dir()


# ── 创建基线备份 ──

def create_base_backup(mode="text"):
    """
    创建基线备份，捕获当前所有记录。

    参数:
        mode: "text" (纯文本) 或 "full" (完整含截图)

    返回:
        dict | None — 创建的备份条目信息，失败返回 None
    """
    records = _fetch_all_records()
    if not records:
        return None

    tag = _now_tag()
    backup_id = _find_unique_id(f"base_{tag}")
    max_id = _calc_max_record_id()
    time_from, time_to = _get_time_range_str(records)

    meta_extras = {
        "type": "base",
        "mode": mode,
        "parent_id": None,
    }

    try:
        if mode == "full":
            fpath, fname = _build_full_zip(backup_id, records, meta_extras)
        else:
            fpath, fname = _build_text_file(backup_id, records, meta_extras)

        entry = {
            "id": backup_id,
            "type": "base",
            "mode": mode,
            "created_at": _now_iso(),
            "file": fname,
            "record_count": len(records),
            "max_record_id": max_id,
            "parent_id": None,
            "child_id": None,
            "time_from": time_from,
            "time_to": time_to,
        }

        manifest = _load_manifest()
        manifest["entries"][backup_id] = entry
        _save_manifest(manifest)
        return entry
    except Exception as e:
        print(f"[backup] 创建基线失败: {e}")
        return None


# ── 创建增量备份 ──

def create_incremental_backup(parent_id):
    """
    在指定 parent 之后创建增量备份。

    parent 可以是该链上的任意节点（base 或 incremental）。
    增量备份只存储 parent 之后新增的记录。

    返回:
        dict | None — 创建的备份条目信息，失败返回 None
    """
    manifest = _load_manifest()
    parent = manifest["entries"].get(parent_id)
    if not parent:
        print(f"[backup] 未找到 parent: {parent_id}")
        return None

    # 找到链的末端（最后一个 child），在其之后追加
    chain = _walk_chain(manifest, parent_id)
    tail = chain[-1]
    base = chain[0]

    records = _fetch_records_after(tail["max_record_id"])
    if not records:
        return None  # 没有新记录

    tag = _now_tag()
    backup_id = _find_unique_id(f"inc_{tag}")
    time_from, time_to = _get_time_range_str(records)

    mode = base.get("mode", "text")
    meta_extras = {
        "type": "incremental",
        "mode": mode,
        "parent_id": tail["id"],
    }

    try:
        if mode == "full":
            fpath, fname = _build_full_zip(backup_id, records, meta_extras)
        else:
            fpath, fname = _build_text_file(backup_id, records, meta_extras)

        entry = {
            "id": backup_id,
            "type": "incremental",
            "mode": mode,
            "created_at": _now_iso(),
            "file": fname,
            "record_count": len(records),
            "max_record_id": max((r["id"] for r in records), default=tail["max_record_id"]),
            "parent_id": tail["id"],
            "child_id": None,
            "time_from": time_from,
            "time_to": time_to,
        }

        # 更新父节点的 child_id
        manifest["entries"][tail["id"]]["child_id"] = backup_id
        manifest["entries"][backup_id] = entry
        _save_manifest(manifest)
        return entry
    except Exception as e:
        print(f"[backup] 创建增量备份失败: {e}")
        return None


# ── 查询 ──

def get_chains():
    """
    获取所有备份链（以 base 为单位）。

    返回:
        list[dict] — 所有 base 备份及其链信息
    """
    manifest = _load_manifest()
    chains = []
    for entry in manifest["entries"].values():
        if entry["type"] == "base":
            chain_entries = _walk_chain(manifest, entry["id"])
            total_records = sum(e["record_count"] for e in chain_entries)
            chains.append({
                "base": entry,
                "chain": chain_entries,
                "length": len(chain_entries),
                "total_records": total_records,
            })
    # 按创建时间降序排列
    chains.sort(key=lambda c: c["base"]["created_at"], reverse=True)
    return chains


def get_chain_for(backup_id):
    """
    获取指定备份所在的完整链。

    返回:
        list[dict] — [base, ..., this_entry, ...] 的完整链
    """
    manifest = _load_manifest()
    entry = manifest["entries"].get(backup_id)
    if not entry:
        return []

    # 先回到链首（基线的 parent_id 为 None）
    cur = entry
    while cur.get("parent_id"):
        cur = manifest["entries"].get(cur["parent_id"])
        if not cur:
            break
    base_id = cur["id"] if cur else backup_id
    return _walk_chain(manifest, base_id)


def get_all_records_in_chain_up_to(backup_id):
    """
    获取从基线到指定备份节点的所有记录（合并）。

    用于"恢复到该备份点"预览。
    """
    chain = get_chain_for(backup_id)
    if not chain:
        return []

    # 只取到目标节点
    target_found = False
    records = []
    for entry in chain:
        records.extend(_read_records_from_entry(entry))
        if entry["id"] == backup_id:
            target_found = True
            break

    if not target_found:
        return []

    # 按 id 去重并排序
    seen = set()
    deduped = []
    for r in records:
        rid = r["id"]
        if rid not in seen:
            seen.add(rid)
            deduped.append(r)
    deduped.sort(key=lambda r: r["id"])
    return deduped


def get_backup_detail(backup_id):
    """获取单个备份条目的详细信息"""
    manifest = _load_manifest()
    entry = manifest["entries"].get(backup_id)
    if not entry:
        return None

    # 如果文件存在，额外读取记录预览
    fpath = os.path.join(BACKUP_DIR, entry["file"])
    file_exists = os.path.exists(fpath)
    file_size = os.path.getsize(fpath) if file_exists else 0

    detail = {**entry, "file_exists": file_exists, "file_size": file_size}

    # 如果是链中的节点，标记位置
    if entry["parent_id"]:
        parent = manifest["entries"].get(entry["parent_id"])
        detail["parent_name"] = parent["id"] if parent else None

    return detail


def delete_backup(backup_id):
    """
    删除一个备份条目及其文件。

    注意:
        - 如果有 child，则 child 的 parent_id 指向上级
        - 如果是 base 且有 child，则删除整条链
    返回:
        bool — 是否成功
    """
    manifest = _load_manifest()
    entry = manifest["entries"].get(backup_id)
    if not entry:
        return False

    # 如果有 child，提示先删除子节点
    if entry.get("child_id"):
        return False  # 必须先删除子节点

    # 删除文件
    fpath = os.path.join(BACKUP_DIR, entry["file"])
    if os.path.exists(fpath):
        try:
            os.remove(fpath)
        except Exception as e:
            print(f"[backup] 删除文件失败: {e}")

    # 更新父节点的 child_id
    parent_id = entry.get("parent_id")
    if parent_id and parent_id in manifest["entries"]:
        manifest["entries"][parent_id]["child_id"] = None

    # 删除 manifest 条目
    del manifest["entries"][backup_id]
    _save_manifest(manifest)
    return True
