import html
import json
import os
import queue
import re
import sys
import threading
import tkinter as tk
from tkinter import ttk

import requests
import sounddevice as sd
from vosk import Model, KaldiRecognizer

APP_NAME = "LetThereBe"
APP_DIR = os.path.dirname(os.path.abspath(__file__))


def get_root_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.join(APP_DIR, ".."))


ROOT_DIR = get_root_dir()
MODEL_DIR = os.path.join(ROOT_DIR, "models", "vosk-model-small-en-us-0.15")
API_URL = "https://bible-api.com/"
API_BIBLE_BASE = "https://api.scripture.api.bible/v1"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", ROOT_DIR), APP_NAME)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

TRANSLATIONS = [
    "kjv",
    "asv",
    "web",
    "bbe",
    "ylt",
    "darby",
    "niv",
    "msg",
    "nlt",
    "gnt",
    "esv",
]

RESTRICTED_TRANSLATIONS = {"niv", "msg", "nlt", "gnt", "esv"}

NUMBER_WORDS = {
    "zero": 0,
    "oh": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
    "hundred": 100,
    "thousand": 1000,
    "first": 1,
    "second": 2,
    "third": 3,
}

BOOK_ALIASES = [
    "Genesis",
    "Exodus",
    "Leviticus",
    "Numbers",
    "Deuteronomy",
    "Joshua",
    "Judges",
    "Ruth",
    "1 Samuel",
    "2 Samuel",
    "1 Kings",
    "2 Kings",
    "1 Chronicles",
    "2 Chronicles",
    "Ezra",
    "Nehemiah",
    "Esther",
    "Job",
    "Psalms",
    "Proverbs",
    "Ecclesiastes",
    "Song of Solomon",
    "Isaiah",
    "Jeremiah",
    "Lamentations",
    "Ezekiel",
    "Daniel",
    "Hosea",
    "Joel",
    "Amos",
    "Obadiah",
    "Jonah",
    "Micah",
    "Nahum",
    "Habakkuk",
    "Zephaniah",
    "Haggai",
    "Zechariah",
    "Malachi",
    "Matthew",
    "Mark",
    "Luke",
    "John",
    "Acts",
    "Romans",
    "1 Corinthians",
    "2 Corinthians",
    "Galatians",
    "Ephesians",
    "Philippians",
    "Colossians",
    "1 Thessalonians",
    "2 Thessalonians",
    "1 Timothy",
    "2 Timothy",
    "Titus",
    "Philemon",
    "Hebrews",
    "James",
    "1 Peter",
    "2 Peter",
    "1 John",
    "2 John",
    "3 John",
    "Jude",
    "Revelation",
]

BOOK_TOKENS = [normalize_book_key(b) for b in BOOK_ALIASES]


def words_to_number(seq):
    total = 0
    current = 0
    for w in seq:
        if w in ("hundred", "thousand"):
            scale = NUMBER_WORDS[w]
            if current == 0:
                current = 1
            current *= scale
            if scale >= 1000:
                total += current
                current = 0
        else:
            current += NUMBER_WORDS[w]
    return total + current


def normalize_reference(text):
    if not text:
        return ""
    text = text.lower()
    tokens = re.findall(r"[a-zA-Z']+|\d+|:", text)

    out = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in ("vs", "verse", "verses"):
            out.append(":")
            i += 1
            continue
        if t.isdigit() or t == ":":
            out.append(t)
            i += 1
            continue
        if t in NUMBER_WORDS:
            seq = [t]
            j = i + 1
            while j < len(tokens) and tokens[j] in NUMBER_WORDS:
                seq.append(tokens[j])
                j += 1
            out.append(str(words_to_number(seq)))
            i = j
            continue
        out.append(t)
        i += 1

    s = " ".join(out)
    if ":" not in s:
        matches = list(re.finditer(r"(\d+)\s+(\d+)\b", s))
        if matches:
            last = matches[-1]
            s = s[: last.start()] + f"{last.group(1)}:{last.group(2)}" + s[last.end() :]
    return s


