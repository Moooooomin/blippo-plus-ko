#!/usr/bin/env python3
"""Blippo+ 한글 패치 — 설치 프로그램 (GUI).

실제 작업은 blippo_ko.py 가 한다. 이 파일은 창을 띄우고, 작업을 별도 스레드에서
돌리면서 그 출력과 진행률을 받아 화면에 보여 줄 뿐이다.

  python blippo_ko_gui.py
"""
import argparse
import os
import queue
import re
import subprocess
import sys
import threading
import time
import traceback
import warnings

warnings.filterwarnings("ignore")

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

# 고해상도 화면에서 창이 흐릿하게 늘어나지 않게
try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

import blippo_ko as bk

VERSION = "1.1"
GAME_EXE = "Blippo+.exe"
SLOT = 14                      # 유럽 스페인어 자리를 한국어로 쓴다
APP = bk.app_dir()
TRANS = os.path.join(APP, "blippo_ko.json")
BACKUP = os.path.join(APP, "backup")

C = {
    "bg": "#f4f2ea",       # 브라운관 베젤 같은 미색
    "panel": "#ffffff",
    "ink": "#1d1d1b",
    "muted": "#6b6a64",
    "line": "#d9d6ca",
    "accent": "#2f7d6b",   # 블리포+ 편성표의 청록
    "accent_hi": "#276a5a",
    "ok": "#2f7d6b",
    "warn": "#b7791f",
    "bad": "#b3261e",
    "off": "#8a8880",
    "log_bg": "#1d1d1b",
    "log_fg": "#d9e8e2",
}


