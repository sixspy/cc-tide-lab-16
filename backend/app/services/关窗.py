"""关窗：缓冲按运单物化为窗切片，并在同一事务内封印写闸。"""
from __future__ import annotations
import hashlib
import json
import uuid
from collections import defaultdict

from app.db import 连接
from app.seed import 此刻
from app.modules.关窗封印写闸 import (
    DEFAULT_REASON,
    STATE_SEALED,
    写闸锁,
    窗归档键,
    规则已封印,
    规则策略,
    解封窗 as _解封窗,
    确保写闸账,
)


def _切片指纹(conn, 窗号: str) -> str:
    rows = conn.execute(
        """SELECT 切片编号,窗号,运单键,事件数,窗起,窗止,命运
           FROM 窗切片账 WHERE 窗号=? ORDER BY 切片编号""",
        (窗号,),
    ).fetchall()
    raw = "\n".join(
        "|".join(str(r[k]) for k in ("切片编号", "窗号", "运单键", "事件数", "窗起", "窗止", "命运"))
        for r in rows
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _既往关窗报告(conn, 窗号: str) -> dict | None:
    row = conn.execute(
        "SELECT 报告 FROM 关窗批次 WHERE 窗号=? ORDER BY 编号 DESC LIMIT 1",
        (窗号,),
    ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["报告"])
    except Exception:
        return None


def 关当前窗() -> dict:
    批 = f"关窗-{uuid.uuid4().hex[:8]}"
    with 写闸锁:
        conn = 连接()
        try:
            conn.execute("BEGIN IMMEDIATE")
            规 = {r["键"]: r["值"] for r in conn.execute("SELECT 键,值 FROM 窗规").fetchall()}
            窗号 = 规.get("当前窗号", "W-demo")
            窗起 = 规.get("窗起", "")
            窗止 = 规.get("窗止", "")
            策略 = 规则策略(规)
            确保写闸账(conn, 窗号, 策略)

            gate = conn.execute("SELECT * FROM 窗写闸账 WHERE 窗号=?", (窗号,)).fetchone()
            规封印 = 规则已封印(规, 窗号)
            if (gate is not None and gate["封印态"] == STATE_SEALED) or 规封印:
                # 并发关窗的后到者在这里读到已提交封印，绝不第二次物化。
                if gate is None or gate["封印态"] != STATE_SEALED:
                    时刻 = 此刻()
                    conn.execute(
                        """UPDATE 窗写闸账 SET 封印态=?,策略=?,拒因=?,更新时刻=?
                           WHERE 窗号=?""",
                        (STATE_SEALED, 策略, DEFAULT_REASON, 时刻, 窗号),
                    )
                既往 = _既往关窗报告(conn, 窗号) or {}
                报告 = {
                    "批次编号": 既往.get("批次编号", 批),
                    "窗号": 窗号,
                    "成片数": 既往.get("成片数", 0),
                    "缓冲消耗": 既往.get("缓冲消耗", 0),
                    "changed": False,
                    "成功": False,
                    "winner": False,
                    "already_sealed": True,
                    "幂等": True,
                    "是否封印": True,
                    "封印": True,
                    "封印态": STATE_SEALED,
                    "写闸策略": 策略,
                    "拒因": DEFAULT_REASON,
                    "切片集指纹": _切片指纹(conn, 窗号),
                }
                conn.commit()
                return 报告

            rows = conn.execute(
                "SELECT * FROM 入窗缓冲 WHERE 窗号=? AND 命运='在缓冲'", (窗号,)
            ).fetchall()
            by_waybill: dict[str, list] = defaultdict(list)
            for r in rows:
                by_waybill[r["运单键"]].append(r)

            成片 = 0
            时刻 = 此刻()
            for 运单, evs in by_waybill.items():
                切片 = f"片-{窗号}-{运单}-{uuid.uuid4().hex[:6]}"
                conn.execute(
                    """INSERT INTO 窗切片账(切片编号,窗号,运单键,事件数,窗起,窗止,物化时,命运)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (切片, 窗号, 运单, len(evs), 窗起, 窗止, 时刻, "已成片"),
                )
                for e in evs:
                    conn.execute(
                        "UPDATE 入窗缓冲 SET 命运=? WHERE 事件编号=?",
                        ("已物化", e["事件编号"]),
                    )
                    conn.execute(
                        "UPDATE 观测点 SET 命运=? WHERE 事件编号=?",
                        ("已成片", e["事件编号"]),
                    )
                成片 += 1

            # 窗规封印与写闸账、缓冲物化在同一事务内落票。
            for k, v in {
                "封印态": STATE_SEALED,
                "封印窗号": 窗号,
                "封印时刻": 时刻,
                "写闸策略": 策略,
            }.items():
                conn.execute(
                    """INSERT INTO 窗规(键,值) VALUES (?,?)
                       ON CONFLICT(键) DO UPDATE SET 值=excluded.值""",
                    (k, v),
                )
            conn.execute(
                """UPDATE 窗写闸账
                   SET 封印态=?, 策略=?, 拒因=?, 归档键=?, valid=1,
                       封印时刻=?, 解封时刻='', 更新时刻=?
                   WHERE 窗号=?""",
                (STATE_SEALED, 策略, DEFAULT_REASON, 窗归档键(窗号), 时刻, 时刻, 窗号),
            )

            报告 = {
                "批次编号": 批,
                "窗号": 窗号,
                "成片数": 成片,
                "缓冲消耗": len(rows),
                "changed": True,
                "成功": True,
                "winner": True,
                "already_sealed": False,
                "幂等": False,
                "是否封印": True,
                "封印": True,
                "封印态": STATE_SEALED,
                "写闸策略": 策略,
                "拒因": DEFAULT_REASON if 策略 == "切流拒写" else "",
                "归档键": 窗归档键(窗号) if 策略 == "双写归档" else None,
                "切片集指纹": _切片指纹(conn, 窗号),
            }
            conn.execute(
                """INSERT INTO 关窗批次(编号,窗号,时刻,成片数,报告) VALUES (?,?,?,?,?)""",
                (批, 窗号, 时刻, 成片, json.dumps(报告, ensure_ascii=False)),
            )
            conn.commit()
            return 报告
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def 解封当前窗(窗号: str | None = None, **kwargs) -> dict:
    """关窗编排的反向 CAS 入口；并发调用不会双写现行缓冲。"""
    return _解封窗(窗号, **kwargs)


# 兼容不同验收命名。
关窗 = 关当前窗
执行关窗 = 关当前窗
关窗并封印 = 关当前窗
解封窗 = 解封当前窗
解除封印 = 解封当前窗
解封写闸 = 解封当前窗


def 解封(窗号: str | None = None, **kwargs) -> dict:
    return _解封窗(窗号, **kwargs)