def normalize_book_key(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def parse_reference(reference):
    ref = normalize_reference(reference)
    match = re.match(r"^(?P<book>.+?)\s+(?P<chapter>\d+)\s*:\s*(?P<verse>\d+)(?:\s*-\s*(?P<verse_end>\d+))?$", ref)
    if not match:
        raise ValueError("Use format like: John 3:16 or 1 John 3:16")
    book = match.group("book").strip()
    chapter = int(match.group("chapter"))
    verse = int(match.group("verse"))
    verse_end = match.group("verse_end")
    verse_end = int(verse_end) if verse_end else None
    return book, chapter, verse, verse_end


def best_book_match(raw_book):
    from difflib import get_close_matches

    key = normalize_book_key(raw_book)
    if key in BOOK_TOKENS:
        idx = BOOK_TOKENS.index(key)
        return BOOK_ALIASES[idx]
    matches = get_close_matches(key, BOOK_TOKENS, n=1, cutoff=0.6)
    if not matches:
        return raw_book
    idx = BOOK_TOKENS.index(matches[0])
    return BOOK_ALIASES[idx]


class Recorder:
    def __init__(self, on_partial, on_final, on_error):
        self.on_partial = on_partial
        self.on_final = on_final
        self.on_error = on_error
        self.q = queue.Queue()
        self.thread = None
        self.running = False
        self.last_text = ""

    def start(self):
        if self.running:
            return
        if not os.path.isdir(MODEL_DIR):
            self.on_error("Vosk model not found. Run: python app\\download_model.py")
            return
        try:
            model = Model(MODEL_DIR)
            rec = KaldiRecognizer(model, 16000)
            self.running = True

            def callback(indata, frames, time, status):
                if status:
                    self.on_error(str(status))
                self.q.put(bytes(indata))

            def loop():
                try:
                    with sd.RawInputStream(
                        samplerate=16000, blocksize=8000, dtype="int16", channels=1, callback=callback
                    ):
                        while self.running:
                            data = self.q.get()
                            if rec.AcceptWaveform(data):
                                res = json.loads(rec.Result())
                                text = res.get("text", "").strip()
                                if text:
                                    self.last_text = text
                                    self.on_partial(text)
                            else:
                                res = json.loads(rec.PartialResult())
                                partial = res.get("partial", "").strip()
                                if partial:
                                    self.on_partial(partial)
                except Exception as e:
                    self.on_error(str(e))
                finally:
                    try:
                        res = json.loads(rec.FinalResult())
                        text = res.get("text", "").strip()
                        if text:
                            self.last_text = text
                    except Exception:
                        pass
                    self.on_final(self.last_text)

            self.thread = threading.Thread(target=loop, daemon=True)
            self.thread.start()
        except Exception as e:
            self.on_error(str(e))

    def stop(self):
        if not self.running:
            return
        self.running = False


def fetch_verse(reference, translation):
    if not reference:
        raise ValueError("Reference is empty")
    params = {}
    if translation:
        params["translation"] = translation
    r = requests.get(f"{API_URL}{reference}", params=params, timeout=15)
    if r.status_code != 200:
        raise ValueError(f"API error ({r.status_code}): {r.text}")
    data = r.json()
    verses = data.get("verses", [])
    if not verses:
        raise ValueError("No verses found")
    text = "".join(v.get("text", "") for v in verses).strip()
    ref = data.get("reference", reference)
    translation_name = data.get("translation_name", translation)
    return ref, translation_name, text


def api_bible_headers(api_key):
    return {"api-key": api_key}


def load_config():
    try:
        if not os.path.isfile(CONFIG_FILE):
            return {}
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(data):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def api_bible_list_bibles(api_key):
    r = requests.get(f"{API_BIBLE_BASE}/bibles", headers=api_bible_headers(api_key), timeout=15)
    if r.status_code != 200:
        raise ValueError(f"API.Bible error ({r.status_code}): {r.text}")
    data = r.json()
    return data.get("data", [])


def api_bible_list_books(api_key, bible_id):
    r = requests.get(
        f"{API_BIBLE_BASE}/bibles/{bible_id}/books",
        headers=api_bible_headers(api_key),
        timeout=15,
    )
    if r.status_code != 200:
        raise ValueError(f"API.Bible error ({r.status_code}): {r.text}")
    data = r.json()
    return data.get("data", [])


def build_book_map(books):
    book_map = {}
    for b in books:
        book_id = b.get("id")
        for key in [
            b.get("name"),
            b.get("nameLong"),
            b.get("abbreviation"),
            b.get("abbreviationLocal"),
        ]:
            if key:
                book_map[normalize_book_key(key)] = book_id
    return book_map


def api_bible_fetch_passage(api_key, bible_id, passage_id):
    params = {
        "content-type": "text",
        "include-notes": "false",
        "include-titles": "false",
        "include-verse-numbers": "false",
        "include-chapter-numbers": "false",
        "include-verse-spans": "false",
    }
    r = requests.get(
        f"{API_BIBLE_BASE}/bibles/{bible_id}/passages/{passage_id}",
        headers=api_bible_headers(api_key),
        params=params,
        timeout=15,
    )
    if r.status_code != 200:
        raise ValueError(f"API.Bible error ({r.status_code}): {r.text}")
    data = r.json().get("data", {})
    content = data.get("content", "")
    content = html.unescape(re.sub(r"<[^>]+>", "", content)).strip()
    reference = data.get("reference", passage_id)
    copyright_text = data.get("copyright", "")
    return reference, content, copyright_text


def main():
    root = tk.Tk()
    root.title("Let There Be - Voice Bible")
    root.geometry("760x720")
    root.minsize(760, 650)

    container = ttk.Frame(root)
    container.pack(fill="both", expand=True)

    canvas = tk.Canvas(container, highlightthickness=0)
    vscroll = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vscroll.set)
    vscroll.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    content = ttk.Frame(canvas)
    canvas_window = canvas.create_window((0, 0), window=content, anchor="nw")

    def on_content_configure(event):
        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.itemconfigure(canvas_window, width=canvas.winfo_width())

    def on_canvas_configure(event):
        canvas.itemconfigure(canvas_window, width=event.width)

    content.bind("<Configure>", on_content_configure)
    canvas.bind("<Configure>", on_canvas_configure)

    def on_mousewheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    canvas.bind_all("<MouseWheel>", on_mousewheel)

    style = ttk.Style(root)
    style.theme_use("clam")

    header = ttk.Label(content, text="Let There Be", font=("Segoe UI", 18, "bold"))
    header.pack(pady=10)

    frame = ttk.Frame(content)
    frame.pack(fill="x", padx=16)

    ttk.Label(frame, text="Spoken / recognized reference:").pack(anchor="w")
    ref_var = tk.StringVar()
    ref_entry = ttk.Entry(frame, textvariable=ref_var)
    ref_entry.pack(fill="x", pady=4)

    ttk.Label(frame, text="Translation (public domain by default):").pack(anchor="w")
    translation_var = tk.StringVar(value=TRANSLATIONS[0])
    translation_box = ttk.Combobox(frame, textvariable=translation_var, values=TRANSLATIONS, state="normal")
    translation_box.pack(fill="x", pady=4)

    ttk.Label(frame, text="Provider:").pack(anchor="w", pady=(8, 0))
    provider_var = tk.StringVar(value="public")
    provider_frame = ttk.Frame(frame)
    provider_frame.pack(fill="x", pady=4)
    ttk.Radiobutton(provider_frame, text="Public API (bible-api.com)", variable=provider_var, value="public").pack(
        side="left"
    )
    ttk.Radiobutton(provider_frame, text="API.Bible (licensed)", variable=provider_var, value="api_bible").pack(
        side="left", padx=12
    )

    ttk.Label(frame, text="API.Bible key:").pack(anchor="w")
    config = load_config()
    api_key_var = tk.StringVar(value=config.get("api_bible_key", os.environ.get("API_BIBLE_KEY", "")))
    api_key_entry = ttk.Entry(frame, textvariable=api_key_var, show="*")
    api_key_entry.pack(fill="x", pady=4)
    key_btns = ttk.Frame(frame)
    key_btns.pack(anchor="w", pady=(0, 6))
    save_key_btn = ttk.Button(key_btns, text="Save Key")
    save_key_btn.pack(side="left")
    test_key_btn = ttk.Button(key_btns, text="Test Key")
    test_key_btn.pack(side="left", padx=6)

    ttk.Label(frame, text="API.Bible translation (Bible ID):").pack(anchor="w")
    bible_display_var = tk.StringVar()
    bible_box = ttk.Combobox(frame, textvariable=bible_display_var, values=[], state="readonly")
    bible_box.pack(fill="x", pady=4)
    load_bibles_btn = ttk.Button(frame, text="Load Bibles")
    load_bibles_btn.pack(anchor="w", pady=(0, 6))

    status_var = tk.StringVar(value="Ready")
    status_label = ttk.Label(frame, textvariable=status_var)
    status_label.pack(anchor="w", pady=6)

    output = tk.Text(content, wrap="word", height=12)
    output.pack(fill="both", expand=True, padx=16, pady=8)

    def set_status(msg):
        status_var.set(msg)

    def on_partial(text):
        root.after(0, lambda: set_status(f"Listening: {text}"))

    def on_final(text):
        def apply():
            if text:
                normalized = normalize_reference(text)
                ref_var.set(normalized)
                set_status("Captured")
            else:
                set_status("No speech recognized")
        root.after(0, apply)

    def on_error(msg):
        root.after(0, lambda: set_status(f"Error: {msg}"))

    recorder = Recorder(on_partial, on_final, on_error)
    bibles_map = {}
    bibles_info = {}
    books_cache = {}

    def start_recording():
        set_status("Listening...")
        recorder.start()

    def stop_recording():
        recorder.stop()
        set_status("Stopping...")

    def toggle_provider_state():
        is_public = provider_var.get() == "public"
        translation_box.configure(state="normal" if is_public else "disabled")
        api_key_entry.configure(state="disabled" if is_public else "normal")
        bible_box.configure(state="disabled" if is_public else "readonly")
        load_bibles_btn.configure(state="disabled" if is_public else "normal")
        save_key_btn.configure(state="disabled" if is_public else "normal")

    def save_key():
        key = api_key_var.get().strip()
        if not key:
            set_status("API.Bible key is empty")
            return
        data = load_config()
        data["api_bible_key"] = key
        save_config(data)
        set_status(f"Saved API.Bible key to {CONFIG_FILE}")

    save_key_btn.configure(command=save_key)

    def test_key():
        key = api_key_var.get().strip()
        if not key:
            set_status("API.Bible key is empty")
            return
        try:
            bibles = api_bible_list_bibles(key)
            count = len(bibles)
            set_status(f"API.Bible key OK ({count} bibles)")
        except Exception as e:
            set_status(f"API.Bible key failed: {e}")

    test_key_btn.configure(command=test_key)

    def load_bibles():
        api_key = api_key_var.get().strip()
        if not api_key:
            set_status("Enter API.Bible key first")
            return
        try:
            bibles = api_bible_list_bibles(api_key)
            bibles_map.clear()
            bibles_info.clear()
            options = []
            for b in bibles:
                name = b.get("name", "Unknown")
                abbr = b.get("abbreviationLocal") or b.get("abbreviation") or ""
                display = f"{name} ({abbr})" if abbr else name
                b_id = b.get("id")
                if b_id:
                    bibles_map[display] = b_id
                    bibles_info[b_id] = b
                    options.append(display)
            options.sort()
            bible_box.configure(values=options)
            if options:
                bible_display_var.set(options[0])
                set_status("Loaded API.Bible translations")
            else:
                set_status("No bibles returned for this key")
        except Exception as e:
            set_status(str(e))

    load_bibles_btn.configure(command=load_bibles)

    def fetch():
        output.delete("1.0", "end")
        reference = ref_var.get().strip()
        provider = provider_var.get()
        if provider == "public":
            translation = translation_var.get().strip().lower()
            if translation in RESTRICTED_TRANSLATIONS:
                set_status("Note: NIV/MSG/NLT/GNT/ESV require licensed APIs; may fail here")
            try:
                book, chapter, verse, verse_end = parse_reference(reference)
                book = best_book_match(book)
                if verse_end:
                    corrected = f"{book} {chapter}:{verse}-{verse_end}"
                else:
                    corrected = f"{book} {chapter}:{verse}"
                ref, tname, text = fetch_verse(corrected, translation)
                output.insert("end", f"{ref} ({tname})\n\n{text}")
                set_status("Fetched")
            except Exception as e:
                set_status(str(e))
            return

        api_key = api_key_var.get().strip()
        if not api_key:
            set_status("API.Bible key is required")
            return
        display = bible_display_var.get().strip()
        bible_id = bibles_map.get(display)
        if not bible_id:
            set_status("Select a Bible ID (click Load Bibles)")
            return
        try:
            if bible_id not in books_cache:
                books = api_bible_list_books(api_key, bible_id)
                books_cache[bible_id] = build_book_map(books)
            book_name, chapter, verse, verse_end = parse_reference(reference)
            book_name = best_book_match(book_name)
            book_id = books_cache[bible_id].get(normalize_book_key(book_name))
            if not book_id:
                raise ValueError(f"Book not found: {book_name}")
            if verse_end:
                passage_id = f"{book_id}.{chapter}.{verse}-{book_id}.{chapter}.{verse_end}"
            else:
                passage_id = f"{book_id}.{chapter}.{verse}"
            ref, text, copyright_text = api_bible_fetch_passage(api_key, bible_id, passage_id)
            output.insert("end", f"{ref}\n\n{text}")
            if copyright_text:
                output.insert("end", f"\n\n{copyright_text}")
            set_status("Fetched (API.Bible)")
        except Exception as e:
            set_status(str(e))

    btn_frame = ttk.Frame(content)
    btn_frame.pack(pady=6)

    ttk.Button(btn_frame, text="Start Recording", command=start_recording).pack(side="left", padx=4)
    ttk.Button(btn_frame, text="Stop", command=stop_recording).pack(side="left", padx=4)
    ttk.Button(btn_frame, text="Fetch Verse", command=fetch).pack(side="left", padx=4)

    toggle_provider_state()
    provider_var.trace_add("write", lambda *_: toggle_provider_state())

    root.mainloop()


if __name__ == "__main__":
    main()
