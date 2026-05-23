# -*- coding: utf-8 -*-
"""
PaddleOCR Text Recognition Service
Supports GPU acceleration (RTX 3060), auto-fallback to CPU if GPU unavailable.
Uses singleton pattern to avoid repeated initialization.

V2 update (2026-05-10):
- Supports bilingual model switching (en / ch)
- Defaults to English model (overseas product positioning)
- Auto language detection, English documents won't use Chinese model
- Per-language OCR instance caching, avoids repeated initialization
"""
import os
import sys
import re
import traceback
from config import OCR_USE_GPU, BASE_DIR

# Add DLL search paths (ensures zlibwapi.dll and other dependencies are found)
# Priority: OCR_DLL_PATHS env var (semicolon-separated) > auto-detect common CUDA install paths
_dll_paths = [os.path.dirname(sys.executable)]  # current Python installation directory

_env_dll = os.environ.get("OCR_DLL_PATHS", "")
if _env_dll:
    _dll_paths.extend(p.strip() for p in _env_dll.split(";") if p.strip())
else:
    # Auto-detect common CUDA Toolkit install locations
    _cuda_candidates = [
        r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA',
    ]
    for _cuda_base in _cuda_candidates:
        if os.path.isdir(_cuda_base):
            try:
                for _ver in sorted(os.listdir(_cuda_base), reverse=True):
                    _bin = os.path.join(_cuda_base, _ver, "bin")
                    if os.path.isdir(_bin):
                        _dll_paths.append(_bin)
                        break  # use the newest version
            except Exception:
                pass

_dll_paths.append(r'C:\Windows\System32')

for _p in _dll_paths:
    if os.path.exists(_p):
        try:
            os.add_dll_directory(_p)
        except Exception:
            pass

# Per-language OCR instance cache: {"en": instance, "ch": instance}
_ocr_instances = {}
# Track device mode per language instance
_ocr_mode = {}  # {"en": True/False, "ch": True/False}


def detect_language(text):
    """
    Detect the primary language of text.
    Samples text, counts CJK vs Latin characters, returns recommended language code.

    Args:
        text: text string to analyze

    Returns:
        "ch" — primarily Chinese (CJK)
        "en" — primarily English / Latin
        "mixed" — Chinese-English mixed
    """
    if not text or len(text.strip()) < 20:
        return "en"  # too short, default to English

    # Sample first 5000 chars (faster detection)
    sample = text[:5000]

    # Count character types
    cjk_count = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', sample))
    latin_count = len(re.findall(r'[a-zA-Z]', sample))
    total_meaningful = cjk_count + latin_count

    if total_meaningful == 0:
        return "en"

    cjk_ratio = cjk_count / total_meaningful

    if cjk_ratio > 0.5:
        return "ch"
    elif cjk_ratio > 0.15:
        return "mixed"  # mixed document, Chinese model has better compatibility
    else:
        return "en"


def _create_ocr_instance(lang, use_gpu):
    """
    Create a new PaddleOCR instance.

    Args:
        lang: "en" or "ch"
        use_gpu: True/False
    """
    from paddleocr import PaddleOCR

    # Optimal parameters per language model
    if lang == "en":
        # English model: higher detection thresholds (English layout is cleaner), larger recognition batches
        ocr = PaddleOCR(
            use_angle_cls=False,       # disable angle classification (GPU tensor compatibility)
            lang="en",                 # English-specific model
            use_gpu=use_gpu,
            show_log=False,
            det_db_thresh=0.3,         # detection threshold
            det_db_box_thresh=0.5,     # box threshold (English lines clearer, can be higher)
            rec_batch_num=16 if use_gpu else 6,
        )
    else:
        # Chinese model parameters (keeping optimized settings)
        ocr = PaddleOCR(
            use_angle_cls=False,
            lang="ch",
            use_gpu=use_gpu,
            show_log=False,
            det_db_thresh=0.3,
            rec_batch_num=16 if use_gpu else 6,
        )
    return ocr


def get_ocr_instance(lang="en"):
    """
    Get PaddleOCR singleton instance.
    Prefers GPU (RTX 3060), auto-fallback to CPU if GPU unavailable.
    Per-language instance caching — same language won't reinitialize.

    Args:
        lang: "en" (English, default), "ch" (Chinese), "mixed" (mixed → uses Chinese model)

    Returns:
        PaddleOCR instance
    """
    global _ocr_instances, _ocr_mode

    # Mixed documents use Chinese model (supports both Chinese and English)
    if lang == "mixed":
        lang = "ch"

    # Return cached instance if available
    if lang in _ocr_instances and _ocr_instances[lang] is not None:
        return _ocr_instances[lang]

    # Check PaddleOCR installation
    try:
        import paddle
    except ModuleNotFoundError:
        raise Exception(
            "OCR dependencies not installed. Please run: pip install paddlepaddle paddleocr"
        )

    # Try GPU first
    if OCR_USE_GPU:
        try:
            paddle.set_device("gpu:0")
            instance = _create_ocr_instance(lang, use_gpu=True)
            # Quick validation that GPU works
            _ocr_instances[lang] = instance
            _ocr_mode[lang] = True
            lang_label = "English" if lang == "en" else "Chinese"
            print(f"[OCR] GPU mode active (RTX 3060) — {lang_label} model loaded")
            return instance
        except Exception as e:
            print(f"[OCR] GPU init failed for {lang}, falling back to CPU: {e}")

    # Fallback to CPU
    try:
        paddle.set_device("cpu")
        instance = _create_ocr_instance(lang, use_gpu=False)
        _ocr_instances[lang] = instance
        _ocr_mode[lang] = False
        lang_label = "English" if lang == "en" else "Chinese"
        print(f"[OCR] CPU mode — {lang_label} model loaded")
        return instance
    except Exception as e:
        raise Exception(f"OCR initialization failed for language '{lang}': {str(e)}")


def is_gpu_available():
    """Check if GPU mode is currently enabled for any loaded instance."""
    global _ocr_mode
    if _ocr_mode:
        return any(_ocr_mode.values())
    return False


def ocr_image(image_path, lang="en"):
    """
    Perform OCR recognition on an image.

    Args:
        image_path: absolute path to image file
        lang: language code — "en" (English, default), "ch" (Chinese), "auto" (auto-detect)

    Returns:
        Recognized text (string), joined in reading order.
    """
    try:
        # Get language-specific OCR instance
        ocr = get_ocr_instance(lang)

        # Run OCR recognition
        result = ocr.ocr(image_path, cls=True)

        if not result or not result[0]:
            return ""

        # Extract text in top-to-bottom, left-to-right order
        lines = []
        for line in result[0]:
            if line and len(line) >= 2:
                text = line[1][0]  # recognized text
                confidence = line[1][1]  # confidence score

                # English model can use a slightly lower confidence threshold (more stable recognition)
                min_conf = 0.4 if lang == "en" else 0.5
                if confidence > min_conf:
                    lines.append(text)

        return "\n".join(lines)

    except Exception as e:
        traceback.print_exc()
        raise Exception(f"OCR failed: {str(e)}")


def reset_ocr_cache():
    """
    Reset OCR instance cache (call after switching language config).
    """
    global _ocr_instances, _ocr_mode
    _ocr_instances = {}
    _ocr_mode = {}
