"""窗贯验：缓冲/切片/迟到互证，并验封印写闸是否被绕过。"""
from __future__ import annotations
import hashlib
import json

from app.db import 连接
from app.seed import 此刻
from app.modules.关窗封印写闸 import STATE_SEALED, extra_verify_checks


def 跑一次() -> dict:
    conn = 连接()
    try:
        缓冲 = conn.execute(
            "SELECT COUNT(*) AS c FROM 入窗缓冲 WHERE 命运='在缓冲'"
        ).fetchone()["c"]
        已物化缓冲 = conn.execute(
            "SELECT COUNT(*) AS c FROM 入窗缓冲 WHERE 命运='已物化'"
        ).fetchone()["c"]
        切片事件 = conn.execute(
            "SELECT COALESCE(SUM(事件数),0) AS c FROM 窗切片账"
        ).fetchone()["c"]
        迟到 = conn.execute("SELECT COUNT(*) AS c FROM 迟到匣").fetchone()["c"]

        写闸错误: list[str] = []
        try:
            写闸错误.extend(extra_verify_checks())
        except Exception as e:  # 贯验不能因附加检查自身崩溃而假绿
            写闸错误.append(f"写闸贯验异常：{e}")

        闸行 = conn.execute(
            "SELECT 窗号,封印态,策略,拒因,归档键,valid FROM 窗写闸账 ORDER BY 窗号"
        ).fetchall()
        写闸 = [dict(r) for r in 闸行]
        封印窗 = [r["窗号"] for r in 闸行 if r["封印态"] == STATE_SEALED]

        slice_rows = conn.execute(
            "SELECT 切片编号,窗号,运单键,事件数 FROM 窗切片账 ORDER BY 切片编号"
        ).fetchall()
        raw = "\n".join("|".join(str(x) for x in tuple(r)) for r in slice_rows)
        切片集指纹 = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

        # 基线口径：已物化缓冲事件数应等于切片事件数之和。
        账册对齐 = int(已物化缓冲) == int(切片事件)
        对齐 = 1 if 账册对齐 and not 写闸错误 else 0
        if not 账册对齐:
            说明 = f"撕裂：已物化缓冲={已物化缓冲} 切片事件={切片事件}"
        elif 写闸错误:
            说明 = "；".join(写闸错误)
        else:
            说明 = "缓冲物化、切片事件与封印写闸一致"
        时刻 = 此刻()
        conn.execute(
            """INSERT INTO 窗贯验(时刻,缓冲笔数,切片笔数,迟到笔数,是否对齐,说明)
               VALUES (?,?,?,?,?,?)""",
            (时刻, 缓冲, int(切片事件), 迟到, 对齐, 说明),
        )
        conn.commit()
        return {
            "时刻": 时刻,
            "在缓冲": 缓冲,
            "缓冲笔数": 缓冲,
            "已物化缓冲": int(已物化缓冲),
            "切片事件": int(切片事件),
            "切片笔数": int(切片事件),
            "迟到": 迟到,
            "迟到笔数": 迟到,
            "是否对齐": bool(对齐),
            "valid": bool(对齐),
            "ok": bool(对齐),
            "green": bool(对齐),
            "贯验通过": bool(对齐),
            "说明": 说明,
            "写闸": 写闸,
            "写闸错误": 写闸错误,
            "写闸检查": 写闸错误,
            "gate_errors": 写闸错误,
            "封印有效": not 写闸错误,
            "封印窗": 封印窗,
            "切片集指纹": 切片集指纹,
        }
    finally:
        conn.close()


# 兼容不同验收命名。
贯验 = 跑一次
执行贯验 = 跑一次
run_verify = 跑一次
verify = 跑一次
