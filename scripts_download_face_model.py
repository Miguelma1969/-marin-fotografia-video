"""Download the compact InsightFace model during the Docker image build.

Downloading at build time prevents every Render restart from downloading and
extracting a model while the web service is already under its RAM limit.
"""
from __future__ import annotations

import os
import shutil
import urllib.request
import zipfile
from pathlib import Path

MODEL_NAME = os.getenv("FACE_MODEL", "buffalo_sc").strip() or "buffalo_sc"
MODEL_ROOT = Path(os.getenv("FACE_MODEL_ROOT", "/opt/insightface")).expanduser()
MODEL_DIR = MODEL_ROOT / "models" / MODEL_NAME
MODEL_URL = f"https://github.com/deepinsight/insightface/releases/download/v0.7/{MODEL_NAME}.zip"


def main() -> None:
    if any(MODEL_DIR.glob("*.onnx")):
        print(f"Face model already present: {MODEL_DIR}")
        return

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    archive = MODEL_ROOT / "models" / f"{MODEL_NAME}.zip"
    print(f"Downloading compact face model {MODEL_NAME}...")
    urllib.request.urlretrieve(MODEL_URL, archive)
    try:
        with zipfile.ZipFile(archive) as bundle:
            # Release archives usually contain files directly, but tolerate a
            # top-level model folder without creating a duplicated directory.
            members = bundle.namelist()
            top = f"{MODEL_NAME}/"
            for member in members:
                if member.endswith("/"):
                    continue
                relative = member[len(top):] if member.startswith(top) else member
                if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
                    continue
                destination = MODEL_DIR / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as src, destination.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
    finally:
        archive.unlink(missing_ok=True)

    onnx_files = list(MODEL_DIR.glob("*.onnx"))
    if not onnx_files:
        raise RuntimeError(f"No ONNX files were extracted to {MODEL_DIR}")
    print(f"Installed {len(onnx_files)} ONNX model file(s) in {MODEL_DIR}")


if __name__ == "__main__":
    main()
