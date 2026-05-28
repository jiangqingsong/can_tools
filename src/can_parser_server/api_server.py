import os
import sys
import json
import uuid
import time
import shutil
import threading
from pathlib import Path
from typing import Optional, Dict
from fastapi import FastAPI, File, UploadFile, Form, HTTPException

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR.parent))

from parsers import decode_asc, decode_blf, decode_csv

app = FastAPI(title="CAN Data Parser Service", version="2.0.0")
CONFIG_DIR = BASE_DIR / "config"
DBC_DIR = BASE_DIR / "dbc_files"
TEMP_DIR = "./temp_uploads"
os.makedirs(TEMP_DIR, exist_ok=True)

# 启动时加载模型配置
def _load_models_config() -> dict:
    config_path = CONFIG_DIR / "models_config.json"
    if not config_path.exists():
        print(f"[WARN] 模型配置文件不存在: {config_path}")
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    vehicles = config.get("vehicles", {})
    print(f"[INFO] 已加载模型配置，车型数: {len(vehicles)}")
    for v_name, v_info in vehicles.items():
        model_names = list(v_info.get("models", {}).keys())
        print(f"  - {v_name}: {model_names}")
    return vehicles

MODELS = _load_models_config()

# 并发控制
_semaphore = threading.Semaphore(4)
_task_store: Dict[str, dict] = {}
_task_lock = threading.Lock()


@app.post("/api/v1/parse")
async def parse(
    parser_type: str = Form(..., description="解析类型：asc, blf, csv"),
    batch_id: str = Form(..., description="批次标识"),
    data_file: UploadFile = File(..., description="数据文件（ASC/BLF/Excel/CSV）"),
    dbc_file: Optional[UploadFile] = File(default=None, description="DBC 描述文件（csv 类型不需要，使用 model_name 时可选）"),
    batch_size: int = Form(default=500000),
    signal_filter_list: Optional[str] = Form(default=None, description='JSON数组，如 ["VehicleSpeed"]'),
    vehicle_model: Optional[str] = Form(default=None, description="车型（如 C01、C11），配合 model_name 使用"),
    model_name: Optional[str] = Form(default=None, description="分析场景模型名称，配合 vehicle_model 使用"),
):
    parser_type = parser_type.lower()

    if parser_type == "asc":
        decode_fn = decode_asc
    elif parser_type == "blf":
        decode_fn = decode_blf
    elif parser_type == "csv":
        decode_fn = decode_csv
    else:
        raise HTTPException(status_code=400, detail=f"不支持的解析类型 '{parser_type}'，仅支持：asc, blf, csv")

    if not data_file.filename:
        raise HTTPException(status_code=400, detail="data_file 不能为空")

    # 解析信号过滤列表（从参数或模型配置）
    signals = None
    model_dbc_files = None  # 从模型配置解析出的 DBC 文件路径列表

    if model_name:
        # ---- 使用分析场景模型 ----
        if not vehicle_model:
            raise HTTPException(status_code=400, detail="使用 model_name 时必须同时传入 vehicle_model")
        vehicle_cfg = MODELS.get(vehicle_model)
        if not vehicle_cfg:
            raise HTTPException(status_code=400, detail=f"车型 '{vehicle_model}' 不存在，可用车型: {list(MODELS.keys())}")
        model_cfg = vehicle_cfg.get("models", {}).get(model_name)
        if not model_cfg:
            available = list(vehicle_cfg.get("models", {}).keys())
            raise HTTPException(status_code=400, detail=f"模型 '{model_name}' 在车型 '{vehicle_model}' 下不存在，可用模型: {available}")

        # 从模型配置获取信号过滤列表
        cfg_signal_list = model_cfg.get("signal_filter_list")
        if cfg_signal_list:
            signals = cfg_signal_list

        # 对于 asc/blf，从模型配置获取 DBC 文件路径列表
        if parser_type != "csv":
            dbc_file_names = model_cfg.get("dbc_files", [])
            if not dbc_file_names:
                raise HTTPException(status_code=400, detail=f"模型 '{model_name}' 未配置 dbc_files")
            vehicle_dbc_dir = DBC_DIR / vehicle_model
            model_dbc_files = []
            for dbc_name in dbc_file_names:
                dbc_path = vehicle_dbc_dir / dbc_name
                if not dbc_path.exists():
                    raise HTTPException(status_code=400, detail=f"DBC 文件不存在: {dbc_path}")
                model_dbc_files.append(str(dbc_path))
    else:
        # ---- 传统模式：从参数解析 signal_filter_list ----
        if signal_filter_list:
            try:
                signals = json.loads(signal_filter_list)
                if not isinstance(signals, list):
                    raise ValueError
            except Exception:
                raise HTTPException(status_code=400, detail="signal_filter_list 必须是 JSON 数组字符串")

        # 传统模式：asc/blf 必须上传 dbc_file
        if parser_type != "csv" and not (dbc_file and dbc_file.filename):
            raise HTTPException(status_code=400, detail="dbc_file 不能为空（或使用 vehicle_model + model_name 指定分析场景模型）")

    # 生成任务ID
    task_id = str(uuid.uuid4())[:8]
    data_path = os.path.join(TEMP_DIR, f"{task_id}_{data_file.filename}")
    dbc_path = None

    # 保存上传文件
    with open(data_path, "wb") as f:
        shutil.copyfileobj(data_file.file, f)

    if dbc_file and dbc_file.filename:
        dbc_path = os.path.join(TEMP_DIR, f"{task_id}_{dbc_file.filename}")
        with open(dbc_path, "wb") as f:
            shutil.copyfileobj(dbc_file.file, f)

    # 初始化任务状态
    with _task_lock:
        _task_store[task_id] = {
            "task_id": task_id,
            "batch_id": batch_id,
            "parser_type": parser_type,
            "status": "pending",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "completed_at": None,
            "result": None,
        }

    def _run():
        with _semaphore:
            with _task_lock:
                _task_store[task_id]["status"] = "running"
            try:
                if parser_type == "csv":
                    total = decode_fn(
                        batch_id=batch_id,
                        data_file=data_path,
                        batch_size=batch_size,
                    )
                else:
                    # 确定使用的 DBC 文件：优先使用模型配置的，否则使用上传的
                    if model_dbc_files:
                        dbc_files = model_dbc_files
                    else:
                        dbc_files = [dbc_path]

                    total = decode_fn(
                        batch_id=batch_id,
                        data_file=data_path,
                        dbc_files=dbc_files,
                        batch_size=batch_size,
                        signal_filter_list=signals,
                    )

                with _task_lock:
                    _task_store[task_id].update({
                        "status": "success",
                        "completed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "result": {"total_written": total},
                    })
            except Exception as e:
                with _task_lock:
                    _task_store[task_id].update({
                        "status": "failed",
                        "completed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "result": {"error": str(e)},
                    })
            finally:
                cleanup_paths = [data_path] + ([dbc_path] if dbc_path else [])
                for p in cleanup_paths:
                    if os.path.exists(p):
                        os.remove(p)

    threading.Thread(target=_run, daemon=True).start()

    return {"task_id": task_id, "parser_type": parser_type, "status": "accepted"}


