import os
import shutil
import subprocess
from pathlib import Path

from . import config
from .utils import get_no_window_flag

LIBREOFFICE_PROCESS: subprocess.Popen | None = None


def find_libreoffice() -> str:
    configured_path = os.getenv("LIBREOFFICE_PATH") or os.getenv("SOFFICE_PATH")
    candidates = [
        configured_path,
        shutil.which("soffice.com"),
        shutil.which("soffice"),
        shutil.which("libreoffice"),
        r"C:\Program Files\LibreOffice\program\soffice.com",
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.com",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]

    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(Path(candidate))

    return ""


def libreoffice_profile_arg() -> str:
    config.LIBREOFFICE_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return f"-env:UserInstallation={config.LIBREOFFICE_PROFILE_DIR.as_uri()}"


def start_libreoffice_listener() -> tuple[bool, str]:
    global LIBREOFFICE_PROCESS

    soffice_path = find_libreoffice()
    if not soffice_path:
        return False, "LibreOffice CLI was not found."

    if LIBREOFFICE_PROCESS and LIBREOFFICE_PROCESS.poll() is None:
        return True, "LibreOffice listener is already running."

    accept_arg = (
        f"--accept=socket,host=127.0.0.1,port={config.LIBREOFFICE_LISTENER_PORT};"
        "urp;StarOffice.ComponentContext"
    )
    args = [
        soffice_path,
        "--headless",
        "--invisible",
        "--nologo",
        "--nodefault",
        "--nofirststartwizard",
        "--nolockcheck",
        libreoffice_profile_arg(),
        accept_arg,
    ]

    try:
        LIBREOFFICE_PROCESS = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=get_no_window_flag(),
        )
        return True, f"LibreOffice listener started on port {config.LIBREOFFICE_LISTENER_PORT}."
    except Exception as exc:
        LIBREOFFICE_PROCESS = None
        return False, f"LibreOffice listener could not start: {exc}"


def stop_libreoffice_listener() -> None:
    global LIBREOFFICE_PROCESS

    if not LIBREOFFICE_PROCESS or LIBREOFFICE_PROCESS.poll() is not None:
        LIBREOFFICE_PROCESS = None
        return

    LIBREOFFICE_PROCESS.terminate()
    try:
        LIBREOFFICE_PROCESS.wait(timeout=5)
    except subprocess.TimeoutExpired:
        LIBREOFFICE_PROCESS.kill()
    finally:
        LIBREOFFICE_PROCESS = None


def convert_office_to_pdf(input_path: Path, output_dir: Path) -> tuple[Path, list[str]]:
    warnings: list[str] = []
    soffice_path = find_libreoffice()

    if not soffice_path:
        raise RuntimeError(
            "LibreOffice CLI was not found. Install LibreOffice and make sure soffice is on PATH, "
            "or set LIBREOFFICE_PATH to soffice.com/soffice.exe."
        )

    listener_ok, listener_message = start_libreoffice_listener()
    warnings.append(listener_message)
    if not listener_ok:
        warnings.append("Continuing with one-shot LibreOffice conversion.")

    args = [
        soffice_path,
        "--headless",
        "--invisible",
        "--nologo",
        "--nodefault",
        "--nofirststartwizard",
        "--nolockcheck",
        libreoffice_profile_arg(),
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(input_path),
    ]

    completed = subprocess.run(
        args,
        cwd=str(output_dir),
        capture_output=True,
        text=True,
        timeout=config.SOFFICE_TIMEOUT_SECONDS,
        creationflags=get_no_window_flag(),
        check=False,
    )

    expected_pdf = output_dir / f"{input_path.stem}.pdf"
    if not expected_pdf.exists():
        pdf_candidates = sorted(output_dir.glob("*.pdf"), key=lambda path: path.stat().st_mtime, reverse=True)
        expected_pdf = pdf_candidates[0] if pdf_candidates else expected_pdf

    if completed.returncode != 0 or not expected_pdf.exists():
        details = (completed.stderr or completed.stdout or "No LibreOffice output.").strip()
        raise RuntimeError(f"LibreOffice conversion failed: {details}")

    return expected_pdf, warnings
