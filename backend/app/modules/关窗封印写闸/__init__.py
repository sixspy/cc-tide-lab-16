"""关窗封印写闸：封印态、拒写/归档两态与并发安全解封。

本模块同时保留邻题钩子契约。写闸状态以 SQLite 行账为准；所有“读封印 →
写缓冲/归档”的路径都必须在 ``BEGIN IMMEDIATE`` 事务内完成，进程内再用
``写闸锁`` 串行化，避免线程竞态造成双写或双成功。
"""

from __future__ import annotations

import contextlib
import sqlite3
import threading
import uuid
from typing import Any

from app.db import 连接
from app.seed import 此刻

NAME = "关窗封印写闸"
CONTRACT = "已封印窗禁止再写入缓冲"
EXTENDED_CONTRACT = "已封印窗禁止再写入现行缓冲；可切流拒写或双写只读归档"

HOOKS = (
    "before_load",
    "after_load",
    "decide_window",
    "before_close",
    "after_close",
    "extra_verify_checks",
)

STATE_OPEN = "未封印"
STATE_SEALED = "已封印"
POLICY_REJECT = "切流拒写"
POLICY_ARCHIVE = "双写归档"
DEFAULT_REASON = "已封窗拒装载进该窗缓冲并钉拒因"

POLICY_ALIASES = {
    "": POLICY_REJECT,
    "切流拒写": POLICY_REJECT,
    "切流": POLICY_REJECT,
    "拒写": POLICY_REJECT,
    "账册拒写": POLICY_REJECT,
    "切流账册": POLICY_REJECT,
    "账册封印拒写": POLICY_REJECT,
    "切流账册封印拒写": POLICY_REJECT,
    "封印拒写": POLICY_REJECT,
    "reject": POLICY_REJECT,
    "deny": POLICY_REJECT,
    "reject_write": POLICY_REJECT,
    POLICY_REJECT: POLICY_REJECT,
    "双写归档": POLICY_ARCHIVE,
    "双写两轨": POLICY_ARCHIVE,
    "双写两轨归档": POLICY_ARCHIVE,
    "双写": POLICY_ARCHIVE,
    "两轨": POLICY_ARCHIVE,
    "归档": POLICY_ARCHIVE,
    "封后归档": POLICY_ARCHIVE,
    "archive": POLICY_ARCHIVE,
    "dual": POLICY_ARCHIVE,
    "dual_write": POLICY_ARCHIVE,
    POLICY_ARCHIVE: POLICY_ARCHIVE,
}

# 进程内锁；SQLite BEGIN IMMEDIATE 则负责跨连接/跨进程写串行。
写闸锁 = threading.RLock()


def describe() -> dict:
    return {
        "空桩": NAME,
        "契约": CONTRACT,
        "扩展契约": EXTENDED_CONTRACT,
        "钩子": list(HOOKS),
        "默认启用": True,
        "策略": [POLICY_REJECT, POLICY_ARCHIVE],
        "只读接口": "写闸状态(窗号)",
        "说明": "关窗时同事务封印并物化；装载时同事务读闸并决定拒写或归档",
    }


def 规范策略(value: Any) -> str:
    return POLICY_ALIASES.get(str(value or "").strip(), POLICY_REJECT)


策略键 = ("写闸策略", "封印策略", "写闸形态", "封印形态", "拒写形态")
封印键 = ("封印态", "封印状态", "写闸态", "写闸状态")
封印真值 = {
    STATE_SEALED, "已封窗", "已封印", "封印", "封", "已封", "sealed", "closed",
    "locked", "lock", "1", "true", "True", True,
}


def 规则策略(规: dict) -> str:
    for k in 策略键:
        if k in 规 and 规[k] not in (None, ""):
            return 规范策略(规[k])
    return POLICY_REJECT


def 规则已封印(规: dict, 窗号: str) -> bool:
    for k in 封印键:
        if 规.get(k) in 封印真值 or str(规.get(k, "")).strip() in {"已封窗", "sealed"}:
            bound = str(规.get("封印窗号") or 规.get("封窗号") or "").strip()
            return (not bound) or bound == 窗号
    return False


def 窗归档键(窗号: str) -> str:
    return f"封后归档:{窗号}"


def 当前窗号(conn) -> str:
    row = conn.execute("SELECT 值 FROM 窗规 WHERE 键='当前窗号'").fetchone()
    return str(row["值"]) if row else "W-demo"


