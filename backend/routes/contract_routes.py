"""
合同分析 API 路由
POST /api/analyze  - 上传并分析合同
POST /api/analyze-text  - 粘贴文本分析
POST /api/unlock   - 解锁完整报告
GET  /api/health   - 健康检查
"""
import os
import uuid
import hashlib
import time
from pathlib import Path
from datetime import datetime

from pydantic import BaseModel
from fastapi import APIRouter, UploadFile, File, HTTPException, Request, Depends
from fastapi.responses import FileResponse

from rate_limiter import analyze_limiter, debug_limiter, unlock_limiter
from sqlalchemy.orm import Session
from db import get_db, SessionLocal
from models import File, Analysis, UnlockCode
import json


class TextRequest(BaseModel):
    text: str

class UnlockRequest(BaseModel):
    analysis_id: str
    unlock_code: str

from services.extractor_service import extract_text_from_pdf
from services.ocr_service import ocr_image
from services.cleaner_service import clean_text
from services.contract_analyzer import analyze_contract

router = APIRouter(prefix="/api")

# Upload / output directories
UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# Allowed file types
ALLOWED_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "text/plain",
}
MAX_SIZE = 50 * 1024 * 1024  # 50MB

_CACHE_TTL = 3600  # 1 hour cache

# Unlock codes: loaded from env UNLOCK_CODES (comma-separated)
# Each code can be single-use (default) or multi-use (prefixed with '*')
_VALID_CODES: dict[str, bool] = {}  # code -> is_multi_use
_USED_CODES: set[str] = set()

_codes_str = os.getenv("UNLOCK_CODES", "TRIAL2026,DEMO2026")
for _c in _codes_str.split(","):
    _c = _c.strip()
    if not _c:
        continue
    if _c.startswith("*"):
        # Multi-use code (e.g. *ADMIN2026)
        _VALID_CODES[_c[1:].strip()] = True
    else:
        _VALID_CODES[_c] = False

# Max file age: auto-delete uploads older than this (seconds)
_UPLOAD_MAX_AGE = int(os.getenv("UPLOAD_MAX_AGE", "86400"))  # 24h default


async def _rate_limit_analyze(request: Request):
    """Rate limit dependency for analyze endpoints."""
    analyze_limiter.check(request)


async def _rate_limit_debug(request: Request):
    """Rate limit dependency for debug endpoint."""
    debug_limiter.check(request)


async def _rate_limit_unlock(request: Request):
    """Rate limit dependency for unlock endpoint (anti-brute-force)."""
    unlock_limiter.check(request)


def _get_llm_config() -> tuple[str, str, str]:
    """从环境变量读取 LLM 配置"""
    api_key = os.getenv("LLM_API_KEY", "")
    api_base = os.getenv("LLM_API_BASE", "https://api.deepseek.com")
    model = os.getenv("LLM_MODEL", "deepseek-chat")
    if not api_key:
        raise HTTPException(500, "服务器未配置 LLM API Key，请联系管理员")
    return api_key, api_base, model


def _make_analysis_id(full_result: dict) -> str:
    """生成 analysis_id（8位短码）"""
    return hashlib.sha256(f"{full_result}_{time.time()}_{uuid.uuid4()}".encode()).hexdigest()[:8]


def _make_free_result(full_result: dict) -> dict:
    """从完整分析结果中提取免费版内容（仅评分+摘要，隐藏详细条款）"""
    analysis = full_result.get("analysis", {})
    risk_count = len(analysis.get("risks", []))
    missing_count = len(analysis.get("missing_clauses", []))
    return {
        "analysis": {
            "overall_risk_score": analysis.get("overall_risk_score", 0),
            "summary": analysis.get("summary", ""),
            "risks_count": risk_count,
            "missing_count": missing_count,
        },
        "file_id": full_result.get("file_id", ""),
        "filename": full_result.get("filename", ""),
        "text_length": full_result.get("text_length", 0),
        "analysis_id": full_result.get("analysis_id", ""),
        "is_free": True,
    }


