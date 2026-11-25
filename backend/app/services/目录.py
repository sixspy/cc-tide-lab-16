"""列表与窗规读写。"""
from __future__ import annotations
from app.db import 连接


def 窗规() -> dict:
    conn = 连接()
    try:
        rows = conn.execute("SELECT 键,值 FROM 窗规").fetchall()
        return {r["键"]: r["值"] for r in rows}
    finally:
        conn.close()


def 改窗规(体: dict) -> dict:
    conn = 连接()
    try:
        for k, v in (体 or {}).items():
            conn.execute(
                "INSERT INTO 窗规(键,值) VALUES (?,?) ON CONFLICT(键) DO UPDATE SET 值=excluded.值",
                (str(k), str(v)),
            )
        策略补丁 = next((体[k] for k in ("写闸策略", "封印策略", "写闸形态", "封印形态", "拒写形态") if k in 体), None)
        if 策略补丁 is not None:
            from app.modules.关窗封印写闸 import 规范策略

            wid_row = conn.execute(
                "SELECT 值 FROM 窗规 WHERE 键='当前窗号'"
            ).fetchone()
            if wid_row:
                policy = 规范策略(策略补丁)
                conn.execute(
                    """UPDATE 窗写闸账 SET 策略=?
                       WHERE 窗号=? AND 封印态='未封印'""",
                    (policy, wid_row["值"]),
                )
                conn.execute(
                    "INSERT INTO 窗规(键,值) VALUES ('写闸策略',?) ON CONFLICT(键) DO UPDATE SET 值=excluded.值",
                    (policy,),
                )
        conn.commit()
        return 窗规()
    finally:
        conn.close()


def 网点列表() -> list[dict]:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 网点源 ORDER BY 源键").fetchall()]
    finally:
        conn.close()


def 观测列表() -> list[dict]:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 观测点 ORDER BY 事件时 DESC LIMIT 200").fetchall()]
    finally:
        conn.close()


def 缓冲列表(
    窗号: str | None = None,
    仅现行: bool = False,
    **kwargs,
) -> list[dict]:
    窗号 = 窗号 or kwargs.get("window_id")
    if not 仅现行:
        仅现行 = bool(
            kwargs.get("现行") or kwargs.get("current") or kwargs.get("active")
        )
    conn = 连接()
    try:
        sql = "SELECT * FROM 入窗缓冲"
        where = []
        args: list = []
        if 窗号:
            where.append("窗号=?")
            args.append(窗号)
        if 仅现行:
            where.append("命运='在缓冲'")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY 事件时"
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def 现行缓冲列表(窗号: str | None = None) -> list[dict]:
    return 缓冲列表(窗号, 仅现行=True)


当前缓冲列表 = 现行缓冲列表


def 切片列表(窗号: str | None = None) -> list[dict]:
    conn = 连接()
    try:
        if 窗号:
            rows = conn.execute(
                "SELECT * FROM 窗切片账 WHERE 窗号=? ORDER BY 物化时 DESC LIMIT 200",
                (窗号,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM 窗切片账 ORDER BY 物化时 DESC LIMIT 200").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def 迟到列表() -> list[dict]:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 迟到匣 ORDER BY 编号 DESC LIMIT 200").fetchall()]
    finally:
        conn.close()


def 贯验列表() -> list[dict]:
    conn = 连接()
    try:
        rows = conn.execute("SELECT * FROM 窗贯验 ORDER BY 编号 DESC LIMIT 50").fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["是否对齐"] = bool(item.get("是否对齐"))
            item["valid"] = item["是否对齐"]
            out.append(item)
        return out
    finally:
        conn.close()


def 写闸列表() -> list[dict]:
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 窗写闸账 ORDER BY 窗号").fetchall()]
    finally:
        conn.close()


def 写闸状态(窗号: str | None = None) -> dict:
    from app.modules.关窗封印写闸 import 写闸状态 as _状态

    return _状态(窗号)


写闸只读接口 = 写闸状态
获取写闸 = 写闸状态


def 封印拒写列表(窗号: str | None = None) -> list[dict]:
    conn = 连接()
    try:
        if 窗号:
            rows = conn.execute(
                "SELECT * FROM 封印拒写账 WHERE 窗号=? ORDER BY 编号 DESC LIMIT 200",
                (窗号,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM 封印拒写账 ORDER BY 编号 DESC LIMIT 200"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def 封后归档列表(窗号: str | None = None) -> list[dict]:
    from app.modules.关窗封印写闸 import 窗归档键

    conn = 连接()
    try:
        if 窗号:
            rows = conn.execute(
                "SELECT * FROM 封后归档 WHERE 窗号=? ORDER BY 入归档时 DESC, 归档键 DESC LIMIT 200",
                (窗号,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM 封后归档 ORDER BY 入归档时 DESC, 归档键 DESC LIMIT 200"
            ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            book_key = 窗归档键(item["窗号"])
            # 行级归档键保证幂等；账册键对应写闸只读接口给出的窗口归档引用。
            item["归档账键"] = book_key
            item["账册键"] = book_key
            item["window_archive_key"] = book_key
            out.append(item)
        return out
    finally:
        conn.close()


# 双写两轨的另一轨可读“封后缓冲”，但它与只读归档是同一引用，不是现行缓冲。
封后缓冲列表 = 封后归档列表
归档列表 = 封后归档列表


def 概览() -> dict:
    conn = 连接()
    try:
        return {
            "观测点": conn.execute("SELECT COUNT(*) AS c FROM 观测点").fetchone()["c"],
            "在缓冲": conn.execute("SELECT COUNT(*) AS c FROM 入窗缓冲 WHERE 命运='在缓冲'").fetchone()["c"],
            "窗切片": conn.execute("SELECT COUNT(*) AS c FROM 窗切片账").fetchone()["c"],
            "迟到": conn.execute("SELECT COUNT(*) AS c FROM 迟到匣").fetchone()["c"],
            "窗规": 窗规(),
        }
    finally:
        conn.close()
