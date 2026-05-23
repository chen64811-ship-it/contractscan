"""
ContractScan - AI 合同风险审查工具
主应用入口（FastAPI）
"""
import os
import sys
from pathlib import Path

# 确保 backend 目录在 sys.path 中，方便导入
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from routes.contract_routes import router as contract_router

app = FastAPI(
    title="ContractScan",
    description="AI 合同风险审查工具 — 上传合同 PDF，AI 自动识别风险条款",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# CORS 跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 API 路由
app.include_router(contract_router)

# 静态文件（前端）
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
FRONTEND_DIR.mkdir(exist_ok=True)

if FRONTEND_DIR.exists():
    # 挂载前端静态资源（CSS / JS / 图片）
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    async def index():
        """返回前端页面"""
        return FileResponse(str(FRONTEND_DIR / "index.html"))

    @app.get("/{filename:path}")
    async def serve_frontend(filename: str):
        """处理前端路由（非 API 路径都返回前端页面）"""
        file_path = FRONTEND_DIR / filename
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(FRONTEND_DIR / "index.html"))


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app:app", host=host, port=port, reload=True)
