import json
import os
import queue
import re
import threading
import tkinter as tk
from tkinter import ttk

import requests
import sounddevice as sd
from vosk import Model, KaldiRecognizer

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(APP_DIR, ".."))
MODEL_DIR = os.path.join(ROOT_DIR, "models", "vosk-model-small-en-us-0.15")
API_URL = "https://bible-api.com/"

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


def main():
    root = tk.Tk()
    root.title("Let There Be - Voice Bible")
    root.geometry("700x520")

    style = ttk.Style(root)
    style.theme_use("clam")

    header = ttk.Label(root, text="Let There Be", font=("Segoe UI", 18, "bold"))
    header.pack(pady=10)

    frame = ttk.Frame(root)
    frame.pack(fill="x", padx=16)

    ttk.Label(frame, text="Spoken / recognized reference:").pack(anchor="w")
    ref_var = tk.StringVar()
    ref_entry = ttk.Entry(frame, textvariable=ref_var)
    ref_entry.pack(fill="x", pady=4)

    ttk.Label(frame, text="Translation (public domain by default):").pack(anchor="w")
    translation_var = tk.StringVar(value=TRANSLATIONS[0])
    translation_box = ttk.Combobox(frame, textvariable=translation_var, values=TRANSLATIONS, state="normal")
    translation_box.pack(fill="x", pady=4)

    status_var = tk.StringVar(value="Ready")
    status_label = ttk.Label(frame, textvariable=status_var)
    status_label.pack(anchor="w", pady=6)

    output = tk.Text(root, wrap="word", height=15)
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

    def start_recording():
        set_status("Listening...")
        recorder.start()

    def stop_recording():
        recorder.stop()
        set_status("Stopping...")

    def fetch():
        output.delete("1.0", "end")
        reference = ref_var.get().strip()
        translation = translation_var.get().strip().lower()
        if translation in RESTRICTED_TRANSLATIONS:
            set_status("Note: NIV/MSG/NLT/GNT/ESV require licensed APIs; may fail here")
        try:
            ref, tname, text = fetch_verse(reference, translation)
            output.insert("end", f"{ref} ({tname})\n\n{text}")
            set_status("Fetched")
        except Exception as e:
            set_status(str(e))

    btn_frame = ttk.Frame(root)
    btn_frame.pack(pady=6)

    ttk.Button(btn_frame, text="Start Recording", command=start_recording).pack(side="left", padx=4)
    ttk.Button(btn_frame, text="Stop", command=stop_recording).pack(side="left", padx=4)
    ttk.Button(btn_frame, text="Fetch Verse", command=fetch).pack(side="left", padx=4)

    root.mainloop()


if __name__ == "__main__":
    main()
