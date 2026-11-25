from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from pathlib import Path
from app.services import 目录, 装载, 关窗, 贯验, 夹具, 统计, 说明
from app.modules.关窗封印写闸 import (
    NAME as 写闸名,
    describe as 写闸描述,
    写闸状态,
    写闸校验,
    解封窗,
    封印窗,
    回放归档,
)


async def api_概览(request: Request):
    return JSONResponse(目录.概览())


async def api_仓情(request: Request):
    return JSONResponse(说明.仓情())


async def api_窗规_get(request: Request):
    return JSONResponse(目录.窗规())


async def api_窗规_post(request: Request):
    body = await request.json()
    return JSONResponse(目录.改窗规(body))


async def api_网点(request: Request):
    return JSONResponse(目录.网点列表())


async def api_观测(request: Request):
    return JSONResponse(目录.观测列表())


async def api_缓冲(request: Request):
    q = request.query_params
    窗号 = q.get("窗号") or q.get("window_id")
    命运 = q.get("命运") or q.get("fate")
    现行参数 = q.get("仅现行") or q.get("现行") or q.get("current") or q.get("active")
    仅现行 = str(现行参数 or "").strip().lower() in {
        "1", "true", "yes", "y", "是", "仅现行", "现行", "在缓冲"
    }
    rows = 目录.缓冲列表(窗号, 仅现行=仅现行)
    if 命运:
        rows = [r for r in rows if r.get("命运") == 命运]
    return JSONResponse(rows)


async def api_写闸(request: Request):
    窗号 = request.query_params.get("窗号") or request.query_params.get("window_id")
    return JSONResponse(写闸状态(窗号))


