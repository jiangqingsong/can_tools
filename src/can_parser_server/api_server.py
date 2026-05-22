import os
import json
import uuid
import time
import shutil
import threading
from typing import Optional, Dict
from fastapi import FastAPI, File, UploadFile, Form, HTTPException

# 导入解析器（你项目里的 parsers 模块）
from parsers import decode_asc, decode_blf, decode_csv

app = FastAPI(title="CAN Data Parser Service", version="2.0.0")

# 临时上传目录
TEMP_DIR = "./temp_uploads"
os.makedirs(TEMP_DIR, exist_ok=True)

# 并发控制：最多同时4个解析任务
_semaphore = threading.Semaphore(4)
# 任务存储：内存保存任务状态
_task_store: Dict[str, dict] = {}
# 任务存储读写锁
_task_lock = threading.Lock()


@app.post("/api/v1/parse")
async def parse(
    parser_type: str = Form(..., description="解析类型：asc, blf, csv"),
    batch_id: str = Form(..., description="批次标识"),
    data_file: UploadFile = File(..., description="数据文件（ASC/BLF/Excel/CSV）"),
    dbc_file: Optional[UploadFile] = File(default=None, description="DBC 描述文件（csv 类型不需要）"),
    batch_size: int = Form(default=500000),
    signal_filter_list: Optional[str] = Form(default=None, description='JSON数组，如 ["VehicleSpeed"]')
):
    """
    提交解析任务。根据 parser_type 参数动态选择 ASC / BLF / CSV 解析器。支持并行调用。
    """
    parser_type = parser_type.lower()

    # 选择解析函数
    if parser_type == "asc":
        decode_fn = decode_asc
    elif parser_type == "blf":
        decode_fn = decode_blf
    elif parser_type == "csv":
        decode_fn = decode_csv
    else:
        raise HTTPException(status_code=400, detail=f"不支持的解析类型 '{parser_type}'，仅支持：asc, blf, csv")

    # 参数校验
    if not data_file.filename:
        raise HTTPException(status_code=400, detail="data_file 不能为空")

    if parser_type != "csv" and not (dbc_file and dbc_file.filename):
        raise HTTPException(status_code=400, detail="dbc_file 不能为空")

    # 解析信号过滤列表
    signals = None
    if signal_filter_list:
        try:
            signals = json.loads(signal_filter_list)
            if not isinstance(signals, list):
                raise ValueError
        except Exception:
            raise HTTPException(status_code=400, detail="signal_filter_list 必须是 JSON 数组字符串")

    # 生成任务ID
    task_id = str(uuid.uuid4())[:8]
    data_path = os.path.join(TEMP_DIR, f"{task_id}_{data_file.filename}")
    dbc_path = None

    if dbc_file and dbc_file.filename:
        dbc_path = os.path.join(TEMP_DIR, f"{task_id}_{dbc_file.filename}")

    # 保存上传文件到临时目录
    with open(data_path, "wb") as f:
        shutil.copyfileobj(data_file.file, f)
    if dbc_path:
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

    # 后台解析线程函数
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
                    total = decode_fn(
                        batch_id=batch_id,
                        data_file=data_path,
                        dbc_file=dbc_path,
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
                # 清理临时文件
                cleanup_paths = [data_path] + ([dbc_path] if dbc_path else [])
                for p in cleanup_paths:
                    if os.path.exists(p):
                        os.remove(p)

    # 启动守护线程执行解析
    threading.Thread(target=_run, daemon=True).start()

    return {"task_id": task_id, "parser_type": parser_type, "status": "accepted"}


@app.get("/api/v1/tasks/{task_id}")
async def get_task(task_id: str):
    with _task_lock:
        task = _task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@app.get("/health")
async def health():
    return {"status": "ok", "supported_types": ["asc", "blf", "csv"]}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app="api_server:app", host="0.0.0.0", port=8000, reload=True)