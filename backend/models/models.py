"""SQLAlchemy models for ContractScan

Models:
- File: 存储上传文件元数据
- Analysis: 存储分析结果摘要与引用（详细结果仍可另存）
- UnlockCode: 支付后生成的解锁码
- Order: 支付订单记录
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from ..db import Base


class File(Base):
    __tablename__ = "files"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    content_type = Column(String(64), nullable=True)
    path = Column(String(1024), nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    size = Column(Integer, nullable=True)


class Analysis(Base):
    __tablename__ = "analyses"
    id = Column(Integer, primary_key=True, index=True)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=True)
    analysis_id = Column(String(64), unique=True, index=True)  # short code used by API
    summary = Column(Text, nullable=True)
    full_result_path = Column(String(1024), nullable=True)  # optional path to full JSON in outputs/
    created_at = Column(DateTime, default=datetime.utcnow)
    is_free = Column(Boolean, default=True)

    file = relationship("File")


class UnlockCode(Base):
    __tablename__ = "unlock_codes"
    code = Column(String(64), primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    email = Column(String(256), nullable=True)
    order_id = Column(String(64), nullable=True)
    is_multi_use = Column(Boolean, default=False)


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(String(128), unique=True, index=True)
    email = Column(String(256), nullable=True)
    variant_name = Column(String(256), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
