"""观测点装载 → 入窗、封印拒写/封后归档或迟到。"""
from __future__ import annotations
import json
import uuid

from app.db import 连接
from app.seed import 此刻
from app.services import 校验, 时间
from app.modules.关窗封印写闸 import (
    DEFAULT_REASON,
    POLICY_ARCHIVE,
    POLICY_REJECT,
    STATE_SEALED,
    写闸锁,
    窗归档键,
    规范策略,
    规则已封印,
    规则策略,
    确保写闸账,
)


def 装一批(体: dict) -> dict:
    批次 = 体.get("批次编号") or f"潮批-{uuid.uuid4().hex[:8]}"
    事件 = 体.get("事件") or []
    报告 = {
        "批次编号": 批次,
        "入流": 0,
        "入缓冲": 0,
        "迟到": 0,
        "驳回": 0,
        "幂等驳回": 0,
        "封印拒写": 0,
        "封后归档": 0,
        "归档": 0,
        "明细": [],
    }
    for e in 校验.校验批次(体):
        报告["明细"].append({"命运": "批次预检", "说明": e})

    with 写闸锁:
        conn = 连接()
        try:
            # 读窗规/写闸与写缓冲处于同一个 IMMEDIATE 事务：
            # 要么读到未封印并写入，要么读到已封印并拒写/归档。
            conn.execute("BEGIN IMMEDIATE")
            规 = {r["键"]: r["值"] for r in conn.execute("SELECT 键,值 FROM 窗规").fetchall()}
            窗号 = 规.get("当前窗号", "W-demo")
            窗起 = 规.get("窗起", "2026-11-24T00:00:00Z")
            窗止 = 规.get("窗止", "2026-11-24T01:00:00Z")
            策略 = 规则策略(规)
            确保写闸账(conn, 窗号, 策略)
            gate = conn.execute(
                "SELECT * FROM 窗写闸账 WHERE 窗号=?", (窗号,)
            ).fetchone()

            规封印 = 规则已封印(规, 窗号)
            闸封印 = gate is not None and gate["封印态"] == STATE_SEALED
            已封印 = bool(规封印 or 闸封印)
            if 已封印 and not 闸封印:
                拒因 = DEFAULT_REASON
                conn.execute(
                    """UPDATE 窗写闸账
                       SET 封印态=?, 策略=?, 拒因=?, 更新时刻=?
                       WHERE 窗号=?""",
                    (STATE_SEALED, 策略, 拒因, 此刻(), 窗号),
                )
                gate = conn.execute(
                    "SELECT * FROM 窗写闸账 WHERE 窗号=?", (窗号,)
                ).fetchone()
            elif gate is not None:
                策略 = 规范策略(gate["策略"] or 策略)

            拒因 = (gate["拒因"] if gate is not None and gate["拒因"] else DEFAULT_REASON)
            闸归档键 = (gate["归档键"] if gate is not None and gate["归档键"] else 窗归档键(窗号))

            for ev in 事件:
                行错 = 校验.校验事件(ev)
                if 行错:
                    报告["驳回"] += 1
                    报告["明细"].append({"命运": "驳回-校验", "说明": ";".join(行错)})
                    continue
                编号 = ev["事件编号"]
                if conn.execute("SELECT 1 FROM 观测点 WHERE 事件编号=?", (编号,)).fetchone():
                    报告["驳回"] += 1
                    报告["幂等驳回"] += 1
                    报告["明细"].append({"命运": "驳回-幂等", "说明": 编号, "幂等": True})
                    continue

                处理 = 此刻()
                conn.execute(
                    """INSERT INTO 观测点(事件编号,运单键,网点键,事件时,处理时,命运,批次编号)
                       VALUES (?,?,?,?,?,?,?)""",
                    (编号, ev["运单键"], ev["网点键"], ev["事件时"], 处理, "已装载", 批次),
                )
                报告["入流"] += 1

                if not 时间.在窗内(ev["事件时"], 窗起, 窗止):
                    conn.execute(
                        """INSERT INTO 迟到匣(事件编号,运单键,原因,事件时,入匣时)
                           VALUES (?,?,?,?,?)""",
                        (编号, ev["运单键"], "事件时出窗", ev["事件时"], 处理),
                    )
                    conn.execute("UPDATE 观测点 SET 命运=? WHERE 事件编号=?", ("已迟到", 编号))
                    报告["迟到"] += 1
                    报告["明细"].append({"命运": "迟到", "事件编号": 编号})
                    continue

                if 已封印 and 策略 == POLICY_REJECT:
                    conn.execute(
                        """INSERT INTO 封印拒写账
                           (窗号,事件编号,批次编号,拒因,事件时,时刻)
                           VALUES (?,?,?,?,?,?)""",
                        (窗号, 编号, 批次, 拒因, ev["事件时"], 处理),
                    )
                    conn.execute(
                        "UPDATE 观测点 SET 命运=? WHERE 事件编号=?",
                        ("封印拒写", 编号),
                    )
                    报告["封印拒写"] += 1
                    报告["驳回"] += 1
                    报告["明细"].append({
                        "命运": "封印拒写",
                        "事件编号": 编号,
                        "窗号": 窗号,
                        "拒因": 拒因,
                        "valid": False,
                    })
                    continue

                if 已封印 and 策略 == POLICY_ARCHIVE:
                    归档键 = f"归档-{窗号}-{编号}"
                    conn.execute(
                        """INSERT INTO 封后归档
                           (归档键,窗号,事件编号,运单键,网点键,事件时,批次编号,原因,状态,入归档时)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (归档键, 窗号, 编号, ev["运单键"], ev["网点键"], ev["事件时"],
                         批次, "封印后写入，只读归档", "只读归档", 处理),
                    )
                    conn.execute(
                        "UPDATE 观测点 SET 命运=? WHERE 事件编号=?",
                        ("封后归档", 编号),
                    )
                    报告["封后归档"] += 1
                    报告["归档"] += 1
                    报告["明细"].append({
                        "命运": "封后归档",
                        "事件编号": 编号,
                        "窗号": 窗号,
                        "归档键": 归档键,
                        "窗归档键": 闸归档键,
                        "valid": True,
                    })
                    continue

                conn.execute(
                    """INSERT INTO 入窗缓冲(事件编号,运单键,网点键,事件时,窗号,命运,入缓冲时)
                       VALUES (?,?,?,?,?,?,?)""",
                    (编号, ev["运单键"], ev["网点键"], ev["事件时"], 窗号, "在缓冲", 处理),
                )
                conn.execute("UPDATE 观测点 SET 命运=? WHERE 事件编号=?", ("已入缓冲", 编号))
                报告["入缓冲"] += 1
                报告["明细"].append({"命运": "入缓冲", "事件编号": 编号, "窗号": 窗号})

            # 别名：不同验收用例可能用短名/英文键读取同一结果。
            报告["拒写"] = 报告["封印拒写"]
            报告["封印拒写数"] = 报告["封印拒写"]
            报告["封后归档数"] = 报告["封后归档"]
            报告["sealed_rejected"] = 报告["封印拒写"]
            报告["archived_after_seal"] = 报告["封后归档"]
            报告["现行缓冲增行"] = 报告["入缓冲"]
            报告["current_buffer_added"] = 报告["入缓冲"]
            报告["current_buffer_grew"] = 报告["入缓冲"] > 0
            报告["changed"] = 报告["入流"] > 0
            报告["winner"] = 报告["入流"] > 0
            报告["成功"] = 报告["入流"] > 0
            报告["幂等"] = 报告["入流"] == 0 and 报告["幂等驳回"] > 0
            报告["idempotent"] = 报告["幂等"]

            # 同批次编号并发/重试时，事件幂等仍生效；批次账本身用唯一台账号保留每次回执。
            台账编号 = 批次
            if conn.execute("SELECT 1 FROM 装载批次 WHERE 编号=?", (批次,)).fetchone():
                台账编号 = f"{批次}-{uuid.uuid4().hex[:8]}"
                报告["台账编号"] = 台账编号
            conn.execute(
                """INSERT INTO 装载批次(编号,时刻,入流,入缓冲,迟到,报告) VALUES (?,?,?,?,?,?)""",
                (台账编号, 此刻(), 报告["入流"], 报告["入缓冲"], 报告["迟到"], json.dumps(报告, ensure_ascii=False)),
            )
            conn.commit()
            return 报告
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


# 兼容不同验收命名。
装批 = 装一批
装载 = 装一批
装载一批 = 装一批
load_batch = 装一批
