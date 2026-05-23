"""
合同分析 API 路由
POST /api/analyze  - 上传并分析合同
GET  /api/health    - 健康检查
"""
import os
import uuid
from pathlib import Path

from pydantic import BaseModel
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse


class TextRequest(BaseModel):
    text: str

from services.extractor_service import extract_text_from_pdf
from services.ocr_service import ocr_image
from services.cleaner_service import clean_text
from services.contract_analyzer import analyze_contract

router = APIRouter(prefix="/api")

# 上传目录
UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# 允许的文件类型
ALLOWED_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "text/plain",
}
MAX_SIZE = 50 * 1024 * 1024  # 50MB


def _get_llm_config() -> tuple[str, str, str]:
    """从环境变量读取 LLM 配置"""
    api_key = os.getenv("LLM_API_KEY", "")
    api_base = os.getenv("LLM_API_BASE", "https://api.deepseek.com")
    model = os.getenv("LLM_MODEL", "deepseek-chat")
    if not api_key:
        raise HTTPException(500, "服务器未配置 LLM API Key，请联系管理员")
    return api_key, api_base, model


@router.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    """
    上传合同文件，返回风险分析结果
    支持 PDF / 图片 / 纯文本
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

    # 7. 返回结果
    return {
        "file_id": file_id,
        "filename": file.filename,
        "text_length": len(cleaned_text),
        "analysis": result,
    }


@router.post("/analyze-text")
async def analyze_text(req: TextRequest):
    """
    分析纯文本合同（不上传文件，直接粘贴文本）
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

    return {
        "file_id": "pasted",
        "filename": "pasted-text.txt",
        "text_length": len(text),
        "analysis": result,
    }


@router.get("/health")
async def health():
    """健康检查接口"""
    return {"status": "ok", "service": "ContractScan"}