@router.post("/analyze")
async def analyze(file: UploadFile = File(...), _rl=Depends(_rate_limit_analyze), db: Session = Depends(get_db)):
    """
    Upload contract file, return risk analysis result.
    Supports PDF / PNG / JPEG / TXT.
    """
    # 1. 校验文件类型
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(400, f"不支持的文件格式：{file.content_type}，支持 PDF / PNG / JPEG / TXT")

    # 2. 读取文件内容
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(413, f"文件不能超过 50MB")

    # 3. 保存文件
    file_id = uuid.uuid4().hex[:10]
    ext = Path(file.filename).suffix if file.filename else ".pdf"
    save_name = f"{file_id}{ext}"
    save_path = UPLOAD_DIR / save_name
    save_path.write_bytes(content)

    # 4. 提取文本
    try:
        if file.content_type == "application/pdf":
            raw_text = extract_text_from_pdf(str(save_path))
        elif file.content_type.startswith("image/"):
            raw_text = ocr_image(str(save_path), lang="en")
        elif file.content_type == "text/plain":
            raw_text = content.decode("utf-8")
        else:
            raw_text = ""
    except Exception as e:
        raise HTTPException(500, f"文本提取失败：{str(e)}")

    if not raw_text or len(raw_text.strip()) < 20:
        raise HTTPException(400, "未能从文件中提取到足够的文字内容，请确认文件包含可读文本")

    # 5. 清洗文本
    cleaned_text = clean_text(raw_text)

    # 6. LLM 分析
    api_key, api_base, model = _get_llm_config()
    try:
        result = analyze_contract(cleaned_text, api_key, api_base, model)
    except Exception as e:
        raise HTTPException(500, f"AI 分析失败：{str(e)}")

    # 7. 保存完整结果到 outputs/ 并写入数据库，返回免费版
    full_result = {
        "file_id": file_id,
        "filename": file.filename,
        "text_length": len(cleaned_text),
        "analysis": result,
    }

    analysis_id = _make_analysis_id(full_result)
    full_result["analysis_id"] = analysis_id

    # 写入 outputs/{analysis_id}.json
    out_path = OUTPUT_DIR / f"{analysis_id}.json"
    try:
        out_path.write_text(json.dumps(full_result, ensure_ascii=False))
    except Exception as e:
        raise HTTPException(500, f"无法写入输出文件：{e}")

    # 创建 File / Analysis 记录
    try:
        db_file = File(filename=save_name, content_type=file.content_type, path=str(save_path), size=len(content))
        db.add(db_file)
        db.flush()

        analysis_row = Analysis(file_id=db_file.id, analysis_id=analysis_id, summary=result.get("summary", ""), full_result_path=str(out_path), created_at=datetime.utcnow(), is_free=True)
        db.add(analysis_row)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"数据库写入失败：{e}")

    return _make_free_result(full_result)


@router.post("/analyze-text")
async def analyze_text(req: TextRequest, _rl=Depends(_rate_limit_analyze), db: Session = Depends(get_db)):
    """
    Analyze pasted text (no file upload).
    """
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "合同文本不能为空")
    if len(text) < 50:
        raise HTTPException(400, "合同文本太短（至少50个字符）")

    # LLM 直接分析
    api_key, api_base, model = _get_llm_config()
    try:
        result = analyze_contract(text, api_key, api_base, model)
    except Exception as e:
        raise HTTPException(500, f"AI 分析失败：{str(e)}")

    # 保存完整结果并记录到数据库
    full_result = {
        "file_id": "pasted",
        "filename": "pasted-text.txt",
        "text_length": len(text),
        "analysis": result,
    }
    analysis_id = _make_analysis_id(full_result)
    full_result["analysis_id"] = analysis_id

    out_path = OUTPUT_DIR / f"{analysis_id}.json"
    try:
        out_path.write_text(json.dumps(full_result, ensure_ascii=False))
    except Exception as e:
        raise HTTPException(500, f"无法写入输出文件：{e}")

    try:
        analysis_row = Analysis(file_id=None, analysis_id=analysis_id, summary=result.get("summary", ""), full_result_path=str(out_path), created_at=datetime.utcnow(), is_free=True)
        db.add(analysis_row)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"数据库写入失败：{e}")

    return _make_free_result(full_result)