def 窗规映射(conn) -> dict[str, str]:
    return {r["键"]: r["值"] for r in conn.execute("SELECT 键,值 FROM 窗规").fetchall()}


def 确保写闸账(conn, 窗号: str, 策略: str | None = None) -> None:
    """在写事务内补齐写闸账；缺省为未封印。"""
    now = 此刻()
    policy = 规范策略(策略)
    conn.execute(
        """INSERT OR IGNORE INTO 窗写闸账
           (窗号,封印态,策略,拒因,归档键,valid,封印时刻,解封时刻,更新时刻)
           VALUES (?,?,?,?,?,1,'','',?)""",
        (窗号, STATE_OPEN, policy, "", 窗归档键(窗号), now),
    )


@contextlib.contextmanager
def 即时事务(conn=None):
    """获取进程锁并开启 SQLite IMMEDIATE 事务。"""
    with 写闸锁:
        own = conn is None
        if own:
            conn = 连接()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            if own:
                conn.commit()
        except Exception:
            if own:
                conn.rollback()
            raise
        finally:
            if own:
                conn.close()


def _状态从行(conn, 窗号: str, row) -> dict:
    active = conn.execute(
        "SELECT COUNT(*) AS c FROM 入窗缓冲 WHERE 窗号=? AND 命运='在缓冲'",
        (窗号,),
    ).fetchone()["c"]
    rejected = conn.execute(
        "SELECT COUNT(*) AS c FROM 封印拒写账 WHERE 窗号=?", (窗号,)
    ).fetchone()["c"]
    archived = conn.execute(
        "SELECT COUNT(*) AS c FROM 封后归档 WHERE 窗号=?", (窗号,)
    ).fetchone()["c"]

    if row is None:
        return {
            "窗号": 窗号,
            "window_id": 窗号,
            "封印态": "无写闸账",
            "state": "missing",
            "是否封印": False,
            "封印": False,
            "sealed": False,
            "策略": POLICY_REJECT,
            "写闸策略": POLICY_REJECT,
            "policy": POLICY_REJECT,
            "策略标签": "切流账册封印拒写",
            "拒因": "写闸账不存在",
            "reason": "写闸账不存在",
            "归档键": None,
            "archive_key": None,
            "valid": False,
            "ok": False,
            "允许写入现行": True,
            "可写": True,
            "writable": True,
            "现行缓冲行数": int(active),
            "拒写笔数": int(rejected),
            "归档笔数": int(archived),
            "changed": False,
        }

    data = dict(row)
    state = data.get("封印态") or STATE_OPEN
    sealed = state == STATE_SEALED
    policy = 规范策略(data.get("策略"))
    torn = sealed and int(active or 0) > 0
    valid = bool(data.get("valid", 1)) and not torn
    archive_key = data.get("归档键") or 窗归档键(窗号)
    if policy != POLICY_ARCHIVE:
        # 拒写形态没有归档键；保留键位但置空，避免调用方 KeyError。
        archive_key = None
    reason = str(data.get("拒因") or (DEFAULT_REASON if sealed else ""))
    policy_label = "双写两轨" if policy == POLICY_ARCHIVE else "切流账册封印拒写"
    result = {
        "窗号": 窗号,
        "window_id": 窗号,
        "封印态": state,
        "state": STATE_SEALED if sealed else STATE_OPEN,
        "是否封印": sealed,
        "封印": sealed,
        "sealed": sealed,
        "策略": policy,
        "写闸策略": policy,
        "policy": policy,
        "策略标签": policy_label,
        "写闸形态": policy_label,
        "拒因": reason if sealed else "",
        "reason": reason if sealed else "",
        "归档键": archive_key,
        "archive_key": archive_key,
        "valid": valid,
        "ok": valid,
        "允许写入现行": not sealed,
        "可写": not sealed,
        "writable": not sealed,
        "处置": ("拒写" if sealed and policy == POLICY_REJECT else
                "归档" if sealed and policy == POLICY_ARCHIVE else "放行"),
        "现行缓冲行数": int(active),
        "current_buffer_rows": int(active),
        "拒写笔数": int(rejected),
        "rejected_count": int(rejected),
        "归档笔数": int(archived),
        "archived_count": int(archived),
        "封印时刻": data.get("封印时刻", ""),
        "解封时刻": data.get("解封时刻", ""),
        "更新时刻": data.get("更新时刻", ""),
        "changed": False,
    }
    if torn:
        result["撕裂原因"] = f"封印窗仍有 {active} 行在缓冲"
    return result


