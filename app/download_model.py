import os
import zipfile

import requests

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MODELS_DIR = os.path.join(ROOT_DIR, "models")
MODEL_NAME = "vosk-model-small-en-us-0.15"
MODEL_DIR = os.path.join(MODELS_DIR, MODEL_NAME)
MODEL_ZIP = os.path.join(MODELS_DIR, f"{MODEL_NAME}.zip")
URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"


def download():
    if os.path.isdir(MODEL_DIR):
        print("Model already exists:", MODEL_DIR)
        return
    os.makedirs(MODELS_DIR, exist_ok=True)
    print("Downloading model...")
    with requests.get(URL, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(MODEL_ZIP, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    print("Extracting...")
    with zipfile.ZipFile(MODEL_ZIP, "r") as z:
        z.extractall(MODELS_DIR)
    os.remove(MODEL_ZIP)
    print("Done")


if __name__ == "__main__":
    download()
