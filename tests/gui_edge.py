"""GUI edge cases under Xvfb: no-audio file, not-media file, cancel a long job, cancel a burn.
usage: xvfb-run python tests/gui_edge.py TESTDATA OUTDIR"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import ImageGrab
from tkinter import messagebox
from atlas_subtitles.gui import app as appmod

D, out = Path(sys.argv[1]), Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
log = []
for k in ("showinfo", "showwarning", "showerror"):
    setattr(messagebox, k, (lambda kind: lambda *a, **kw: log.append((kind, a[1] if len(a) > 1 else a)))(k))
messagebox.askyesno = lambda *a, **k: (log.append(("ask", a[1] if len(a) > 1 else a)), True)[1]
a = appmod.App(); a.geometry("1366x740+0+0"); a.out_dir = str(out)
a.on_model(a.model_label("base"))
res = {}

def shot(n):
    a.update(); time.sleep(0.3); a.update()
    x, y = a.winfo_rootx(), a.winfo_rooty()
    ImageGrab.grab(bbox=(x, y, x + a.winfo_width(), y + a.winfo_height())).save(out / f"{n}.png")

def wait(then, t0=None):
    t0 = t0 or time.time()
    if a.worker is not None and a.worker.is_alive() and time.time() - t0 < 300:
        a.after(200, lambda: wait(then, t0)); return
    a.after(300, then)

def step1():
    a.set_file(str(D / "noaudio.mp4")); n = len(log); a.start_job()
    wait(lambda: (res.__setitem__("noaudio", log[n:]), shot("e1_noaudio"), step2()))
def step2():
    n = len(log); a.set_file(str(D / "garbage.mp4")); a.start_job()
    wait(lambda: (res.__setitem__("garbage", log[n:]), step3()))
def step3():
    a.set_file(str(D / "long.mp4")); n = len(log); a.start_job(); t0 = time.time()
    def do_cancel():
        res["prog_before_cancel"] = round(a.prog.get(), 3); res["live_segments"] = len(a.segments)
        shot("e2_long_running"); a.cancel_job(); res["t_cancel"] = time.time()
        wait(lambda: (res.__setitem__("cancel_stop_s", round(time.time() - res["t_cancel"], 2)),
                      res.__setitem__("status_after_cancel", a.status.cget("text")),
                      res.__setitem__("long_dialogs", log[n:]), shot("e3_cancelled"), step4()))
    a.after(8000, do_cancel)
def step4():
    # burn cancel: use segments we have (or a dummy line)
    from atlas_subtitles.core.subtitles import Segment
    if not a.segments:
        a.segments = [Segment(0, 5, "اختبار")]
    a.start_burn()
    def c():
        shot("e4_burning"); a.cancel_job(); t = time.time()
        wait(lambda: (res.__setitem__("burn_cancel_stop_s", round(time.time() - t, 2)),
                      res.__setitem__("status_after_burn_cancel", a.status.cget("text")),
                      res.__setitem__("partial_exists", (out / "long_subtitled.mp4").exists()), finish()))
    a.after(3000, c)
def finish():
    for k, v in res.items():
        print(k, "=", v)
    a.destroy()

a.after(800, step1)
a.mainloop()
