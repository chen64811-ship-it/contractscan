# -*- coding: utf-8 -*-
"""
Configuration
Reads settings from .env file, no hardcoded values.
"""
import os
from dotenv import load_dotenv

# Load .env environment variables
load_dotenv()

# Project root directory (parent of backend/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Upload folder (absolute path)
UPLOAD_FOLDER = os.path.join(BASE_DIR, os.getenv("UPLOAD_FOLDER", "uploads"))

# Output folder (absolute path)
OUTPUT_FOLDER = os.path.join(BASE_DIR, os.getenv("OUTPUT_FOLDER", "outputs"))

# Maximum file size (bytes), default 50MB
MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 52428800))

# Allowed file extensions
ALLOWED_EXTENSIONS = set(os.getenv("ALLOWED_EXTENSIONS", "pdf,docx,xlsx,png,jpg,jpeg,gif,bmp,webp,jfif,md").split(","))

# Server configuration
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 5000))

# PaddleOCR GPU configuration
OCR_USE_GPU = os.getenv("OCR_USE_GPU", "true").lower() == "true"

# PaddleOCR language model: auto (auto-detect), en (English), ch (Chinese)
# auto only applies to PDF (can detect from text), images default to this value
OCR_LANG = os.getenv("OCR_LANG", "en")

# Ensure upload and output directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)


def is_allowed_file(filename):
    """
    Check if file extension is in the allowed list.
    """
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_file_ext(filename):
    """
    Get file extension (lowercase).
    """
    return filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