def res(name):
    """exe 안에 함께 묶인 파일 (아이콘 등)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


# ------------------------------------------------------------ 상태 점검

def detect_game():
    try:
        return bk.find_game(None).game
    except SystemExit:
        return None


def valid_game(path):
    if not path:
        return None
    p = os.path.normpath(path)
    if os.path.basename(p).lower() == "blippo+_data":
        p = os.path.dirname(p)
    return p if os.path.isdir(bk.Paths(p).bundles) else None


def load_trans():
    try:
        units, _ = bk.read_units(TRANS)
        return {(u["asset"], u["path"]): u["ko"] for u in units if (u.get("ko") or "").strip()}
    except Exception:
        return {}


def game_state(game, trans):
    if not game:
        return "none"
    if not trans:
        return "unknown"
    try:
        return "patched" if bk.looks_patched(bk.Paths(game), trans) else "original"
    except Exception:
        return "unknown"


def game_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s" % GAME_EXE, "/NH"],
                             capture_output=True, text=True, timeout=5,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return GAME_EXE.lower() in (out or "").lower()
    except Exception:
        return False


def has_backup():
    try:
        return bool(bk.Backup(BACKUP).load_manifest().get("files"))
    except Exception:
        return False


# ------------------------------------------------------- 작업 스레드 출력

class QueueWriter:
    """print() 출력을 줄 단위로 큐에 넣는다. 줄바꿈 없이 끝나는 출력("읽는 중 ...")은
    flush 때 'partial' 로 보내 상태 줄에 바로 띄운다."""

    def __init__(self, q):
        self.q = q
        self.buf = ""

    def write(self, s):
        self.buf += s.replace("\r", "\n")
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self.q.put(("log", line))
        return len(s)

    def flush(self):
        if self.buf:
            self.q.put(("partial", self.buf))

    def isatty(self):
        return False


# 로그 줄 -> (단계 이름, 진행률 구간). 앞에서부터 처음 맞는 것을 쓴다.
INSTALL_STAGES = [
    ("[1/4]", "1/4  한국어 문장을 넣는 중", 1, 20),
    ("[2/4]", "2/4  글꼴을 보정하는 중", 20, 24),
    ("programguide_assets_all.bundle 읽는 중", "2/4  편성표 글꼴을 보정하는 중", 24, 34),
    ("[3/4]", "3/4  게임 데이터를 고치는 중", 36, 38),
    ("sharedassets0.assets 읽는 중", "3/4  자막·에피소드를 고치는 중", 38, 80),
    ("sharedassets1.assets 읽는 중", "3/4  메뉴·펨토팩스를 고치는 중", 81, 90),
    ("[4/4]", "4/4  마무리하는 중", 91, 93),
    ("검증 중", "설치 결과를 확인하는 중", 93, 100),
]
VERIFY_STAGES = [
    ("번들 읽는 중", "번역 원본을 대조하는 중", 2, 22),
    ("sharedassets0.assets 읽는 중", "자막·에피소드를 대조하는 중", 24, 84),
    ("sharedassets1.assets 읽는 중", "메뉴·펨토팩스를 대조하는 중", 85, 99),
]


# ------------------------------------------------------------------ 창

class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.busy = None          # 진행 중인 작업 이름
        self.t0 = 0.0
        self.stage_lo, self.stage_hi = 0, 100
        self.stages = []
        self.restore_total = 0
        self.restore_done = 0
        self.trans = load_trans()

        root.title("Blippo+ 한글 패치")
        root.configure(bg=C["bg"])
        root.minsize(620, 560)
        try:
            root.iconbitmap(res("icon.ico"))
        except Exception:
            pass
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.fonts()
        self.style()
        self.build()

        self.game = valid_game(detect_game())
        self.refresh()
        self.root.after(80, self.pump)

        if not os.path.isfile(TRANS):
            self.missing_translation()
        else:
            self.greet()

    def greet(self):
        try:
            n = sum(1 for u in bk.read_units(TRANS)[0] if (u.get("ko") or "").strip())
            self.write("번역 %s개를 불러왔습니다." % format(n, ","), "dim")
        except Exception:
            pass
        if self.game:
            self.write("게임 폴더: %s" % self.game, "dim")
        else:
            self.write("게임 폴더를 찾지 못했습니다. '찾아보기'로 Blippo+ 설치 폴더를 지정하세요.", "err")
        self.write("게임을 끈 상태에서 '한글 패치 설치'를 누르세요. "
                   "설치 뒤 게임의 Options → Language → 한국어 를 고르면 됩니다.", "dim")

    # --------------------------------------------------------- 모양

    def fonts(self):
        fam = "맑은 고딕"
        self.f_base = (fam, 10)
        self.f_small = (fam, 9)
        self.f_title = (fam, 17, "bold")
        self.f_sub = (fam, 10)
        self.f_bold = (fam, 10, "bold")
        self.f_btn = (fam, 11, "bold")
        self.f_log = ("Consolas", 9)

    def style(self):
        s = ttk.Style(self.root)
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure(".", font=self.f_base, background=C["bg"], foreground=C["ink"])
        s.configure("Card.TFrame", background=C["panel"], relief="flat")
        s.configure("TLabel", background=C["bg"], foreground=C["ink"])
        s.configure("Card.TLabel", background=C["panel"], foreground=C["ink"])
        s.configure("Muted.TLabel", background=C["panel"], foreground=C["muted"], font=self.f_small)
        s.configure("Head.TLabel", background=C["ink"], foreground="#ffffff", font=self.f_title)
        s.configure("HeadSub.TLabel", background=C["ink"], foreground="#b9d6cc", font=self.f_sub)
        s.configure("Field.TLabel", background=C["panel"], foreground=C["muted"], font=self.f_bold)

        s.configure("Primary.TButton", font=self.f_btn, foreground="#ffffff",
                    background=C["accent"], borderwidth=0, focusthickness=0, padding=(18, 10))
        s.map("Primary.TButton",
              background=[("disabled", "#b9c9c3"), ("active", C["accent_hi"])],
              foreground=[("disabled", "#eef3f1")])
        s.configure("Secondary.TButton", font=self.f_btn, foreground=C["ink"],
                    background="#e9e6da", borderwidth=0, focusthickness=0, padding=(14, 10))
        s.map("Secondary.TButton",
              background=[("disabled", "#efede6"), ("active", "#dedacb")],
              foreground=[("disabled", "#aaa79d")])
        s.configure("Small.TButton", font=self.f_small, padding=(10, 4),
                    background="#e9e6da", borderwidth=0)
        s.map("Small.TButton", background=[("active", "#dedacb")])

        s.configure("TEntry", fieldbackground="#faf9f5", bordercolor=C["line"],
                    lightcolor=C["line"], darkcolor=C["line"])
        s.configure("Horizontal.TProgressbar", troughcolor="#e9e6da", background=C["accent"],
                    bordercolor="#e9e6da", lightcolor=C["accent"], darkcolor=C["accent"],
                    thickness=14)

    def build(self):
        r = self.root

        # 머리
        head = tk.Frame(r, bg=C["ink"])
        head.pack(fill="x")
        inner = tk.Frame(head, bg=C["ink"])
        inner.pack(fill="x", padx=22, pady=(16, 14))
        ttk.Label(inner, text="Blippo+ 한글 패치", style="Head.TLabel").pack(anchor="w")
        ttk.Label(inner, text="v%s  ·  7,696개 문장  ·  자막 · 에피소드 · 펨토팩스 · 메뉴" % VERSION,
                  style="HeadSub.TLabel").pack(anchor="w", pady=(2, 0))
        tk.Frame(r, bg=C["accent"], height=3).pack(fill="x")

        body = tk.Frame(r, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=18, pady=16)

        # 게임 폴더 + 상태
        card = ttk.Frame(body, style="Card.TFrame", padding=(16, 14))
        card.pack(fill="x")
        ttk.Label(card, text="게임 폴더", style="Field.TLabel").grid(row=0, column=0, sticky="w")
        self.path_var = tk.StringVar()
        ent = ttk.Entry(card, textvariable=self.path_var, state="readonly", font=self.f_small)
        ent.grid(row=1, column=0, sticky="ew", pady=(4, 0), ipady=3)
        self.btn_browse = ttk.Button(card, text="찾아보기…", style="Small.TButton",
                                     command=self.browse)
        self.btn_browse.grid(row=1, column=1, padx=(8, 0), pady=(4, 0))
        card.columnconfigure(0, weight=1)

        st = tk.Frame(card, bg=C["panel"])
        st.grid(row=2, column=0, columnspan=2, sticky="w", pady=(12, 0))
        self.dot = tk.Label(st, text="●", bg=C["panel"], fg=C["off"], font=(self.f_base[0], 12))
        self.dot.pack(side="left")
        self.state_var = tk.StringVar(value="확인 중…")
        tk.Label(st, textvariable=self.state_var, bg=C["panel"], fg=C["ink"],
                 font=self.f_bold).pack(side="left", padx=(6, 0))

        # 버튼
        bar = tk.Frame(body, bg=C["bg"])
        bar.pack(fill="x", pady=(14, 0))
        self.btn_install = ttk.Button(bar, text="한글 패치 설치", style="Primary.TButton",
                                      command=self.install)
        self.btn_install.pack(side="left")
        self.btn_restore = ttk.Button(bar, text="원본으로 되돌리기", style="Secondary.TButton",
                                      command=self.restore)
        self.btn_restore.pack(side="left", padx=(10, 0))
        self.btn_verify = ttk.Button(bar, text="설치 확인", style="Secondary.TButton",
                                     command=self.verify)
        self.btn_verify.pack(side="left", padx=(10, 0))

        # 진행
        prog = ttk.Frame(body, style="Card.TFrame", padding=(16, 12))
        prog.pack(fill="x", pady=(14, 0))
        top = tk.Frame(prog, bg=C["panel"])
        top.pack(fill="x")
        self.stage_var = tk.StringVar(value="대기 중")
        tk.Label(top, textvariable=self.stage_var, bg=C["panel"], fg=C["ink"],
                 font=self.f_bold).pack(side="left")
        self.time_var = tk.StringVar(value="")
        tk.Label(top, textvariable=self.time_var, bg=C["panel"], fg=C["muted"],
                 font=self.f_small).pack(side="right")
        self.pbar = ttk.Progressbar(prog, mode="determinate", maximum=100,
                                    style="Horizontal.TProgressbar")
        self.pbar.pack(fill="x", pady=(8, 4))
        self.detail_var = tk.StringVar(value="")
        ttk.Label(prog, textvariable=self.detail_var, style="Muted.TLabel").pack(anchor="w")

        # 기록
        logf = tk.Frame(body, bg=C["bg"])
        logf.pack(fill="both", expand=True, pady=(14, 0))
        self.log = ScrolledText(logf, height=10, font=self.f_log, bg=C["log_bg"], fg=C["log_fg"],
                                insertbackground=C["log_fg"], relief="flat", borderwidth=0,
                                padx=10, pady=8, wrap="word")
        self.log.pack(fill="both", expand=True)
        self.log.tag_configure("err", foreground="#ff8a80")
        self.log.tag_configure("ok", foreground="#5fd3a0")
        self.log.tag_configure("dim", foreground="#8f9b96")
        self.log.configure(state="disabled")

        foot = tk.Frame(r, bg=C["bg"])
        foot.pack(fill="x", padx=18, pady=(0, 12))
        tk.Label(foot, text="설치할 때 원본 파일을 이 프로그램 옆 backup 폴더에 보관합니다. "
                            "지우지 마세요.",
                 bg=C["bg"], fg=C["muted"], font=self.f_small).pack(anchor="w")

    # ------------------------------------------------------- 상태 표시

    def refresh(self):
        self.path_var.set(self.game or "찾지 못했습니다 — '찾아보기'로 지정하세요")
        running = game_running() if self.game else False
        state = game_state(self.game, self.trans)
        if not self.game:
            self.set_state("bad", "Blippo+ 설치 폴더를 찾지 못했습니다")
        elif running:
            self.set_state("warn", "게임이 실행 중입니다 — 종료한 뒤 진행하세요")
        elif state == "patched" and not has_backup():
            self.set_state("ok", "한글 패치가 적용되어 있습니다 (이 폴더에는 원본 백업이 없음)")
        elif state == "patched":
            self.set_state("ok", "한글 패치가 적용되어 있습니다")
        elif state == "original":
            self.set_state("off", "원본 상태입니다 (한글 패치 없음)")
        else:
            self.set_state("warn", "상태를 확인할 수 없습니다")

        idle = self.busy is None
        can_touch = idle and self.game and not running and os.path.isfile(TRANS)
        self.btn_install.state(["!disabled"] if can_touch else ["disabled"])
        self.btn_restore.state(["!disabled"] if (can_touch and has_backup()) else ["disabled"])
        self.btn_verify.state(["!disabled"] if (idle and self.game and os.path.isfile(TRANS))
                              else ["disabled"])
        self.btn_browse.state(["!disabled"] if idle else ["disabled"])
        self.btn_install.configure(text="다시 설치" if state == "patched" else "한글 패치 설치")

    def set_state(self, kind, text):
        self.dot.configure(fg=C.get(kind, C["off"]))
        self.state_var.set(text)

    def write(self, line, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")

    # ------------------------------------------------------------ 동작

    def browse(self):
        d = filedialog.askdirectory(title="Blippo+ 설치 폴더를 고르세요",
                                    initialdir=self.game or os.path.expanduser("~"))
        if not d:
            return
        g = valid_game(d)
        if not g:
            messagebox.showerror(
                "Blippo+ 폴더가 아닙니다",
                "선택한 폴더에서 Blippo+ 게임 파일을 찾지 못했습니다.\n\n"
                "Steam 라이브러리에서 Blippo+ 를 우클릭하고\n"
                "관리 → 로컬 파일 보기 로 열리는 폴더를 고르세요.")
            return
        self.game = g
        self.refresh()

    def install(self):
        if game_running():
            messagebox.showwarning("게임이 실행 중입니다", "Blippo+ 를 완전히 종료한 뒤 다시 시도하세요.")
            self.refresh()
            return
        again = game_state(self.game, self.trans) == "patched"
        msg = ("이미 한글 패치가 적용되어 있습니다.\n다시 설치할까요?\n\n"
               "(번역이 새로 나온 경우 다시 설치하면 반영됩니다.)\n\n" if again else "")
        msg += "설치에는 5~15분 정도 걸립니다.\n그동안 이 창을 닫거나 게임을 켜지 마세요."
        if not messagebox.askokcancel("한글 패치 설치", msg):
            return
        ns = argparse.Namespace(game=self.game, backup_dir=BACKUP, input=TRANS, slot=SLOT,
                                dry_run=False, no_font_fix=False, no_crc_fix=False)
        self.start("install", bk.cmd_apply, ns, INSTALL_STAGES)

    def restore(self):
        if game_running():
            messagebox.showwarning("게임이 실행 중입니다", "Blippo+ 를 완전히 종료한 뒤 다시 시도하세요.")
            self.refresh()
            return
        if not messagebox.askokcancel("원본으로 되돌리기",
                                      "한글 패치를 지우고 게임 파일을 원래대로 되돌립니다.\n계속할까요?"):
            return
        try:
            self.restore_total = len(bk.Backup(BACKUP).load_manifest().get("files", {}))
        except Exception:
            self.restore_total = 5
        ns = argparse.Namespace(game=self.game, backup_dir=BACKUP)
        self.start("restore", bk.cmd_restore, ns, [])

    def verify(self):
        ns = argparse.Namespace(game=self.game, backup_dir=BACKUP, input=TRANS, slot=SLOT)
        self.start("verify", bk.cmd_verify, ns, VERIFY_STAGES)

    # ------------------------------------------------------ 작업 실행

    def start(self, kind, fn, ns, stages):
        self.busy = kind
        self.stages = stages
        self.stage_lo, self.stage_hi = -1, -1
        self.restore_done = 0
        self.t0 = time.time()
        self.pbar.configure(value=0)
        self.detail_var.set("")
        self.stage_var.set({"install": "설치를 시작합니다",
                            "restore": "원본 파일을 되돌리는 중",
                            "verify": "설치 상태를 확인하는 중"}[kind])
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.refresh()
        threading.Thread(target=self.worker, args=(kind, fn, ns), daemon=True).start()

    def worker(self, kind, fn, ns):
        q = self.q
        old = sys.stdout, sys.stderr
        sys.stdout = QueueWriter(q)
        sys.stderr = QueueWriter(q)
        bk.PROGRESS_HOOK = lambda label, n, total: q.put(("prog", label, n, total))
        code, msg = 0, ""
        try:
            fn(ns)
        except SystemExit as e:
            if isinstance(e.code, str):
                code, msg = 1, e.code
            else:
                code = e.code or 0
        except Exception as e:
            code, msg = 1, "%s: %s" % (type(e).__name__, e)
            for line in traceback.format_exc().splitlines():
                q.put(("log", line))
        finally:
            try:
                sys.stdout.flush()
            except Exception:
                pass
            bk.PROGRESS_HOOK = None
            sys.stdout, sys.stderr = old
        q.put(("done", kind, code, msg))

    def pump(self):
        try:
            while True:
                item = self.q.get_nowait()
                self.handle(item)
        except queue.Empty:
            pass
        if self.busy:
            secs = int(time.time() - self.t0)
            self.time_var.set("경과 %d:%02d" % (secs // 60, secs % 60))
        self.root.after(80, self.pump)

    def handle(self, item):
        kind = item[0]
        if kind == "log":
            line = item[1]
            if not line.strip():
                return
            bad = ("!" in line[:10] or "오류" in line or "Traceback" in line
                   or re.search(r"불일치\s+[1-9]", line))
            good = ("완료" in line or "이상 없음" in line
                    or re.search(r"(\d[\d,]*) / \1개 일치", line))
            if "타입트리를 맞추지 못한" in line:
                bad, good = False, False
                self.write(line.rstrip(), "dim")
            else:
                self.write(line.rstrip(), "err" if bad else "ok" if good else None)
            self.on_line(line)
        elif kind == "partial":
            # "…읽는 중 ..." 처럼 줄이 끝나기 전에 온 출력 — 로딩이 시작될 때 바로 단계를 바꾼다
            self.detail_var.set(item[1].strip())
            self.on_line(item[1])
        elif kind == "prog":
            _, label, n, total = item
            if total:
                frac = max(0.0, min(1.0, float(n) / float(total)))
                self.pbar.configure(value=self.stage_lo + (self.stage_hi - self.stage_lo) * frac)
                self.detail_var.set("%s  %s / %s" % (label.strip(), format(n, ","),
                                                     format(total, ",")))
        elif kind == "done":
            self.finish(item[1], item[2], item[3])

    def on_line(self, line):
        for key, name, lo, hi in self.stages:
            if key in line and (lo, hi) != (self.stage_lo, self.stage_hi):
                self.stage_var.set(name)
                self.stage_lo, self.stage_hi = lo, hi
                self.pbar.configure(value=lo)
                break
        if self.busy == "restore" and "복구:" in line and self.restore_total:
            self.restore_done += 1
            self.pbar.configure(value=min(100.0, 100.0 * self.restore_done / self.restore_total))
            self.detail_var.set("%d / %d개 파일" % (self.restore_done, self.restore_total))
        if "저장 중" in line:
            self.detail_var.set("파일을 쓰는 중…")

    def finish(self, kind, code, msg):
        self.busy = None
        self.pbar.configure(value=100 if code == 0 else self.pbar["value"])
        self.time_var.set(self.time_var.get().replace("경과", "걸린 시간"))
        self.detail_var.set("")
        if msg:
            self.write(msg, "err")
        self.refresh()

        if kind == "install":
            if code == 0:
                self.stage_var.set("설치 완료")
                messagebox.showinfo("설치 완료",
                                    "한글 패치를 설치했습니다.\n\n"
                                    "게임을 실행한 뒤\n"
                                    "Options → Language → 한국어\n"
                                    "를 선택하세요.")
            else:
                self.stage_var.set("설치하지 못했습니다")
                messagebox.showerror("설치 실패",
                                     "설치 중 문제가 생겼습니다.\n\n%s\n\n"
                                     "게임을 완전히 종료했는지 확인하고 다시 시도하세요.\n"
                                     "계속 실패하면 '원본으로 되돌리기'로 복구할 수 있습니다."
                                     % (msg or "아래 기록을 확인하세요."))
        elif kind == "restore":
            if code == 0:
                self.stage_var.set("원본으로 되돌렸습니다")
                messagebox.showinfo("되돌리기 완료", "게임 파일을 원래대로 되돌렸습니다.")
            else:
                self.stage_var.set("되돌리지 못했습니다")
                messagebox.showerror("되돌리기 실패", msg or "아래 기록을 확인하세요.")
        elif kind == "verify":
            if code == 0:
                self.stage_var.set("이상 없음 — 모든 한국어가 들어가 있습니다")
                messagebox.showinfo("설치 확인", "이상 없습니다.\n모든 파일에서 한국어가 확인되었습니다.")
            else:
                self.stage_var.set("한국어가 빠진 곳이 있습니다")
                messagebox.showwarning("설치 확인",
                                       "한글 패치가 적용되지 않았거나 일부만 적용되어 있습니다.\n\n"
                                       "'한글 패치 설치'를 다시 실행하세요.")

    # ------------------------------------------------------------ 기타

    def missing_translation(self):
        inside_zip = "\\temp\\" in APP.lower() or "\\tmp\\" in APP.lower()
        extra = ("\n\n압축 파일 안에서 바로 실행한 것 같습니다.\n압축을 먼저 푼 뒤 실행하세요."
                 if inside_zip else "")
        messagebox.showerror("번역 파일이 없습니다",
                             "blippo_ko.json 을 찾을 수 없습니다.\n"
                             "이 프로그램과 같은 폴더에 있어야 합니다." + extra)
        self.refresh()

    def on_close(self):
        if self.busy in ("install", "restore"):
            if not messagebox.askyesno(
                    "작업 중입니다",
                    "게임 파일을 고치는 중입니다.\n지금 닫으면 게임 파일이 손상될 수 있습니다.\n\n"
                    "그래도 닫을까요?", icon="warning"):
                return
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