@router.post("/debug-analyze")
async def debug_analyze(req: TextRequest, _rl=Depends(_rate_limit_debug)):
    """DEBUG: Return raw LLM response for diagnosis."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from services.contract_analyzer import (
        _build_client, _clean_json_response, SYSTEM_PROMPT, STANDARD_CLAUSES
    )
    
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "合同文本不能为空")
    if len(text) < 50:
        raise HTTPException(400, "合同文本太短（至少50个字符）")
    
    if len(text) > 12000:
        text = text[:12000] + "\n\n[Contract truncated at 12000 characters]"
    
    api_key, api_base, model = _get_llm_config()
    client = _build_client(api_key, api_base)
    
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Review this contract per the instructions above. Be thorough — check every clause in the checklist:\n\n{text}"},
        ],
        temperature=0.3,
        max_tokens=4096,
    )
    
    raw_output = response.choices[0].message.content or "{}"
    cleaned = _clean_json_response(raw_output)
    
    import json as json_mod
    parse_ok = False
    try:
        parsed = json_mod.loads(cleaned)
        parse_ok = True
    except:
        parsed = None
    
    return {
        "raw_first_500": raw_output[:500],
        "raw_last_200": raw_output[-200:] if len(raw_output) > 200 else "",
        "raw_length": len(raw_output),
        "cleaned_first_500": cleaned[:500],
        "cleaned_last_200": cleaned[-200:] if len(cleaned) > 200 else "",
        "parse_ok": parse_ok,
        "parsed_keys": list(parsed.keys()) if parsed else None,
    }


@router.post("/unlock")
async def unlock_report(req: UnlockRequest, _rl=Depends(_rate_limit_unlock), db: Session = Depends(get_db)):
    """
    Verify unlock code and return full report.
    Codes can be single-use or multi-use (prefixed with * in UNLOCK_CODES).
    """
    global _VALID_CODES, _USED_CODES

    code = req.unlock_code.strip().upper()
    code_info = _VALID_CODES.get(code)

    # If not an env-provided code, try DB-stored unlock codes
    db_code = None
    if code_info is None:
        db_code = db.query(UnlockCode).filter(UnlockCode.code == code).first()
        if not db_code:
            raise HTTPException(403, "Invalid unlock code. Please check and try again.")
        is_multi_use = bool(db_code.is_multi_use)
        # expire check
        if (datetime.utcnow() - db_code.created_at).total_seconds() > _CODE_TTL:
            raise HTTPException(403, "This unlock code has expired.")
    else:
        is_multi_use = code_info
        if not is_multi_use and code in _USED_CODES:
            raise HTTPException(403, "This code has already been used.")

    # Lookup analysis from DB
    analysis_row = db.query(Analysis).filter(Analysis.analysis_id == req.analysis_id).first()
    if not analysis_row:
        raise HTTPException(404, "Analysis report not found or expired.")

    # Load full JSON from outputs
    try:
        full = json.loads(Path(analysis_row.full_result_path).read_text())
    except Exception:
        raise HTTPException(500, "无法读取完整报告文件")

    # Mark single-use env code as used in memory, or delete single-use DB code
    if db_code:
        if not is_multi_use:
            try:
                db.delete(db_code)
                db.commit()
            except Exception:
                db.rollback()
    else:
        if not is_multi_use:
            _USED_CODES.add(code)

    analysis = full.get("analysis", {})
    return {
        "file_id": full.get("file_id", ""),
        "filename": full.get("filename", ""),
        "text_length": full.get("text_length", 0),
        "analysis": {
            "overall_risk_score": analysis.get("overall_risk_score", 0),
            "summary": analysis.get("summary", ""),
            "risks": analysis.get("risks", []),
            "missing_clauses": analysis.get("missing_clauses", []),
        },
        "is_free": False,
    }


@router.get("/health")
async def health():
    """Health check endpoint. Checks DB connectivity when configured."""
    # If DB not configured, return basic healthy status
    try:
        if SessionLocal is None:
            return {"status": "ok", "service": "ContractScan", "db": "not configured"}
        # try a lightweight query
        db = SessionLocal()
        try:
            db.execute("SELECT 1")
            return {"status": "ok", "service": "ContractScan", "db": "ok"}
        finally:
            db.close()
    except Exception as e:
        return {"status": "fail", "service": "ContractScan", "db": str(e)}


@router.get("/config")
async def public_config():
    """Public config for the frontend (non-sensitive)."""
    return {
        "payment_single_url": os.getenv("PAYMENT_SINGLE_URL", ""),
        "payment_pro_url": os.getenv("PAYMENT_PRO_URL", ""),
    }