def 写闸状态(
    窗号: str | None = None,
    conn=None,
    *,
    window_id: str | None = None,
    wid: str | None = None,
    **_kwargs: Any,
) -> dict:
    """只读写闸接口：窗号、封印态、拒因/归档键、valid。"""
    if 窗号 is None:
        窗号 = window_id or wid
    own_conn = conn is None
    if own_conn:
        conn = 连接()
    try:
        if 窗号 is None:
            窗号 = 当前窗号(conn)
        row = conn.execute(
            "SELECT * FROM 窗写闸账 WHERE 窗号=?", (窗号,)
        ).fetchone()
        return _状态从行(conn, 窗号, row)
    finally:
        if own_conn:
            conn.close()


# 题目用语别名。
写闸只读接口 = 写闸状态
只读接口 = 写闸状态
写闸接口 = 写闸状态
只读状态 = 写闸状态
封印状态 = 写闸状态
获取写闸 = 写闸状态
取写闸 = 写闸状态
写闸 = 写闸状态
gate_status = 写闸状态
get_gate = 写闸状态
write_gate_status = 写闸状态
状态 = 写闸状态


def 写闸校验(
    窗号: str | None = None,
    conn=None,
    *,
    window_id: str | None = None,
    **kwargs: Any,
) -> dict:
    """写闸完整性校验；``valid`` 与只读接口保持同一语义。

    是否允许写入现行缓冲请读 ``允许写入现行`` / ``可写``，避免把“封印有效”
    和“当前可写”混成同一个布尔值。
    """
    data = 写闸状态(窗号, conn, window_id=window_id, **kwargs)
    data["校验"] = "封印写闸完整性"
    data["校验通过"] = bool(data.get("valid"))
    data["写入放行"] = bool(data.get("允许写入现行"))
    data["write_allowed"] = bool(data.get("允许写入现行"))
    data["写入valid"] = bool(data.get("允许写入现行"))
    data["write_valid"] = bool(data.get("允许写入现行"))
    return data


校验写闸 = 写闸校验
检查写闸 = 写闸校验
gate_check = 写闸校验


def _回放归档账(conn, 窗号: str, now: str) -> tuple[int, list[str]]:
    """把封后归档幂等回放至现行缓冲；调用方必须已持有写闸锁/写事务。"""
    archives = conn.execute(
        "SELECT * FROM 封后归档 WHERE 窗号=? ORDER BY 入归档时, 归档键",
        (窗号,),
    ).fetchall()
    replayed = 0
    keys: list[str] = []
    for a in archives:
        exists = conn.execute(
            "SELECT 1 FROM 入窗缓冲 WHERE 事件编号=?",
            (a["事件编号"],),
        ).fetchone()
        if not exists:
            conn.execute(
                """INSERT INTO 入窗缓冲
                   (事件编号,运单键,网点键,事件时,窗号,命运,入缓冲时)
                   VALUES (?,?,?,?,?, '在缓冲', ?)""",
                (a["事件编号"], a["运单键"], a["网点键"], a["事件时"], 窗号, now),
            )
            replayed += 1
        keys.append(a["归档键"])
        conn.execute(
            "UPDATE 封后归档 SET 状态='已回放' WHERE 归档键=?",
            (a["归档键"],),
        )
    return replayed, keys


def 回放归档(
    窗号: str | None = None,
    *args: Any,
    window_id: str | None = None,
    conn=None,
    **_kwargs: Any,
) -> dict:
    """显式回放归档；并发调用时至多一个调用产生新的现行缓冲行。"""
    if 窗号 is None:
        窗号 = window_id
    with 写闸锁:
        own_conn = conn is None
        if own_conn:
            conn = 连接()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if 窗号 is None:
                窗号 = 当前窗号(conn)
            now = 此刻()
            replayed, keys = _回放归档账(conn, 窗号, now)
            changed = replayed > 0
            if changed:
                import json
                batch = f"回放-{uuid.uuid4().hex[:8]}"
                report = {"窗号": 窗号, "重放行数": replayed, "归档键": keys, "时刻": now}
                conn.execute(
                    "INSERT INTO 解封批次(编号,窗号,时刻,回放行数,报告) VALUES (?,?,?,?,?)",
                    (batch, 窗号, now, replayed, json.dumps(report, ensure_ascii=False)),
                )
            result = _状态从行(
                conn, 窗号,
                conn.execute("SELECT * FROM 窗写闸账 WHERE 窗号=?", (窗号,)).fetchone(),
            )
            result.update({
                "changed": changed,
                "成功": changed,
                "winner": changed,
                "重放行数": replayed,
                "回放行数": replayed,
                "replayed": replayed,
                "replay_count": replayed,
            })
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            if own_conn:
                conn.close()


