# Let There Be (Desktop Voice Bible)

A Windows desktop app that listens for a Bible verse reference (offline speech via Vosk) and fetches the verse text from an online Bible API.

## Features
- Offline speech recognition (Vosk)
- Simple Tkinter UI
- Translation picker (public-domain by default)

## Setup

1. Create a virtual environment and install dependencies:

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r app\requirements.txt
```

2. Download the Vosk model:

```bash
python app\download_model.py
```

3. Run the app:

```bash
python app\main.py
```

## Notes
- The app uses `https://bible-api.com/` for public-domain text.
- The Vosk model is intentionally **not** committed to the repo (see `.gitignore`).
- If recognition is imperfect, edit the recognized reference before fetching.
- NIV / MSG / NLT / GNT / ESV are copyrighted and require licensed APIs.

## API.Bible (Licensed)
The app supports API.Bible for licensed translations.

1. Get an API key from API.Bible.
2. In the app, choose `API.Bible (licensed)`, paste your key, then click `Load Bibles`.
3. Select a Bible from the list and fetch verses normally.

## Build EXE (Windows)
1. Activate the venv:

```bash
.\.venv\Scripts\activate
```

2. Install PyInstaller:

```bash
pip install pyinstaller
```

3. Build:

```bash
pyinstaller --noconfirm --onefile --windowed --name "LetThereBe" --collect-binaries vosk --collect-submodules vosk app\main.py
```

4. Copy the Vosk model next to the EXE:

```bash
mkdir dist\models
xcopy models\vosk-model-small-en-us-0.15 dist\models\vosk-model-small-en-us-0.15 /E /I /Y
```

The executable will be in `dist\LetThereBe.exe`. The model must be located in `dist\models\vosk-model-small-en-us-0.15`.