@app.get("/api/v1/tasks/{task_id}")
async def get_task(task_id: str):
    with _task_lock:
        task = _task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@app.get("/api/v1/models")
async def list_models():
    result = {}
    for v_name, v_info in MODELS.items():
        models_summary = {}
        for m_name, m_cfg in v_info.get("models", {}).items():
            models_summary[m_name] = m_cfg.get("description", "")
        result[v_name] = {
            "description": v_info.get("description", ""),
            "models": models_summary,
        }
    return result


@app.get("/api/v1/models/{vehicle_model}")
async def get_vehicle_models(vehicle_model: str):
    vehicle_cfg = MODELS.get(vehicle_model)
    if not vehicle_cfg:
        raise HTTPException(status_code=404, detail=f"车型 '{vehicle_model}' 不存在")
    result = {
        "vehicle_model": vehicle_model,
        "description": vehicle_cfg.get("description", ""),
        "models": {},
    }
    for m_name, m_cfg in vehicle_cfg.get("models", {}).items():
        result["models"][m_name] = {
            "description": m_cfg.get("description", ""),
            "dbc_files": m_cfg.get("dbc_files", []),
            "signal_filter_list": m_cfg.get("signal_filter_list", []),
        }
    return result


@app.get("/health")
async def health():
    return {"status": "ok", "supported_types": ["asc", "blf", "csv"]}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app="api_server:app", host="0.0.0.0", port=8000, reload=True)