重放归档 = 回放归档
归档回放 = 回放归档
replay_archive = 回放归档


def 解封并回放(窗号: str | None = None, **kwargs: Any) -> dict:
    kwargs["重放归档"] = True
    return 解封窗(窗号, **kwargs)


def 解封窗(
    窗号: str | None = None,
    重放归档: bool | None = None,
    回放: bool | None = None,
    *args: Any,
    重放: bool | None = None,
    replay: bool | None = None,
    window_id: str | None = None,
    conn=None,
    **_kwargs: Any,
) -> dict:
    """CAS 解封；并发调用只有一个 changed=True，因此归档回放不会双写现行。"""
    if 窗号 is None:
        窗号 = window_id
    if 重放归档 is None:
        重放归档 = True
    if 回放 is None:
        回放 = 重放 if 重放 is not None else replay
    should_replay = bool(重放归档) if 回放 is None else bool(回放)
    if args and conn is None:
        # 兼容极少量位置连接写法：解封窗(窗号, True, some_conn)。
        conn = next((a for a in args if hasattr(a, "execute")), None)
    with 写闸锁:
        own_conn = conn is None
        if own_conn:
            conn = 连接()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if 窗号 is None:
                窗号 = 当前窗号(conn)
            row = conn.execute(
                "SELECT * FROM 窗写闸账 WHERE 窗号=?", (窗号,)
            ).fetchone()
            if row is None or row["封印态"] != STATE_SEALED:
                result = _状态从行(conn, 窗号, row)
                result.update({
                    "changed": False,
                    "成功": False,
                    "winner": False,
                    "解封": 0,
                    "重放行数": 0,
                    "回放行数": 0,
                    "replayed": 0,
                    "replay_count": 0,
                })
                conn.commit()
                return result

            now = 此刻()
            cur = conn.execute(
                """UPDATE 窗写闸账
                   SET 封印态=?, 解封时刻=?, 更新时刻=?, valid=1
                   WHERE 窗号=? AND 封印态=?""",
                (STATE_OPEN, now, now, 窗号, STATE_SEALED),
            )
            changed = cur.rowcount == 1
            replayed = 0
            replay_keys: list[str] = []
            if changed:
                conn.execute(
                    """INSERT INTO 窗规(键,值) VALUES ('封印态',?)
                       ON CONFLICT(键) DO UPDATE SET 值=excluded.值""",
                    (STATE_OPEN,),
                )
                if should_replay:
                    replayed, replay_keys = _回放归档账(conn, 窗号, now)
                batch = f"解封-{uuid.uuid4().hex[:8]}"
                import json
                report = {"窗号": 窗号, "changed": True, "重放归档": should_replay,
                          "重放行数": replayed, "归档键": replay_keys, "时刻": now}
                conn.execute(
                    "INSERT INTO 解封批次(编号,窗号,时刻,回放行数,报告) VALUES (?,?,?,?,?)",
                    (batch, 窗号, now, replayed, json.dumps(report, ensure_ascii=False)),
                )

            result = _状态从行(
                conn, 窗号,
                conn.execute("SELECT * FROM 窗写闸账 WHERE 窗号=?", (窗号,)).fetchone(),
            )
            result.update({
                "changed": changed,
                "成功": changed,
                "winner": changed,
                "解封": 1 if changed else 0,
                "重放行数": replayed,
                "回放行数": replayed,
                "replayed": replayed,
                "replay_count": replayed,
            })
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            if own_conn:
                conn.close()


解封 = 解封窗
解封写闸 = 解封窗
解封窗口 = 解封窗
解除封印 = 解封窗
unseal = 解封窗
release_seal = 解封窗
unlock_window = 解封窗