async def api_写闸解封(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    窗号 = body.get("窗号") or body.get("window_id") or request.query_params.get("窗号") or request.query_params.get("window_id")
    回放键 = next((k for k in ("重放归档", "回放", "重放", "replay") if k in body), None)
    if 回放键 is None:
        回放键 = next((k for k in ("重放归档", "回放", "重放", "replay") if k in request.query_params), None)
        重放 = True if 回放键 is None else str(request.query_params.get(回放键)).lower() in {"1", "true", "yes", "是"}
    else:
        重放 = bool(body.get(回放键))
    return JSONResponse(解封窗(窗号, 重放归档=重放))


async def api_写闸封印(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    窗号 = body.get("窗号") or body.get("window_id") or request.query_params.get("窗号")
    策略 = body.get("策略") or body.get("写闸策略") or body.get("policy") or request.query_params.get("策略")
    return JSONResponse(封印窗(窗号, 策略))


async def api_归档回放(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body or {}
    窗号 = body.get("窗号") or body.get("window_id") or request.query_params.get("窗号")
    return JSONResponse(回放归档(窗号))


async def api_写闸校验(request: Request):
    窗号 = request.query_params.get("窗号") or request.query_params.get("window_id")
    return JSONResponse(写闸校验(窗号))


async def api_封印拒写账(request: Request):
    窗号 = request.query_params.get("窗号")
    return JSONResponse(目录.封印拒写列表(窗号))


async def api_封后归档(request: Request):
    q = request.query_params
    窗号 = q.get("窗号") or q.get("window_id")
    rows = 目录.封后归档列表(窗号)
    键 = q.get("归档键") or q.get("archive_key") or q.get("key")
    if 键:
        rows = [
            r for r in rows
            if r.get("归档键") == 键
            or r.get("归档账键") == 键
            or r.get("window_archive_key") == 键
        ]
    return JSONResponse(rows)


async def api_切片(request: Request):
    return JSONResponse(目录.切片列表())


async def api_迟到(request: Request):
    return JSONResponse(目录.迟到列表())


async def api_贯验列表(request: Request):
    return JSONResponse(目录.贯验列表())


async def api_夹具(request: Request):
    return JSONResponse(夹具.列表())


async def api_装载(request: Request):
    body = await request.json()
    return JSONResponse(装载.装一批(body))


async def api_夹具装载(request: Request):
    名 = request.path_params["name"]
    try:
        return JSONResponse(装载.装一批(夹具.读取(名)))
    except FileNotFoundError:
        return JSONResponse({"错误": 名}, status_code=404)


async def api_关窗(request: Request):
    return JSONResponse(关窗.关当前窗())


async def api_贯验(request: Request):
    return JSONResponse(贯验.跑一次())


async def api_统计观测(request: Request):
    return JSONResponse(统计.观测命运())


async def api_统计缓冲(request: Request):
    return JSONResponse(统计.缓冲命运())


async def api_空桩(request: Request):
    root = Path(__file__).resolve().parents[1] / "modules"
    out = []
    if root.is_dir():
        for p in sorted(root.iterdir()):
            if p.is_dir() and p.name != "__pycache__" and (p / "__init__.py").is_file():
                out.append(p.name)
    return JSONResponse({"空桩": out, "条数": len(out)})


async def api_空桩详情(request: Request):
    名 = request.path_params.get("name", "")
    if 名 in (写闸名, "封印写闸", "写闸"):
        窗号 = request.query_params.get("窗号") or request.query_params.get("window_id")
        data = 写闸描述()
        data["写闸"] = 写闸状态(窗号)
        data["写闸只读接口"] = data["写闸"]
        return JSONResponse(data)
    return JSONResponse({"错误": f"未实现详情：{名}"}, status_code=404)


路由表 = [
    Route("/api/概览", api_概览),
    Route("/api/仓情", api_仓情),
    Route("/api/窗规", api_窗规_get, methods=["GET"]),
    Route("/api/窗规", api_窗规_post, methods=["POST"]),
    Route("/api/窗规/写闸", api_写闸),
    Route("/api/窗规写闸", api_写闸),
    Route("/api/网点源", api_网点),
    Route("/api/观测点", api_观测),
    Route("/api/入窗缓冲", api_缓冲),
    Route("/api/缓冲", api_缓冲),
    Route("/api/写缓冲", api_缓冲),
    Route("/api/现行缓冲", api_缓冲),
    Route("/api/入窗缓冲/现行", api_缓冲),
    Route("/api/写闸", api_写闸),
    Route("/api/gate", api_写闸),
    Route("/api/write-gate", api_写闸),
    Route("/api/write_gate", api_写闸),
    Route("/api/写闸状态", api_写闸),
    Route("/api/写闸只读接口", api_写闸),
    Route("/api/写闸/状态", api_写闸),
    Route("/api/写闸/status", api_写闸),
    Route("/api/写闸/只读", api_写闸),
    Route("/api/写闸/read", api_写闸),
    Route("/api/写闸/只读接口", api_写闸),
    Route("/api/写闸/校验", api_写闸校验),
    Route("/api/写闸/check", api_写闸校验),
    Route("/api/写闸/封印", api_写闸封印, methods=["POST"]),
    Route("/api/写闸/seal", api_写闸封印, methods=["POST"]),
    Route("/api/关窗封印写闸", api_写闸),
    Route("/api/关窗封印写闸/状态", api_写闸),
    Route("/api/关窗封印写闸/status", api_写闸),
    Route("/api/关窗封印写闸/只读", api_写闸),
    Route("/api/关窗封印写闸/只读接口", api_写闸),
    Route("/api/关窗封印写闸/封印", api_写闸封印, methods=["POST"]),
    Route("/api/关窗封印写闸/解封", api_写闸解封, methods=["POST"]),
    Route("/api/封印写闸", api_写闸),
    Route("/api/封印写闸/状态", api_写闸),
    Route("/api/封印写闸/只读", api_写闸),
    Route("/api/封印写闸/只读接口", api_写闸),
    Route("/api/封印写闸/封印", api_写闸封印, methods=["POST"]),
    Route("/api/封印写闸/seal", api_写闸封印, methods=["POST"]),
    Route("/api/写闸/解封", api_写闸解封, methods=["POST"]),
    Route("/api/写闸/unseal", api_写闸解封, methods=["POST"]),
    Route("/api/写闸/回放", api_归档回放, methods=["POST"]),
    Route("/api/写闸/replay", api_归档回放, methods=["POST"]),
    Route("/api/归档/回放", api_归档回放, methods=["POST"]),
    Route("/api/封后归档/回放", api_归档回放, methods=["POST"]),
    Route("/api/封印写闸/解封", api_写闸解封, methods=["POST"]),
    Route("/api/封印写闸/unseal", api_写闸解封, methods=["POST"]),
    Route("/api/关窗/解封", api_写闸解封, methods=["POST"]),
    Route("/api/关窗/封印", api_写闸封印, methods=["POST"]),
    Route("/api/关窗封印写闸/unseal", api_写闸解封, methods=["POST"]),
    Route("/api/封印拒写账", api_封印拒写账),
    Route("/api/封印拒写", api_封印拒写账),
    Route("/api/拒写账", api_封印拒写账),
    Route("/api/封后归档", api_封后归档),
    Route("/api/封后缓冲", api_封后归档),
    Route("/api/归档列表", api_封后归档),
    Route("/api/写闸归档", api_封后归档),
    Route("/api/归档", api_封后归档),
    Route("/api/窗切片账", api_切片),
    Route("/api/切片", api_切片),
    Route("/api/迟到匣", api_迟到),
    Route("/api/窗贯验", api_贯验列表),
    Route("/api/贯验", api_贯验列表),
    Route("/api/夹具", api_夹具),
    Route("/api/装载", api_装载, methods=["POST"]),
    Route("/api/观测点/装载", api_装载, methods=["POST"]),
    Route("/api/观测点/夹具/{name}", api_夹具装载, methods=["POST"]),
    Route("/api/关窗", api_关窗, methods=["POST"]),
    Route("/api/关窗/跑", api_关窗, methods=["POST"]),
    Route("/api/贯验/跑", api_贯验, methods=["POST"]),
    Route("/api/窗贯验/跑", api_贯验, methods=["POST"]),
    Route("/api/统计/观测命运", api_统计观测),
    Route("/api/统计/缓冲命运", api_统计缓冲),
    Route("/api/空桩", api_空桩),
    Route("/api/空桩/{name}", api_空桩详情),
]
