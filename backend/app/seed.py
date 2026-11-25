from datetime import datetime, timezone
from app.db import 连接

建表 = """
CREATE TABLE IF NOT EXISTS 窗规 (
  键 TEXT PRIMARY KEY,
  值 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 网点源 (
  源键 TEXT PRIMARY KEY,
  名称 TEXT NOT NULL,
  区域 TEXT NOT NULL DEFAULT '',
  说明 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 观测点 (
  事件编号 TEXT PRIMARY KEY,
  运单键 TEXT NOT NULL,
  网点键 TEXT NOT NULL,
  事件时 TEXT NOT NULL,
  处理时 TEXT NOT NULL,
  命运 TEXT NOT NULL DEFAULT '已装载',
  批次编号 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 入窗缓冲 (
  事件编号 TEXT PRIMARY KEY,
  运单键 TEXT NOT NULL,
  网点键 TEXT NOT NULL,
  事件时 TEXT NOT NULL,
  窗号 TEXT NOT NULL,
  命运 TEXT NOT NULL DEFAULT '在缓冲',
  入缓冲时 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 窗切片账 (
  切片编号 TEXT PRIMARY KEY,
  窗号 TEXT NOT NULL,
  运单键 TEXT NOT NULL,
  事件数 INTEGER NOT NULL,
  窗起 TEXT NOT NULL,
  窗止 TEXT NOT NULL,
  物化时 TEXT NOT NULL,
  命运 TEXT NOT NULL DEFAULT '已成片'
);
CREATE TABLE IF NOT EXISTS 迟到匣 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  事件编号 TEXT NOT NULL,
  运单键 TEXT NOT NULL,
  原因 TEXT NOT NULL,
  事件时 TEXT NOT NULL,
  入匣时 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 窗贯验 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  时刻 TEXT NOT NULL,
  缓冲笔数 INTEGER NOT NULL,
  切片笔数 INTEGER NOT NULL,
  迟到笔数 INTEGER NOT NULL,
  是否对齐 INTEGER NOT NULL,
  说明 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 装载批次 (
  编号 TEXT PRIMARY KEY,
  时刻 TEXT NOT NULL,
  入流 INTEGER NOT NULL DEFAULT 0,
  入缓冲 INTEGER NOT NULL DEFAULT 0,
  迟到 INTEGER NOT NULL DEFAULT 0,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 关窗批次 (
  编号 TEXT PRIMARY KEY,
  窗号 TEXT NOT NULL,
  时刻 TEXT NOT NULL,
  成片数 INTEGER NOT NULL DEFAULT 0,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 窗写闸账 (
  窗号 TEXT PRIMARY KEY,
  封印态 TEXT NOT NULL DEFAULT '未封印',
  策略 TEXT NOT NULL DEFAULT '切流拒写',
  拒因 TEXT NOT NULL DEFAULT '',
  归档键 TEXT,
  valid INTEGER NOT NULL DEFAULT 1,
  封印时刻 TEXT NOT NULL DEFAULT '',
  解封时刻 TEXT NOT NULL DEFAULT '',
  更新时刻 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 封印拒写账 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  窗号 TEXT NOT NULL,
  事件编号 TEXT NOT NULL,
  批次编号 TEXT NOT NULL DEFAULT '',
  拒因 TEXT NOT NULL,
  事件时 TEXT NOT NULL DEFAULT '',
  时刻 TEXT NOT NULL,
  UNIQUE(窗号, 事件编号)
);
CREATE TABLE IF NOT EXISTS 封后归档 (
  归档键 TEXT PRIMARY KEY,
  窗号 TEXT NOT NULL,
  事件编号 TEXT NOT NULL UNIQUE,
  运单键 TEXT NOT NULL,
  网点键 TEXT NOT NULL,
  事件时 TEXT NOT NULL,
  批次编号 TEXT NOT NULL DEFAULT '',
  原因 TEXT NOT NULL DEFAULT '',
  状态 TEXT NOT NULL DEFAULT '只读归档',
  入归档时 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 解封批次 (
  编号 TEXT PRIMARY KEY,
  窗号 TEXT NOT NULL,
  时刻 TEXT NOT NULL,
  回放行数 INTEGER NOT NULL DEFAULT 0,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE VIEW IF NOT EXISTS 封后缓冲 AS SELECT * FROM 封后归档;
CREATE VIEW IF NOT EXISTS 封印拒写 AS SELECT * FROM 封印拒写账;
CREATE VIEW IF NOT EXISTS 写闸账 AS SELECT * FROM 窗写闸账;
CREATE VIEW IF NOT EXISTS 写闸状态视图 AS SELECT * FROM 窗写闸账;
"""


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def 初始化库() -> None:
    conn = 连接()
    conn.executescript(建表)
    if conn.execute("SELECT COUNT(*) AS c FROM 窗规").fetchone()["c"] == 0:
        for k, v in {
            "窗长秒": "3600",
            "允许迟到秒": "0",
            "关窗策略": "按事件时整点",
            "当前窗号": "W-demo",
            "窗起": "2026-11-24T00:00:00Z",
            "窗止": "2026-11-24T01:00:00Z",
            "写闸策略": "切流拒写",
            "封印态": "未封印",
        }.items():
            conn.execute("INSERT INTO 窗规(键,值) VALUES (?,?)", (k, v))
    else:
        for k, v in {
            "写闸策略": "切流拒写",
            "封印态": "未封印",
        }.items():
            conn.execute(
                "INSERT OR IGNORE INTO 窗规(键,值) VALUES (?,?)", (k, v)
            )
    当前窗号 = conn.execute(
        "SELECT 值 FROM 窗规 WHERE 键='当前窗号'"
    ).fetchone()
    if 当前窗号:
        conn.execute(
            """INSERT OR IGNORE INTO 窗写闸账
               (窗号,封印态,策略,拒因,归档键,valid,更新时刻)
               VALUES (?,?,?,?,?,1,?)""",
            (
                当前窗号["值"],
                "未封印",
                conn.execute("SELECT 值 FROM 窗规 WHERE 键='写闸策略'").fetchone()["值"],
                "",
                f"封后归档:{当前窗号['值']}",
                此刻(),
            ),
        )
    if conn.execute("SELECT COUNT(*) AS c FROM 网点源").fetchone()["c"] == 0:
        for row in [
            ("网点-东站", "东站分拨", "华东", "示范网点"),
            ("网点-西港", "西港分拨", "华东", "示范网点"),
            ("网点-北仓", "北仓分拨", "华北", "示范网点"),
        ]:
            conn.execute(
                "INSERT INTO 网点源(源键,名称,区域,说明) VALUES (?,?,?,?)", row
            )
    conn.commit()
    conn.close()