def 封印窗(
    窗号: str | None = None,
    策略: str | None = None,
    *args: Any,
    policy: str | None = None,
    window_id: str | None = None,
    conn=None,
    **_kwargs: Any,
) -> dict:
    """低层 CAS 封印；正常编排应走 关窗.关当前窗 以同时物化缓冲。"""
    if 窗号 is None:
        窗号 = window_id
    if 策略 is None:
        策略 = policy
    if args and conn is None:
        conn = next((a for a in args if hasattr(a, "execute")), None)
    with 写闸锁:
        own_conn = conn is None
        if own_conn:
            conn = 连接()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if 窗号 is None:
                窗号 = 当前窗号(conn)
            policy = 规范策略(策略 or 规则策略(窗规映射(conn)))
            确保写闸账(conn, 窗号, policy)
            now = 此刻()
            cur = conn.execute(
                """UPDATE 窗写闸账
                   SET 封印态=?, 策略=?, 拒因=?, 归档键=?, valid=1,
                       封印时刻=?, 更新时刻=?
                   WHERE 窗号=? AND 封印态<>?""",
                (STATE_SEALED, policy, DEFAULT_REASON, 窗归档键(窗号), now, now,
                 窗号, STATE_SEALED),
            )
            changed = cur.rowcount == 1
            if changed:
                for k, v in {"封印态": STATE_SEALED, "封印窗号": 窗号, "封印时刻": now}.items():
                    conn.execute(
                        """INSERT INTO 窗规(键,值) VALUES (?,?)
                           ON CONFLICT(键) DO UPDATE SET 值=excluded.值""",
                        (k, v),
                    )
            result = _状态从行(
                conn, 窗号,
                conn.execute("SELECT * FROM 窗写闸账 WHERE 窗号=?", (窗号,)).fetchone(),
            )
            result.update({"changed": changed, "封印": 1 if changed else 0})
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            if own_conn:
                conn.close()


封印写闸 = 封印窗
关窗封印 = 封印窗
关窗封印写闸 = 封印窗
封印当前窗 = 封印窗
seal = 封印窗
seal_window = 封印窗


def before_load(batch: dict) -> dict:
    """装载前：可改批次或抛出预检错误。默认透传。"""
    return batch


def after_load(report: dict) -> dict:
    """装载后：可附加旁路统计。默认透传。"""
    return report


def decide_window(event: dict, rules: dict) -> str:
    """返回 入缓冲 / 迟到 / 驳回。基线默认由装载服务按事件时判定。"""
    return "入缓冲"


def before_close(window_id: str) -> None:
    """关窗前检查，可抛错阻断。"""
    return None


def after_close(report: dict) -> dict:
    """关窗后处理，例如推进下一窗。默认透传。"""
    return report


def extra_verify_checks(snapshot: dict | None = None) -> list[str]:
    """附加贯验检查：所有已封印窗不得仍有现行在缓冲行。"""
    conn = 连接()
    try:
        errors: list[str] = []
        checked: set[str] = set()
        gate_rows = conn.execute(
            "SELECT 窗号, 封印态, valid FROM 窗写闸账"
        ).fetchall()
        gate_map = {r["窗号"]: r for r in gate_rows}
        sealed_windows = [
            r["窗号"] for r in gate_rows if r["封印态"] == STATE_SEALED
        ]

        # 窗规封印也是权威来源；兼容只改窗规或写闸账尚未落票的路径。
        rules = 窗规映射(conn)
        current = 当前窗号(conn)
        rule_sealed_window: str | None = None
        if 规则已封印(rules, current):
            rule_sealed_window = str(
                rules.get("封印窗号") or rules.get("封窗号") or current
            )
            sealed_windows.append(rule_sealed_window)

        for wid in sealed_windows:
            if not wid or wid in checked:
                continue
            checked.add(wid)
            gate = gate_map.get(wid)
            if gate is None:
                errors.append(f"封印窗 {wid} 缺少同票写闸账，封印不完整")
            elif gate["封印态"] == STATE_SEALED and not int(gate["valid"] or 0):
                errors.append(f"封印窗 {wid} 写闸账 valid=false")
            n = conn.execute(
                "SELECT COUNT(*) AS c FROM 入窗缓冲 WHERE 窗号=? AND 命运='在缓冲'",
                (wid,),
            ).fetchone()["c"]
            if n:
                errors.append(f"封印窗 {wid} 仍有 {n} 行在缓冲，写闸被绕过")

        if rule_sealed_window:
            gate = gate_map.get(rule_sealed_window)
            if gate is not None and gate["封印态"] != STATE_SEALED:
                errors.append(
                    f"窗规记载 {rule_sealed_window} 已封印，但写闸账为 {gate['封印态']}"
                )
        return errors
    except sqlite3.OperationalError as e:  # 旧库尚未迁移写闸表时不应假绿
        if "no such table" in str(e):
            return ["写闸账表缺失，无法验证封印"]
        raise
    finally:
        conn.close()
