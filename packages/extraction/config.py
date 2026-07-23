import os
import tempfile
from pathlib import Path

DEFAULT_IMAGES_SCALE = float(os.getenv("LOCAL_EXTRACTOR_IMAGES_SCALE", "2"))
MAX_RENDER_SCALE = float(os.getenv("LOCAL_EXTRACTOR_MAX_IMAGES_SCALE", "3"))
DEFAULT_OCR_LANGUAGE = os.getenv("LOCAL_EXTRACTOR_OCR_LANGUAGE", "eng")
SOFFICE_TIMEOUT_SECONDS = int(os.getenv("LOCAL_EXTRACTOR_SOFFICE_TIMEOUT_SECONDS", "180"))
FORCE_OCR_RETRY = os.getenv("LOCAL_EXTRACTOR_FORCE_OCR_RETRY", "true").lower() != "false"
LIBREOFFICE_LISTENER_PORT = int(os.getenv("LOCAL_EXTRACTOR_LIBREOFFICE_PORT", "2002"))
LIBREOFFICE_PROFILE_DIR = Path(
    os.getenv("LOCAL_EXTRACTOR_LIBREOFFICE_PROFILE", tempfile.gettempdir())
) / "slidevision-libreoffice-profile"
SLIDEVISION_CACHE_PATH = Path(os.getenv("SLIDEVISION_CACHE_PATH", "data/slidevision-cache.sqlite"))
SLIDEVISION_CACHE_NAMESPACE = os.getenv("SLIDEVISION_CACHE_NAMESPACE", "default")
OPENCODE_API_URL = os.getenv("OPENCODE_API_URL", "https://opencode.ai/zen/go/v1/chat/completions")
OPENCODE_VISION_MODEL = os.getenv("OPENCODE_VISION_MODEL", "mimo-v2.5")
OPENCODE_VISION_TIMEOUT_MS = int(os.getenv("OPENCODE_VISION_TIMEOUT_MS", "90000"))
OPENCODE_VISION_MAX_TOKENS = int(os.getenv("OPENCODE_VISION_MAX_TOKENS", "1200"))
OPENCODE_VISION_TEMPERATURE = float(os.getenv("OPENCODE_VISION_TEMPERATURE", "0.2"))
OPENCODE_VISION_CONCURRENCY = int(os.getenv("OPENCODE_VISION_CONCURRENCY", "1"))
OPENCODE_VISION_PAGE_TEXT_CHARS = int(os.getenv("OPENCODE_VISION_PAGE_TEXT_CHARS", "1800"))
OPENCODE_VISION_MAX_IMAGE_BYTES = int(os.getenv("OPENCODE_VISION_MAX_IMAGE_BYTES", str(4 * 1024 * 1024)))
OPENCODE_VISION_PROMPT_VERSION = os.getenv("OPENCODE_VISION_PROMPT_VERSION", "v1")

# Bundled alongside this package (moved from server/opencodeVisionClient.mjs) rather than
# resolved relative to process cwd, since the extraction package can now be imported/run
# from any working directory.
_DEFAULT_OPENCODE_VISION_NODE_HELPER = Path(__file__).resolve().parent / "opencode_helper" / "opencodeVisionClient.mjs"
OPENCODE_VISION_NODE_HELPER = Path(
    os.getenv("OPENCODE_VISION_NODE_HELPER", str(_DEFAULT_OPENCODE_VISION_NODE_HELPER))
)
