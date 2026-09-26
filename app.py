"""SCADA DWG Analyzer - tkinter GUI. Heavy work runs in a worker thread; the UI only reads a Queue."""
import json
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))
import common  # noqa: E402
import env_check  # noqa: E402
import pipeline  # noqa: E402

try:  # crisp text on high-DPI Windows displays
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:  # noqa: BLE001
    pass


class App:
    def __init__(self, root):
        self.root = root
        root.title("SCADA DWG Analyzer")
        root.geometry("900x860")
        root.minsize(760, 620)
        self.cfg = common.load_config()
        self.q = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None
        self.env_ok = False
        self.summary = None

        self.v_in = tk.StringVar(value=str(common.resolve(self.cfg, "input_dir")))
        self.v_out = tk.StringVar(value=str(common.resolve(self.cfg, "output_dir")))
        self.opts = {k: tk.BooleanVar(value=v) for k, v in dict(
            recursive=self.cfg.get("recursive", True), convert=True, analyze=True, scada=True,
            csv=True, json=True, overwrite=self.cfg.get("overwrite", False)).items()}
        self.v_progress = tk.DoubleVar(value=0)
        self.v_ptext = tk.StringVar(value="")
        self.v_current = tk.StringVar(value="")
        self.v_scan = tk.StringVar(value="")
        self.v_env = {k: tk.StringVar(value=f"{k}: ...") for k in
                      ("Python", "ezdxf", "AutoCAD", "accoreconsole")}
        self._build()
        self.root.after(100, self._poll)
        self._check_env()

    # ---------- layout ----------
    def _build(self):
        pad = dict(padx=8, pady=3)
        main = ttk.Frame(self.root, padding=8)
        main.pack(fill="both", expand=True)

        env = ttk.LabelFrame(main, text="環境 Environment")
        env.pack(fill="x", **pad)
        self.env_labels = {}
        for i, k in enumerate(self.v_env):
            lb = ttk.Label(env, textvariable=self.v_env[k], width=32)
            lb.grid(row=0, column=i, sticky="w", padx=6, pady=2)
            self.env_labels[k] = lb
        ttk.Button(env, text="重新檢查", command=self._check_env).grid(row=0, column=4, padx=6)

        paths = ttk.LabelFrame(main, text="路徑 Paths")
        paths.pack(fill="x", **pad)
        for r, (label, var) in enumerate((("輸入資料夾 Input", self.v_in),
                                          ("輸出資料夾 Output", self.v_out))):
            ttk.Label(paths, text=label, width=18).grid(row=r, column=0, sticky="w", padx=6, pady=3)
            ttk.Entry(paths, textvariable=var).grid(row=r, column=1, sticky="ew", pady=3)
            ttk.Button(paths, text="Browse", command=lambda v=var: self._browse(v)).grid(
                row=r, column=2, padx=6)
        paths.columnconfigure(1, weight=1)

        op = ttk.LabelFrame(main, text="處理選項 Processing")
        op.pack(fill="x", **pad)
        items = [("recursive", "遞迴搜尋子資料夾"), ("convert", "DWG → DXF"),
                 ("analyze", "DXF 內容解析"), ("scada", "SCADA 關鍵字搜尋"),
                 ("csv", "產生 CSV"), ("json", "產生 JSON"), ("overwrite", "覆寫既有 DXF")]
        for i, (k, t) in enumerate(items):
            ttk.Checkbutton(op, text=t, variable=self.opts[k]).grid(
                row=i // 4, column=i % 4, sticky="w", padx=8, pady=2)

        kw = ttk.LabelFrame(main, text="關鍵字 Keywords（一行一個）")
        kw.pack(fill="x", **pad)
        self.kw_text = tk.Text(kw, height=5, width=30, font=("Consolas", 10))
        self.kw_text.pack(side="left", fill="both", expand=True, padx=6, pady=4)
        self.kw_text.insert("1.0", "\n".join(self.cfg.get("keywords", [])))
        ttk.Button(kw, text="儲存設定", command=self._save_config).pack(side="right", padx=8)

        ctl = ttk.Frame(main)
        ctl.pack(fill="x", **pad)
        self.btn_scan = ttk.Button(ctl, text="掃描檔案 Scan", command=self._scan)
        self.btn_start = ttk.Button(ctl, text="開始處理 Start", command=self._start)
        self.btn_stop = ttk.Button(ctl, text="停止 Stop", command=self._stop, state="disabled")
        for b in (self.btn_scan, self.btn_start, self.btn_stop):
            b.pack(side="left", padx=4)
        ttk.Label(ctl, textvariable=self.v_scan).pack(side="left", padx=12)

        pf = ttk.Frame(main)
        pf.pack(fill="x", **pad)
        ttk.Progressbar(pf, variable=self.v_progress, maximum=100).pack(side="left", fill="x",
                                                                       expand=True)
        ttk.Label(pf, textvariable=self.v_ptext, width=34).pack(side="left", padx=8)
        ttk.Label(main, textvariable=self.v_current, anchor="w").pack(fill="x", padx=10)

        lf = ttk.LabelFrame(main, text="Log")
        lf.pack(fill="both", expand=True, **pad)
        self.log_box = scrolledtext.ScrolledText(lf, height=10, state="disabled",
                                                 font=("Consolas", 9))
        self.log_box.pack(fill="both", expand=True, padx=4, pady=4)

        rf = ttk.LabelFrame(main, text="結果 Result")
        rf.pack(fill="x", **pad)
        self.v_result = tk.StringVar(value="尚未執行")
        ttk.Label(rf, textvariable=self.v_result, justify="left").pack(anchor="w", padx=8, pady=2)
        bf = ttk.Frame(rf)
        bf.pack(fill="x", pady=4)
        for text, rel in (("開啟輸出資料夾", ""), ("開啟 scada_hits.csv", "csv/scada_hits.csv"),
                          ("開啟 object_hits.csv", "csv/object_hits.csv"),
                          ("開啟 file_index.csv", "csv/file_index.csv"),
                          ("開啟 errors.log", "logs/errors.log")):
            ttk.Button(bf, text=text, command=lambda r=rel: self._open(r)).pack(side="left", padx=4)

    # ---------- helpers ----------
    def _browse(self, var):
        d = filedialog.askdirectory(initialdir=var.get() or str(ROOT))
        if d:
            var.set(os.path.normpath(d))

    def _keywords(self):
        return [l.strip() for l in self.kw_text.get("1.0", "end").splitlines() if l.strip()]

    def _current_cfg(self):
        return dict(self.cfg, input_dir=self.v_in.get().strip(), output_dir=self.v_out.get().strip(),
                    keywords=self._keywords())

    def _save_config(self):
        cfg = {k: v for k, v in self.cfg.items() if not k.startswith("_")}
        cfg.update(input_dir=self.v_in.get().strip(), output_dir=self.v_out.get().strip(),
                   keywords=self._keywords(), recursive=self.opts["recursive"].get(),
                   overwrite=self.opts["overwrite"].get())
        try:
            (ROOT / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
            self.cfg = dict(self.cfg, **cfg)
            self._log("OK", "設定已儲存 config.json")
        except OSError as e:
            messagebox.showerror("儲存失敗", str(e))

    def _log(self, level, msg):
        import datetime
        line = f"[{datetime.datetime.now():%H:%M:%S}] {level:<5} {msg}\n"
        self.log_box.configure(state="normal")
        self.log_box.insert("end", line)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _open(self, rel):
        p = Path(self.v_out.get().strip()) / rel if rel else Path(self.v_out.get().strip())
        if not p.exists():
            messagebox.showinfo("找不到檔案", f"尚未產生：\n{p}")
            return
        os.startfile(str(p))  # noqa: S606 (Windows only)

    # ---------- environment ----------
    def _check_env(self):
        for v in self.v_env.values():
            v.set(v.get().split(":")[0] + ": ...")
        self.btn_start.configure(state="disabled")

        def work():
            path, cands = env_check.find_accore(self.cfg)
            self.q.put(("env_paths", path, cands))
        threading.Thread(target=work, daemon=True).start()

    def _on_env_paths(self, path, cands):
        if not path and len(cands) > 1:
            path = self._choose_accore(cands)
        if path:
            self.cfg["accoreconsole"] = path

        def work():
            self.q.put(("env", env_check.check(self.cfg)))
        threading.Thread(target=work, daemon=True).start()

    def _choose_accore(self, cands):
        win = tk.Toplevel(self.root)
        win.title("選擇 accoreconsole.exe")
        win.transient(self.root)
        win.grab_set()
        ttk.Label(win, text="找到多個 accoreconsole.exe，請選擇：").pack(padx=10, pady=6)
        lb = tk.Listbox(win, width=80, height=min(8, len(cands)), exportselection=False)
        for c in cands:
            lb.insert("end", c)
        lb.selection_set(0)
        lb.pack(padx=10)
        result = {"v": ""}

        def ok():
            sel = lb.curselection()
            result["v"] = cands[sel[0]] if sel else ""
            win.destroy()
        ttk.Button(win, text="確定", command=ok).pack(pady=8)
        self.root.wait_window(win)
        return result["v"]

    def _on_env(self, r):
        def mark(ok):
            return "OK" if ok else "NOT FOUND"
        self.v_env["Python"].set(f"Python: {mark(bool(r['python']))} {r['python']}")
        self.v_env["ezdxf"].set(f"ezdxf: {mark(bool(r['ezdxf']))} {r['ezdxf']}")
        self.v_env["AutoCAD"].set(f"AutoCAD: {mark(r['accore_ok'])} {r['autocad']}")
        self.v_env["accoreconsole"].set(f"accoreconsole: {mark(r['accore_ok'])}")
        self.env_ok = r["ok"]
        for line in r["lines"]:
            self._log("INFO", line)
        if not r["accore_ok"]:
            self._log("ERROR", "accoreconsole NOT FOUND，無法開始處理")
        self.btn_start.configure(state="normal" if self.env_ok and not self._busy() else "disabled")

    # ---------- scan ----------
    def _scan(self):
        d = self.v_in.get().strip()
        rec = self.opts["recursive"].get()

        def work():
            try:
                self.q.put(("scan", pipeline.scan(d, rec)))
            except Exception as e:  # noqa: BLE001
                self.q.put(("scan_err", str(e)))
        self.v_scan.set("掃描中...")
        threading.Thread(target=work, daemon=True).start()

    # ---------- run ----------
    def _busy(self):
        return self.worker is not None and self.worker.is_alive()

    def _start(self):
        if self._busy():
            return
        cfg = self._current_cfg()
        if not Path(cfg["input_dir"]).is_dir():
            messagebox.showerror("輸入資料夾不存在", cfg["input_dir"])
            return
        if not cfg["output_dir"]:
            messagebox.showerror("請指定輸出資料夾", "")
            return
        if not cfg["keywords"] and self.opts["scada"].get():
            messagebox.showwarning("沒有關鍵字", "SCADA 搜尋需要至少一個關鍵字")
            return
        opts = {k: v.get() for k, v in self.opts.items()}
        self.stop_event.clear()
        self.btn_start.configure(state="disabled")
        self.btn_scan.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.v_progress.set(0)
        self.v_ptext.set("")
        self.v_result.set("處理中...")

        def work():
            try:
                s = pipeline.run_pipeline(
                    cfg, opts,
                    log=lambda lv, m: self.q.put(("log", lv, m)),
                    progress=lambda st, i, n, cur: self.q.put(("progress", st, i, n, cur)),
                    stop_event=self.stop_event)
            except Exception as e:  # noqa: BLE001
                s = dict(dwg=0, ok=0, failed=0, dxf=0, keyword_hits=0, unique_objects=0, suspect_texts=0, elapsed=0, stopped=False,
                         fatal=f"{type(e).__name__}: {e}")
                common.log_error(cfg, f"pipeline crashed: {s['fatal']}")
            self.q.put(("done", s))
        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _stop(self):
        self.stop_event.set()
        self.btn_stop.configure(state="disabled")
        self._log("WARN", "停止中：等待目前的 accoreconsole 結束...")

    def _on_done(self, s):
        self.summary = s
        self.btn_scan.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.btn_start.configure(state="normal" if self.env_ok else "disabled")
        if s["fatal"]:
            head = "處理中止（嚴重錯誤）"
        elif s["stopped"]:
            head = "已停止"
        elif s.get("failed_files"):
            head = "Completed with warnings（部分檔案失敗，其餘已完成）"
            self.v_progress.set(100)
        else:
            head = "處理完成"
            self.v_progress.set(100)
        failed_files = s.get("failed_files", [])
        shown = "\n".join(f"  - {x}" for x in failed_files[:8])
        if len(failed_files) > 8:
            shown += f"\n  ... 另有 {len(failed_files) - 8} 個（見 errors.log）"
        self.v_result.set(
            f"{head}\n\nDWG：{s['dwg']}\n成功：{s['ok']}\n失敗：{s['failed']}\n跳過：{s.get('skipped', 0)}\n"
            f"分析失敗：{s.get('analyze_failed', 0)}\nDXF：{s['dxf']}\n"
            f"Keyword Hits：{s['keyword_hits']}\nUnique Matched Objects：{s['unique_objects']}\n"
            f"Suspect text records：{s['suspect_texts']}\n耗時：{pipeline.fmt_duration(s['elapsed'])}"
            + (f"\n錯誤：{s['fatal']}" if s["fatal"] else "")
            + (f"\n\n失敗檔案：\n{shown}" if failed_files else ""))

    def _poll(self):
        try:
            while True:
                m = self.q.get_nowait()
                k = m[0]
                if k == "log":
                    self._log(m[1], m[2])
                elif k == "progress":
                    _, stage, i, n, cur = m
                    pct = 100.0 * i / n if n else 0
                    self.v_progress.set(pct)
                    self.v_ptext.set(f"[{stage}] 目前檔案 {i} / {n}    進度 {pct:.1f}%")
                    self.v_current.set(f"目前處理：{cur}")
                elif k == "done":
                    self._on_done(m[1])
                elif k == "env_paths":
                    self._on_env_paths(m[1], m[2])
                elif k == "env":
                    self._on_env(m[1])
                elif k == "scan":
                    r = m[1]
                    self.v_scan.set(
                        f"找到 DWG：{r['dwg']}｜DXF：{r['dxf']}｜總容量：{pipeline.fmt_size(r['size'])}｜"
                        f"資料夾：{r['folders']}｜中文檔名：{r['chinese']}｜空白路徑：{r['spaces']}｜"
                        f"重複檔名：{r['duplicates']}")
                    self._log("INFO", self.v_scan.get())
                elif k == "scan_err":
                    self.v_scan.set("")
                    messagebox.showerror("掃描失敗", m[1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll)


def main():
    root = tk.Tk()
    app = App(root)

    def on_close():
        if app._busy():
            if not messagebox.askyesno("處理中", "仍在處理，確定要停止並離開？"):
                return
            app.stop_event.set()
            app.worker.join(timeout=20)  # lets the running accoreconsole be terminated cleanly
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
