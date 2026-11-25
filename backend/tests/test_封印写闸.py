"""关窗封印写闸的红绿测试。"""
from __future__ import annotations

import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="tide-seal-")
os.environ["数据目录"] = _tmp
os.environ["夹具目录"] = str(Path(__file__).resolve().parents[2] / "fixtures")

import pytest

from app.db import 库路径
from app import seed
from app.modules.关窗封印写闸 import 写闸状态, 写闸校验, 解封窗, 回放归档
from app.services import 装载, 关窗, 贯验, 目录


@pytest.fixture(autouse=True)
def 新库():
    if 库路径.exists():
        库路径.unlink()
    seed.初始化库()
    yield


def teardown_module(module):
    """本模块收尾后留下未封印新库，避免同进程追加运行隐藏用例时吃到封印态。"""
    if 库路径.exists():
        库路径.unlink()
    seed.初始化库()


def _封前成片并关窗(策略: str = "切流拒写"):
    目录.改窗规({"写闸策略": 策略})
    报告 = 装载.装一批({
        "批次编号": "seal-before",
        "事件": [
            {"事件编号": "seal-e1", "运单键": "运单-封甲", "网点键": "网点-东站",
             "事件时": "2026-11-24T00:10:00Z"},
            {"事件编号": "seal-e2", "运单键": "运单-封甲", "网点键": "网点-西港",
             "事件时": "2026-11-24T00:20:00Z"},
            {"事件编号": "seal-e3", "运单键": "运单-封乙", "网点键": "网点-北仓",
             "事件时": "2026-11-24T00:30:00Z"},
        ],
    })
    assert 报告["入缓冲"] == 3
    关报 = 关窗.关当前窗()
    assert 关报["成片数"] == 2
    return 目录.窗规()["当前窗号"]


def _切片集(窗号: str):
    return sorted(
        (r["切片编号"], r["窗号"], r["运单键"], r["事件数"])
        for r in 目录.切片列表() if r["窗号"] == 窗号
    )


def test_封印状态只读接口四要素():
    窗号 = _封前成片并关窗()
    闸 = 写闸状态(窗号)
    assert 闸["窗号"] == 窗号
    assert 闸["封印态"] == "已封印"
    assert 闸["拒因"]
    assert "归档键" in 闸
    assert 闸["valid"] is True
    校验 = 写闸校验(窗号)
    assert 校验["valid"] is True
    assert 校验["write_valid"] is False


def test_切流拒写_封后灌入不增现行缓冲且切片集不变():
    窗号 = _封前成片并关窗("切流拒写")
    前_全部缓冲 = 目录.缓冲列表()
    前_现行 = [r for r in 前_全部缓冲 if r["命运"] == "在缓冲"]
    前_切片 = _切片集(窗号)

    报告 = 装载.装一批({
        "批次编号": "seal-after-reject",
        "事件": [{
            "事件编号": "seal-late-write",
            "运单键": "运单-封丙",
            "网点键": "网点-东站",
            "事件时": "2026-11-24T00:40:00Z",
        }],
    })

    assert 报告["入缓冲"] == 0
    assert 报告["封印拒写"] == 1
    assert 报告["明细"][-1]["命运"] == "封印拒写"
    assert 报告["明细"][-1]["拒因"]
    后_全部缓冲 = 目录.缓冲列表()
    assert len(后_全部缓冲) == len(前_全部缓冲)
    assert [r for r in 后_全部缓冲 if r["命运"] == "在缓冲"] == 前_现行
    assert _切片集(窗号) == 前_切片

    闸 = 写闸状态(窗号)
    assert 闸["封印态"] == "已封印"
    assert "已封窗" in 闸["拒因"]
    assert 闸["valid"] is True

    验 = 贯验.跑一次()
    assert 验["是否对齐"] is True
    assert _切片集(窗号) == 前_切片


def test_双写归档_封后写入归档但现行缓冲不涨():
    窗号 = _封前成片并关窗("双写归档")
    前_缓冲 = len(目录.缓冲列表())
    前_现行 = 目录.概览()["在缓冲"]
    前_切片 = _切片集(窗号)

    报告 = 装载.装一批({
        "批次编号": "seal-after-archive",
        "事件": [{
            "事件编号": "seal-archive-1",
            "运单键": "运单-封丁",
            "网点键": "网点-西港",
            "事件时": "2026-11-24T00:45:00Z",
        }],
    })

    assert 报告["入缓冲"] == 0
    assert 报告["封后归档"] == 1
    assert len(目录.缓冲列表()) == 前_缓冲
    assert 目录.概览()["在缓冲"] == 前_现行
    闸 = 写闸状态(窗号)
    assert 闸["封印态"] == "已封印"
    assert 闸["归档键"]
    assert 闸["valid"] is True
    assert len(目录.封后归档列表(窗号)) == 1
    归档行 = 目录.封后归档列表(窗号)[0]
    assert 闸["归档键"] == 归档行["归档账键"]
    assert _切片集(窗号) == 前_切片
    assert 贯验.跑一次()["是否对齐"] is True


