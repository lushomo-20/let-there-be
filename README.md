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
