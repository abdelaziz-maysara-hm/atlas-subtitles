#!/usr/bin/env python3
"""Atlas Subtitles - customtkinter GUI. All heavy work runs in a worker thread; the UI polls a queue."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

from .. import APP_NAME, __version__
from .bidi_fix import NEEDED, vis, wrap_vis
from ..core import ffmpeg, models, pipeline, subtitles
from ..core.errors import AtlasError, Cancelled
from ..core.subtitles import Segment, fmt_srt_time, is_rtl, parse_time
from .strings import SPOKEN, T

try:  # optional drag & drop
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _DND = True
except Exception:  # pragma: no cover
    _DND = False

CFG_DIR = Path.home() / "AtlasRecordings"
CFG = CFG_DIR / "atlas_subtitles.json"
SHARED_CFG = CFG_DIR / "atlas_settings.json"   # language choice shared with the other Atlas apps
MEDIA_EXT = ("*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.wmv *.flv *.3gp *.ts "
             "*.mp3 *.wav *.m4a *.aac *.ogg *.opus *.flac *.wma *.amr")
FONTS = ["Noto Sans", "Amiri"]

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


def load_cfg() -> dict:
    cfg = {}
    for p in (SHARED_CFG, CFG):
        try:
            cfg.update(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def human_dur(sec: float) -> str:
    sec = int(round(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


class BaseTk(ctk.CTk):
    pass


if _DND:
    class BaseTk(ctk.CTk, TkinterDnD.DnDWrapper):  # type: ignore[no-redef]
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            try:
                self.TkdndVersion = TkinterDnD._require(self)
            except Exception:
                self.TkdndVersion = None


class WrapLabel(ctk.CTkLabel):
    """CTkLabel that wraps RTL text correctly on Linux (see bidi_fix); plain wraplength elsewhere."""

    def __init__(self, master, chars: int = 48, wraplength: int = 330, **kw):
        self._chars = chars
        if NEEDED:
            wraplength = 0
            kw["text"] = wrap_vis(kw.get("text", ""), chars)
        super().__init__(master, wraplength=wraplength, **kw)

    def configure(self, require_redraw=False, **kw):
        if NEEDED and "text" in kw:
            kw["text"] = wrap_vis(kw["text"], self._chars)
        return super().configure(require_redraw=require_redraw, **kw)


class App(BaseTk):
    def __init__(self):
        super().__init__()
        self.cfg = load_cfg()
        self.lang = self.cfg.get("lang", "ar") if self.cfg.get("lang") in ("ar", "en") else "ar"
        self.src: str | None = None
        self.info: ffmpeg.MediaInfo | None = None
        self.segments: list[Segment] = []
        self.undo_stack: list[list[Segment]] = []
        self.q: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel_ev = threading.Event()
        self.job_t0 = 0.0
        self.out_dir: str | None = self.cfg.get("out_dir") or None
        self.vars = {
            "model": tk.StringVar(value=self.cfg.get("model", models.DEFAULT_MODEL)),
            "spoken": tk.StringVar(value=self.cfg.get("spoken", "ar")),
            "dialect": tk.StringVar(value=self.cfg.get("dialect", "msa")),
            "precise": tk.BooleanVar(value=bool(self.cfg.get("precise", False))),
            "font": tk.StringVar(value=self.cfg.get("font") if self.cfg.get("font") in FONTS else "Noto Sans"),
            "size": tk.StringVar(value=str(self.cfg.get("size", "5.5"))),
            "box": tk.BooleanVar(value=bool(self.cfg.get("box", False))),
            "shift": tk.StringVar(value="0.5"),
            "fmt_srt": tk.BooleanVar(value=True),
            "fmt_vtt": tk.BooleanVar(value=bool(self.cfg.get("fmt_vtt", False))),
            "fmt_txt": tk.BooleanVar(value=bool(self.cfg.get("fmt_txt", False))),
        }
        self.title(f"{APP_NAME} {__version__}")
        self.geometry("1180x780")
        self.minsize(980, 660)
        self._style_tree()
        self.build()
        self.after(100, self.poll)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- helpers ----------
    def t(self, key, **kw):
        s = T[self.lang].get(key, T["en"].get(key, key))
        if kw and NEEDED:  # keep paths / numbers as one left-to-right island inside Arabic text
            kw = {k: (v if is_rtl(str(v)) else f"\u202a{v}\u202c") for k, v in kw.items()}
        return vis(s.format(**kw) if kw else s)

    @property
    def rtl(self) -> bool:
        return self.lang == "ar"

    def side(self, first=True):
        """pack side for the 'start' of a row (right in Arabic)."""
        return ("right" if self.rtl else "left") if first else ("left" if self.rtl else "right")

    @property
    def anchor(self):
        return "e" if self.rtl else "w"

    def persist(self):
        CFG_DIR.mkdir(parents=True, exist_ok=True)
        data = {k: (v.get()) for k, v in self.vars.items() if k not in ("shift",)}
        data.update(lang=self.lang, out_dir=self.out_dir)
        try:
            CFG.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            shared = {}
            try:
                shared = json.loads(SHARED_CFG.read_text(encoding="utf-8"))
            except Exception:
                pass
            shared["lang"] = self.lang
            SHARED_CFG.write_text(json.dumps(shared, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

    def _style_tree(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        base = ("Segoe UI", 11) if sys.platform == "win32" else ("Noto Sans Arabic", 11)
        st.configure("Atlas.Treeview", background="#1f2937", fieldbackground="#1f2937", foreground="#e5e7eb",
                     rowheight=30, font=base, borderwidth=0)
        st.configure("Atlas.Treeview.Heading", background="#111827", foreground="#93c5fd",
                     font=(base[0], 11, "bold"), relief="flat")
        st.map("Atlas.Treeview", background=[("selected", "#2563eb")], foreground=[("selected", "white")])

    def ui_font(self, size=13, weight="normal"):
        fam = "Segoe UI" if sys.platform == "win32" else "Noto Sans Arabic"
        return ctk.CTkFont(family=fam, size=size, weight=weight)

    # ---------- layout ----------
    def build(self):
        for w in self.winfo_children():
            w.destroy()
        S, A = self.side, self.anchor
        F = self.ui_font

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(header, text=self.t("title"), font=F(22, "bold")).pack(side=S())
        ctk.CTkLabel(header, text="  " + self.t("subtitle") + "  ", text_color="gray", font=F(12)).pack(side=S())
        ctk.CTkButton(header, text=self.t("lang"), width=64, command=self.toggle_lang).pack(side=S(False))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=4)
        # scrollable so the export box stays reachable on 1366x768 laptops / 125% scaling
        left = ctk.CTkScrollableFrame(body, width=345)
        left.pack(side=S(), fill="y")
        right = ctk.CTkFrame(body, fg_color="transparent")
        right.pack(side=S(), fill="both", expand=True, padx=(12, 12) if True else 0)

        # --- input / drop zone
        self.drop = ctk.CTkFrame(left, height=110, border_width=2, border_color="#334155", fg_color="#0f172a")
        self.drop.pack(fill="x", padx=12, pady=(12, 6))
        self.drop.pack_propagate(False)
        self.drop_lbl = ctk.CTkLabel(self.drop, text="⬇  " + self.t("drop"), font=F(14), text_color="#93c5fd",
                                     wraplength=300)
        self.drop_lbl.pack(expand=True)
        for wdg in (self.drop, self.drop_lbl):
            wdg.bind("<Button-1>", lambda e: self.choose_file())
        if _DND and getattr(self, "TkdndVersion", None):
            for wdg in (self.drop, self.drop_lbl):
                try:
                    wdg.drop_target_register(DND_FILES)
                    wdg.dnd_bind("<<Drop>>", self.on_drop)
                except Exception:
                    pass
        row = ctk.CTkFrame(left, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=4)
        ctk.CTkButton(row, text=self.t("choose"), command=self.choose_file, font=F(13)).pack(side=S(), expand=True, fill="x")
        ctk.CTkButton(row, text=self.t("open_srt"), command=self.open_srt, fg_color="#334155",
                      font=F(13)).pack(side=S(), expand=True, fill="x", padx=6)
        self.file_lbl = WrapLabel(left, text=self.file_text(), text_color="gray", wraplength=330,
                                     justify="right" if self.rtl else "left", font=F(12))
        self.file_lbl.pack(anchor=A, padx=12, pady=(2, 8))

        # --- settings
        def labeled(parent, key):
            ctk.CTkLabel(parent, text=self.t(key), font=F(13, "bold")).pack(anchor=A, padx=12, pady=(6, 0))

        labeled(left, "model")
        self.model_menu = ctk.CTkOptionMenu(left, values=self.model_labels(), command=self.on_model, font=F(13))
        self.model_menu.set(self.model_label(self.vars["model"].get()))
        self.model_menu.pack(fill="x", padx=12, pady=4)
        WrapLabel(left, text=self.t("model_hint"), text_color="gray", font=F(11), wraplength=330, chars=52,
                     justify="right" if self.rtl else "left").pack(anchor=A, padx=12)
        ctk.CTkCheckBox(left, text=self.t("precise"), variable=self.vars["precise"], font=F(11),
                        checkbox_width=18, checkbox_height=18).pack(anchor=A, padx=12, pady=(4, 0))

        labeled(left, "language")
        names = {c: vis(n) for c, n in T[self.lang]["lang_names"].items()}
        self.spoken_menu = ctk.CTkOptionMenu(left, values=[names[c] for c in SPOKEN], font=F(13),
                                             command=lambda v: self.vars["spoken"].set(
                                                 next(c for c in SPOKEN if names[c] == v)))
        self.spoken_menu.set(names.get(self.vars["spoken"].get(), names["ar"]))
        self.spoken_menu.pack(fill="x", padx=12, pady=4)

        labeled(left, "dialect")
        drow = ctk.CTkFrame(left, fg_color="transparent")
        drow.pack(fill="x", padx=12, pady=4)
        for key in ("msa", "egyptian"):
            ctk.CTkRadioButton(drow, text=self.t(key), variable=self.vars["dialect"], value=key,
                               font=F(13)).pack(side=S(), padx=4)

        brow = ctk.CTkFrame(left, fg_color="transparent")
        brow.pack(fill="x", padx=12, pady=(14, 4))
        self.start_btn = ctk.CTkButton(brow, text=self.t("start"), height=40, font=F(15, "bold"),
                                       fg_color="#16a34a", hover_color="#15803d", command=self.start_job)
        self.start_btn.pack(side=S(), expand=True, fill="x")
        self.cancel_btn = ctk.CTkButton(brow, text=self.t("cancel"), height=40, width=90, fg_color="#b91c1c",
                                        hover_color="#991b1b", command=self.cancel_job, state="disabled", font=F(13))
        self.cancel_btn.pack(side=S(), padx=6)
        self.prog = ctk.CTkProgressBar(left)
        self.prog.set(0)
        self.prog.pack(fill="x", padx=12, pady=6)
        self.status = WrapLabel(left, text=self.t("ready"), font=F(12), wraplength=330, chars=44,
                                   justify="right" if self.rtl else "left")
        self.status.pack(anchor=A, padx=12, pady=(0, 8))

        # --- export box
        ex = ctk.CTkFrame(left, fg_color="#111827")
        ex.pack(fill="x", padx=12, pady=6)
        frow = ctk.CTkFrame(ex, fg_color="transparent")
        frow.pack(fill="x", padx=8, pady=(8, 2))
        for key, lbl in (("fmt_srt", "SRT"), ("fmt_vtt", "VTT"), ("fmt_txt", "TXT")):
            ctk.CTkCheckBox(frow, text=lbl, variable=self.vars[key], width=60, font=F(12)).pack(side=S(), padx=2)
        ctk.CTkButton(frow, text=self.t("export"), width=90, command=self.export, font=F(13)).pack(side=S(False))
        self.burn_btn = ctk.CTkButton(ex, text=self.t("burn"), command=self.start_burn, fg_color="#7c3aed",
                                      hover_color="#6d28d9", font=F(13))
        self.burn_btn.pack(fill="x", padx=8, pady=4)
        orow = ctk.CTkFrame(ex, fg_color="transparent")
        orow.pack(fill="x", padx=8, pady=2)
        ctk.CTkLabel(orow, text=self.t("font"), font=F(12)).pack(side=S())
        ctk.CTkOptionMenu(orow, values=FONTS, variable=self.vars["font"], width=90, font=F(12)).pack(side=S(), padx=4)
        ctk.CTkLabel(orow, text=self.t("size"), font=F(12)).pack(side=S())
        ctk.CTkOptionMenu(orow, values=["4", "5", "5.5", "6.5", "8"], variable=self.vars["size"], width=64,
                          font=F(12)).pack(side=S(), padx=4)
        ctk.CTkCheckBox(ex, text=self.t("boxbg"), variable=self.vars["box"], font=F(12)).pack(anchor=A, padx=8, pady=2)
        drow2 = ctk.CTkFrame(ex, fg_color="transparent")
        drow2.pack(fill="x", padx=8, pady=(2, 8))
        self.out_lbl = WrapLabel(drow2, text=self.out_text(), text_color="gray", font=F(11), wraplength=200, chars=28)
        self.out_lbl.pack(side=S())
        ctk.CTkButton(drow2, text=self.t("open_folder"), width=80, fg_color="#334155", command=self.open_folder,
                      font=F(12)).pack(side=S(False))
        ctk.CTkButton(drow2, text=self.t("change"), width=70, fg_color="#334155", command=self.change_out,
                      font=F(12)).pack(side=S(False), padx=4)

        # --- editor
        ctk.CTkLabel(right, text=self.t("editor"), font=F(16, "bold")).pack(anchor=A, pady=(0, 4))
        tf = ctk.CTkFrame(right)
        tf.pack(fill="both", expand=True)
        cols = ("n", "start", "end", "text")
        order = tuple(reversed(cols)) if self.rtl else cols  # mirror columns for Arabic
        self.tree = ttk.Treeview(tf, columns=cols, displaycolumns=order, show="headings", style="Atlas.Treeview",
                                 selectmode="extended")
        for c, w, st in (("n", 50, False), ("start", 110, False), ("end", 110, False), ("text", 520, True)):
            self.tree.heading(c, text=self.t("col_" + c), anchor="center" if c != "text" else A)
            self.tree.column(c, width=w, minwidth=w if not st else 200, stretch=st,
                             anchor=("center" if c != "text" else A))
        sb = ctk.CTkScrollbar(tf, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side=S(False), fill="y")
        self.tree.pack(side=S(), fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        ed = ctk.CTkFrame(right)
        ed.pack(fill="x", pady=(8, 0))
        trow = ctk.CTkFrame(ed, fg_color="transparent")
        trow.pack(fill="x", padx=8, pady=(8, 4))
        ctk.CTkLabel(trow, text=self.t("start_t"), font=F(12)).pack(side=S())
        self.e_start = ctk.CTkEntry(trow, width=120, justify="center")
        self.e_start.pack(side=S(), padx=4)
        ctk.CTkLabel(trow, text=self.t("end_t"), font=F(12)).pack(side=S())
        self.e_end = ctk.CTkEntry(trow, width=120, justify="center")
        self.e_end.pack(side=S(), padx=4)
        ctk.CTkButton(trow, text=self.t("apply"), width=90, command=self.apply_edit, font=F(13)).pack(side=S(False))
        self.e_text = ctk.CTkTextbox(ed, height=70, font=self.ui_font(15), wrap="word")
        self.e_text.pack(fill="x", padx=8, pady=4)
        self.e_text._textbox.tag_configure("dir", justify="right" if self.rtl else "left")
        self.e_text.bind("<KeyRelease>", lambda e: self._justify_text())

        arow = ctk.CTkFrame(ed, fg_color="transparent")
        arow.pack(fill="x", padx=8, pady=(4, 2))
        for key, cmd, color in (("split", self.do_split, None), ("merge", self.do_merge, None),
                                ("add", self.do_add, None), ("delete", self.do_delete, "#b91c1c"),
                                ("undo", self.do_undo, "#334155")):
            kw = {"fg_color": color} if color else {}
            ctk.CTkButton(arow, text=self.t(key), width=96, command=cmd, font=F(13), **kw).pack(side=S(), padx=3)
        arow = ctk.CTkFrame(ed, fg_color="transparent")  # second row: timing shift
        arow.pack(fill="x", padx=8, pady=(2, 8))
        ctk.CTkButton(arow, text=self.t("shift_all"), width=60, command=lambda: self.do_shift(False),
                      fg_color="#0e7490", font=F(12)).pack(side=S(False), padx=2)
        ctk.CTkButton(arow, text=self.t("shift_sel"), width=70, command=lambda: self.do_shift(True),
                      fg_color="#0e7490", font=F(12)).pack(side=S(False), padx=2)
        ctk.CTkEntry(arow, textvariable=self.vars["shift"], width=56, justify="center").pack(side=S(False), padx=2)
        ctk.CTkLabel(arow, text=self.t("shift"), font=F(12)).pack(side=S(False), padx=4)

        self.bind_all("<Control-z>", lambda e: self.do_undo())
        self.refresh_tree()
        self.set_busy(self.worker is not None and self.worker.is_alive())

    # ---------- texts ----------
    def model_label(self, name):
        mark = " " + self.t("downloaded") if models.is_downloaded(name) else ""
        return f"{name}  (~{models.MODELS[name]} MB){mark}"

    def model_labels(self):
        return [self.model_label(m) for m in ("tiny", "base", "small", "medium")]

    def on_model(self, label):
        self.vars["model"].set(label.split()[0])
        self.persist()

    def file_text(self):
        if not self.src:
            return self.t("nofile")
        name = Path(self.src).name
        if not self.info:
            return name
        res = f"{self.info.width}×{self.info.height}" if self.info.has_video else "audio"
        txt = name + "\n" + self.t("info", dur=human_dur(self.info.duration), res=res,
                                   size=human_size(self.info.size_bytes))
        if not self.info.has_audio:
            txt += " · ⚠ " + self.t("noaudio_tag")
        return txt

    def out_text(self):
        path = self.out_dir or T[self.lang].get("same_folder", T["en"]["same_folder"])
        return self.t("outdir_fmt", path=path)

    def toggle_lang(self):
        self.lang = "en" if self.lang == "ar" else "ar"
        self.persist()
        self.build()

    # ---------- file handling ----------
    def choose_file(self):
        if self.busy():
            return
        p = filedialog.askopenfilename(filetypes=[("Media", MEDIA_EXT), ("All", "*.*")])
        if p:
            self.set_file(p)

    def on_drop(self, event):
        paths = self.tk.splitlist(event.data)
        if paths and not self.busy():
            self.set_file(paths[0])

    def set_file(self, p: str):
        self.src = p
        try:
            self.info = ffmpeg.probe(p)
        except AtlasError as e:
            self.info, self.src = None, None  # don't keep an unusable file selected
            self.show_error(e)
            self.file_lbl.configure(text=self.file_text())
            self.drop_lbl.configure(text="⬇  " + self.t("drop"))
            return
        self.file_lbl.configure(text=self.file_text())
        self.drop_lbl.configure(text="🎬  " + Path(p).name)

    def open_srt(self):
        if self.busy():
            return
        p = filedialog.askopenfilename(filetypes=[("SubRip", "*.srt"), ("All", "*.*")])
        if not p:
            return
        try:
            segs = subtitles.load_srt(p)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(APP_NAME, f"{self.t('err_generic')}\n{e}")
            return
        self.push_undo()
        self.segments = subtitles.sort_and_fix(segs)
        self.refresh_tree()
        self.status.configure(text=self.t("loaded_srt", name=Path(p).name, n=len(segs)))

    def base_path(self) -> Path:
        stem = Path(self.src).stem if self.src else "subtitles"
        folder = Path(self.out_dir) if self.out_dir else (Path(self.src).parent if self.src else Path.home())
        if not os.access(folder, os.W_OK):
            folder = CFG_DIR / "Subtitles"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / stem

    def change_out(self):
        d = filedialog.askdirectory()
        if d:
            self.out_dir = d
            self.out_lbl.configure(text=self.out_text())
            self.persist()

    def open_folder(self):
        folder = self.base_path().parent
        try:
            if sys.platform == "win32":
                os.startfile(str(folder))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception:
            pass

    # ---------- jobs ----------
    def busy(self) -> bool:
        if self.worker is not None and self.worker.is_alive():
            messagebox.showinfo(APP_NAME, self.t("busy"))
            return True
        return False

    def set_busy(self, on: bool):
        self.start_btn.configure(state="disabled" if on else "normal")
        self.burn_btn.configure(state="disabled" if on else "normal")
        self.cancel_btn.configure(state="normal" if on else "disabled")

    def start_job(self):
        if self.busy():
            return
        if not self.src:
            messagebox.showwarning(APP_NAME, self.t("need_file"))
            return
        if self.info is None:
            try:
                self.info = ffmpeg.probe(self.src)
            except AtlasError as e:
                self.show_error(e)
                return
        if not self.info.has_audio:
            self.show_error(AtlasError("no_audio"))
            return
        model = self.vars["model"].get()
        est = self.info.duration * pipeline.TYPICAL_RTF.get(model, 0.5)
        if self.info.duration > 45 * 60 and not messagebox.askyesno(
                APP_NAME, self.t("long_warn", dur=human_dur(self.info.duration), model=model, est=human_dur(est))):
            return
        self.persist()
        spoken = self.vars["spoken"].get()
        lang = None if spoken == "auto" else spoken
        dialect = self.vars["dialect"].get() if lang in (None, "ar") else "msa"
        compute = "float32" if self.vars["precise"].get() else "int8"
        self.push_undo()
        self.segments = []
        self.refresh_tree()
        self.cancel_ev = threading.Event()
        self.job_t0 = time.time()
        self.prog.set(0)
        self.set_busy(True)
        src = self.src

        def run():
            try:
                res = pipeline.transcribe_file(
                    src, model, lang, dialect, cancel=self.cancel_ev, compute_type=compute,
                    progress=lambda st, f, d: self.q.put(("progress", st, f, d)),
                    on_segment=lambda s: self.q.put(("segment", s)))
                self.q.put(("done", res))
            except Cancelled:
                self.q.put(("cancelled",))
            except AtlasError as e:
                self.q.put(("error", e))
            except Exception as e:  # noqa: BLE001
                self.q.put(("error", AtlasError("generic", f"{type(e).__name__}: {e}")))

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def start_burn(self):
        if self.busy():
            return
        if not self.segments:
            messagebox.showwarning(APP_NAME, self.t("nothing"))
            return
        if not self.src or not self.info or not self.info.has_video:
            messagebox.showwarning(APP_NAME, self.t("need_video"))
            return
        base = self.base_path()
        dst = base.parent / (base.name + "_subtitled.mp4")
        if Path(self.src).resolve() == dst.resolve():
            dst = base.parent / (base.name + "_subtitled_2.mp4")
        self.persist()
        segs = list(self.segments)
        self.cancel_ev = threading.Event()
        self.job_t0 = time.time()
        self.prog.set(0)
        self.set_busy(True)
        try:
            size = float(self.vars["size"].get())
        except ValueError:
            size = 5.5
        font, box, src = self.vars["font"].get(), self.vars["box"].get(), self.src

        def run():
            try:
                p = pipeline.burn(src, segs, str(dst), font=font, size_pct=size, box=box, cancel=self.cancel_ev,
                                  progress=lambda f: self.q.put(("progress", "burn", f, "")))
                self.q.put(("burned", p))
            except Cancelled:
                self.q.put(("cancelled",))
            except AtlasError as e:
                self.q.put(("error", e))
            except Exception as e:  # noqa: BLE001
                self.q.put(("error", AtlasError("generic", f"{type(e).__name__}: {e}")))

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def cancel_job(self):
        self.cancel_ev.set()
        self.cancel_btn.configure(state="disabled")

    def poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "progress":
                    _, st, f, d = msg
                    self.prog.set(f)
                    self.status.configure(text=self.progress_text(st, f, d))
                elif kind == "segment":
                    self.segments.append(msg[1])
                    s = msg[1]
                    self.tree.insert("", "end", iid=str(len(self.segments) - 1), values=self.row(len(self.segments), s))
                    self.tree.yview_moveto(1.0)
                elif kind == "done":
                    res = msg[1]
                    self.segments = res.segments  # post-processed (re-segmented) result
                    self.refresh_tree()
                    self.prog.set(1)
                    self.status.configure(text=self.t("done", n=len(self.segments), secs=int(time.time() - self.job_t0)))
                    self.set_busy(False)
                    self.model_menu.configure(values=self.model_labels())
                    self.model_menu.set(self.model_label(self.vars["model"].get()))
                    if self.vars["fmt_srt"].get() or self.vars["fmt_vtt"].get() or self.vars["fmt_txt"].get():
                        self.export(quiet=True)
                elif kind == "burned":
                    self.prog.set(1)
                    self.status.configure(text=self.t("saved", path=msg[1]))
                    self.set_busy(False)
                elif kind == "cancelled":
                    self.status.configure(text=self.t("cancelled"))
                    self.prog.set(0)
                    self.set_busy(False)
                elif kind == "error":
                    self.set_busy(False)
                    self.prog.set(0)
                    self.show_error(msg[1])
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def progress_text(self, st, f, d):
        if st == "download":
            m = self.vars["model"].get()
            return self.t("downloading", name=m, mb=d, total=models.MODELS.get(m, "?"))
        if st == "loading":
            return self.t("loading")
        if st == "extract":
            return self.t("extracting")
        if st == "transcribe":
            if not d:
                return self.t("detecting")
            el = time.time() - self.job_t0
            frac = max(0.01, (f - 0.10) / 0.85)
            eta = human_dur(max(0, el / frac - el)) if f > 0.12 else "…"
            name = vis(T[self.lang]["lang_names"].get(d, d))
            return self.t("transcribing", pct=int(f * 100), lang=name, eta=eta)
        if st == "burn":
            return self.t("burning", pct=int(f * 100))
        return ""

    def show_error(self, e: AtlasError):
        key = "err_" + e.code
        msg = self.t(key) if key in T[self.lang] else self.t("err_generic")
        self.status.configure(text=msg)
        detail = f"\n\n{self.t('details')}:\n{e.detail[-600:]}" if e.detail else ""
        messagebox.showerror(APP_NAME, msg + detail)

    # ---------- editor ----------
    def row(self, n, s: Segment):
        text = " ".join(s.text.split())
        if is_rtl(text):
            text = vis("\u200f" + text) if NEEDED else "\u200f" + text
        return (n, fmt_srt_time(s.start), fmt_srt_time(s.end), text)

    def refresh_tree(self, select: int | None = None):
        self.tree.delete(*self.tree.get_children())
        for i, s in enumerate(self.segments):
            self.tree.insert("", "end", iid=str(i), values=self.row(i + 1, s))
        if select is not None and 0 <= select < len(self.segments):
            self.tree.selection_set(str(select))
            self.tree.see(str(select))

    def selected(self) -> list[int]:
        return sorted(int(i) for i in self.tree.selection())

    def on_select(self, _e=None):
        sel = self.selected()
        if not sel:
            return
        s = self.segments[sel[0]]
        self.e_start.delete(0, "end"); self.e_start.insert(0, fmt_srt_time(s.start))
        self.e_end.delete(0, "end"); self.e_end.insert(0, fmt_srt_time(s.end))
        self.e_text.delete("1.0", "end"); self.e_text.insert("1.0", s.text)
        self._justify_text()

    def _justify_text(self):
        txt = self.e_text.get("1.0", "end")
        tb = self.e_text._textbox
        tb.tag_configure("dir", justify="right" if (is_rtl(txt) or (self.rtl and not txt.strip())) else "left")
        tb.tag_add("dir", "1.0", "end")

    def push_undo(self):
        self.undo_stack.append([Segment(s.start, s.end, s.text, list(s.words)) for s in self.segments])
        self.undo_stack = self.undo_stack[-50:]

    def need_sel(self):
        sel = self.selected()
        if not sel:
            messagebox.showinfo(APP_NAME, self.t("select_row"))
        return sel

    def apply_edit(self):
        sel = self.need_sel()
        if not sel:
            return
        try:
            st, en = parse_time(self.e_start.get()), parse_time(self.e_end.get())
            if en <= st:
                raise ValueError
        except ValueError:
            messagebox.showwarning(APP_NAME, self.t("bad_time"))
            return
        text = self.e_text.get("1.0", "end").strip()
        self.push_undo()
        i = sel[0]
        self.segments[i] = Segment(st, en, text, [] if text != self.segments[i].text else self.segments[i].words)
        self.segments = subtitles.sort_and_fix(self.segments)
        self.refresh_tree(min(i, len(self.segments) - 1))

    def do_split(self):
        sel = self.need_sel()
        if not sel:
            return
        try:
            self.push_undo()
            self.segments = subtitles.split_segment(self.segments, sel[0])
        except ValueError:
            self.undo_stack.pop()
            return
        self.refresh_tree(sel[0])

    def do_merge(self):
        sel = self.need_sel()
        if not sel:
            return
        try:
            self.push_undo()
            # merging a multi-selection merges the whole range
            for _ in range(max(1, len(sel) - 1)):
                self.segments = subtitles.merge_segments(self.segments, sel[0])
        except ValueError:
            self.undo_stack.pop()
            return
        self.refresh_tree(sel[0])

    def do_delete(self):
        sel = self.need_sel()
        if not sel:
            return
        self.push_undo()
        self.segments = [s for i, s in enumerate(self.segments) if i not in set(sel)]
        self.refresh_tree(min(sel[0], len(self.segments) - 1))

    def do_add(self):
        sel = self.selected()
        self.push_undo()
        if sel:
            cur = self.segments[sel[-1]]
            nxt = self.segments[sel[-1] + 1].start if sel[-1] + 1 < len(self.segments) else cur.end + 2.0
            st = cur.end
            en = max(st + 0.5, min(st + 2.0, nxt))
            idx = sel[-1] + 1
        else:
            st = self.segments[-1].end if self.segments else 0.0
            en, idx = st + 2.0, len(self.segments)
        self.segments.insert(idx, Segment(st, en, "…"))
        self.refresh_tree(idx)
        self.on_select()

    def do_shift(self, selected_only: bool):
        try:
            off = float(self.vars["shift"].get().replace(",", "."))
        except ValueError:
            messagebox.showwarning(APP_NAME, self.t("bad_time"))
            return
        sel = self.selected()
        if selected_only and not sel:
            messagebox.showinfo(APP_NAME, self.t("select_row"))
            return
        self.push_undo()
        self.segments = subtitles.sort_and_fix(
            subtitles.shift_segments(self.segments, off, sel if selected_only else None))
        self.refresh_tree(sel[0] if sel else None)
        for i in sel:
            if str(i) in self.tree.get_children():
                self.tree.selection_add(str(i))

    def do_undo(self):
        if self.undo_stack:
            self.segments = self.undo_stack.pop()
            self.refresh_tree()

    def export(self, quiet: bool = False):
        if not self.segments:
            if not quiet:
                messagebox.showwarning(APP_NAME, self.t("nothing"))
            return
        fmts = [f for f, k in (("srt", "fmt_srt"), ("vtt", "fmt_vtt"), ("txt", "fmt_txt")) if self.vars[k].get()]
        if not fmts:
            fmts = ["srt"]
        problems = subtitles.validate(self.segments)
        if problems:
            self.segments = subtitles.sort_and_fix(self.segments)
            self.refresh_tree()
        paths = pipeline.export_all(self.segments, self.base_path(), fmts)
        self.persist()
        msg = self.t("saved", path=", ".join(p.name for p in paths)) + f"\n{paths[0].parent}"
        if problems:
            msg += "\n" + self.t("issues", n=len(problems))
        self.status.configure(text=msg)

    def on_close(self):
        self.cancel_ev.set()
        self.persist()
        self.destroy()


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
