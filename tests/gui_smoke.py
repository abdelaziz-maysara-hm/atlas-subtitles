"""Drive the real GUI under Xvfb: load a video, transcribe, edit, export, burn; take screenshots.
usage: xvfb-run -s "-screen 0 1280x860x24" python tests/gui_smoke.py VIDEO OUTDIR [lang]"""
import os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import ImageGrab
from atlas_subtitles.gui import app as appmod
from tkinter import messagebox

video, out = sys.argv[1], Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
ui_lang = sys.argv[3] if len(sys.argv) > 3 else "ar"
model = sys.argv[4] if len(sys.argv) > 4 else "small"
geom = os.environ.get("SMOKE_GEOM", "1260x840")
log = []
messagebox.showinfo = lambda *a, **k: log.append(("info", a))
messagebox.showwarning = lambda *a, **k: log.append(("warn", a))
messagebox.showerror = lambda *a, **k: log.append(("error", a))
messagebox.askyesno = lambda *a, **k: True

a = appmod.App()
a.geometry(geom + "+0+0")
if a.lang != ui_lang:
    a.toggle_lang()
a.on_model(a.model_label(model)); a.model_menu.set(a.model_label(model))
a.vars["model"].trace_add("write", lambda *x: print("MODEL VAR CHANGED ->", a.vars["model"].get(), flush=True))
a.out_dir = str(out)

def shot(name):
    a.update(); time.sleep(0.3); a.update()
    x, y = a.winfo_rootx(), a.winfo_rooty()
    ImageGrab.grab(bbox=(x, y, x + a.winfo_width(), y + a.winfo_height())).save(out / f"{name}.png")
    print("shot", name, "model:", a.vars["model"].get(), "|", a.model_menu.get(), flush=True)

def wait_idle(then, t0=None):
    t0 = t0 or time.time()
    if a.worker is not None and a.worker.is_alive():
        if time.time() - t0 > 600:
            print("TIMEOUT"); a.destroy(); return
        a.after(300, lambda: wait_idle(then, t0)); return
    a.after(400, then)

steps = []
def step(f): steps.append(f); return f

@step
def s0():
    shot("01_empty"); a.set_file(video); a.vars["fmt_vtt"].set(True); a.vars["fmt_txt"].set(True); shot("02_loaded")
    a.start_job(); a.after(2500, lambda: (shot("03_running"), wait_idle(nxt)))
@step
def s1():
    shot("04_done"); print("segments", len(a.segments), "status:", a.status.cget("text"))
    a.tree.selection_set("0"); a.on_select(); shot("05_selected"); nxt()
@step
def s2():
    n = len(a.segments); a.do_split(); print("split", n, "->", len(a.segments))
    a.do_merge(); print("merge ->", len(a.segments))
    a.tree.selection_set("1"); a.on_select()
    a.e_text.delete("1.0", "end"); a.e_text.insert("1.0", "سطر معدّل يدويًا للتجربة؟"); a.apply_edit()
    print("edited:", a.segments[1].text)
    a.vars["shift"].set("0.25"); before = a.segments[0].start; a.do_shift(False); print("shift all", before, "->", a.segments[0].start)
    a.do_undo(); print("undo ->", a.segments[0].start)
    a.tree.selection_set("1"); a.on_select(); shot("06_edited"); a.export(); print("export:", a.status.cget("text")); nxt()
@step
def s3():
    a.start_burn(); a.after(1500, lambda: (shot("07_burning"), wait_idle(nxt)))
@step
def s4():
    shot("08_burned"); print("burn status:", a.status.cget("text")); a.toggle_lang(); shot("09_other_lang"); nxt()
@step
def s5():
    print("dialogs:", log); a.destroy()

i = [0]
def nxt():
    f = steps[i[0]]; i[0] += 1; f()
a.after(800, nxt)
a.mainloop()