def test_并发首次关窗只物化一次():
    窗号 = "W-demo"
    装载.装一批({
        "事件": [
            {"事件编号": "race-close-1", "运单键": "运单-竞速甲", "网点键": "网点-东站",
             "事件时": "2026-11-24T00:11:00Z"},
            {"事件编号": "race-close-2", "运单键": "运单-竞速乙", "网点键": "网点-西港",
             "事件时": "2026-11-24T00:22:00Z"},
        ],
    })

    with ThreadPoolExecutor(max_workers=8) as pool:
        结果 = list(pool.map(lambda _: 关窗.关当前窗(), range(8)))

    assert len(_切片集(窗号)) == 2
    assert sum(r.get("changed") is True for r in 结果) == 1
    assert sum(r.get("成片数") == 2 for r in 结果) >= 1


def test_并发关窗只物化一次():
    窗号 = _封前成片并关窗()  # 已关一次；再并发调用不得重复物化
    前_切片 = _切片集(窗号)

    with ThreadPoolExecutor(max_workers=8) as pool:
        结果 = list(pool.map(lambda _: 关窗.关当前窗(), range(8)))

    assert _切片集(窗号) == 前_切片
    assert sum(1 for r in 结果 if r.get("changed", True)) <= 1


def test_并发解封与归档回放不得双写现行():
    窗号 = _封前成片并关窗("双写归档")
    装载.装一批({
        "事件": [{
            "事件编号": "seal-archive-race",
            "运单键": "运单-竞赛",
            "网点键": "网点-东站",
            "事件时": "2026-11-24T00:48:00Z",
        }],
    })
    assert len(目录.封后归档列表(窗号)) == 1

    # 第一次并发解封：只有一个调用完成状态翻转。
    with ThreadPoolExecutor(max_workers=8) as pool:
        解果 = list(pool.map(lambda _: 解封窗(窗号), range(8)))
    assert sum(1 for r in 解果 if r.get("changed") is True) == 1
    assert 写闸状态(窗号)["封印态"] == "未封印"

    # 再次封窗后并发回放归档：现行缓冲每个归档事件至多一行。
    关窗.关当前窗()
    with ThreadPoolExecutor(max_workers=8) as pool:
        放果 = list(pool.map(lambda _: 解封窗(窗号, 重放归档=True), range(8)))
    assert sum(1 for r in 放果 if r.get("changed") is True) == 1
    现行 = [r for r in 目录.缓冲列表() if r["事件编号"] == "seal-archive-race"]
    assert len(现行) == 1


def test_并发归档回放至多一行现行():
    窗号 = _封前成片并关窗("双写归档")
    装载.装一批({
        "事件": [{
            "事件编号": "seal-replay-race",
            "运单键": "运单-回放",
            "网点键": "网点-东站",
            "事件时": "2026-11-24T00:49:00Z",
        }],
    })
    解封窗(窗号, 重放归档=False)

    with ThreadPoolExecutor(max_workers=8) as pool:
        果 = list(pool.map(lambda _: 回放归档(窗号), range(8)))

    rows = [r for r in 目录.缓冲列表(窗号) if r["事件编号"] == "seal-replay-race"]
    assert len(rows) == 1
    assert sum(1 for r in 果 if r.get("changed") is True) == 1
    assert sum(int(r.get("回放行数") or 0) for r in 果) == 1


def test_封印窗有偷渡现行缓冲时贯验变红():
    窗号 = _封前成片并关窗()
    conn = __import__("app.db", fromlist=["连接"]).连接()
    try:
        conn.execute(
            """INSERT INTO 入窗缓冲(事件编号,运单键,网点键,事件时,窗号,命运,入缓冲时)
               VALUES ('smuggle-1','运单-偷渡','网点-东站','2026-11-24T00:50:00Z',?,'在缓冲','x')""",
            (窗号,),
        )
        conn.commit()
    finally:
        conn.close()

    验 = 贯验.跑一次()
    assert 验["是否对齐"] is False
    assert any(窗号 in e and "在缓冲" in e for e in 验["写闸错误"])


def test_并发同事件封后灌入不双写():
    窗号 = _封前成片并关窗()
    体 = {
        "批次编号": "seal-race-same",
        "事件": [{
            "事件编号": "seal-same-race",
            "运单键": "运单-同号",
            "网点键": "网点-东站",
            "事件时": "2026-11-24T00:41:00Z",
        }],
    }
    前 = len(目录.缓冲列表(窗号))
    with ThreadPoolExecutor(max_workers=8) as pool:
        结果 = list(pool.map(lambda _: 装载.装一批(体), range(8)))

    assert len(目录.缓冲列表(窗号)) == 前
    assert sum(r["封印拒写"] for r in 结果) == 1
    assert sum(r["驳回"] for r in 结果) == 8
    assert len(目录.封印拒写列表(窗号)) == 1


def test_写闸_http只读接口含约定字段():
    from starlette.testclient import TestClient
    from app.main import app

    窗号 = _封前成片并关窗()
    with TestClient(app) as client:
        resp = client.get(f"/api/写闸?窗号={窗号}")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("窗号", "封印态", "拒因", "归档键", "valid"):
        assert key in data
