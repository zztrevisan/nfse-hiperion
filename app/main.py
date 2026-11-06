import logging
import os
import queue
import sys
import threading
import webbrowser
from datetime import date
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import tkinter.font as tkfont

import sv_ttk

from . import certificate, report
from .adn import AdnClient
from .documents import fmt, parse_list
from .security import protect, unprotect
from .store import Store, data_dir
from .sync import Syncer
from .version import APP_NAME, APP_VERSION

PALETTES = {
    "light": dict(BRAND="#1f4e79", INK="#1f2937", MUTED="#6b7280", LINE="#c3ccd6", SIDE="#f3f6f9",
                  CARD="#ffffff", FIELD="#ffffff", LOGBG="#f6f8fa",
                  GREEN="#1e7a3c", AMBER="#b7791f", RED="#c0392b", BLUE="#1a3d7c",
                  ROWS={"ok": ("#d3eedb", "#14532d"), "vazio": ("#ffffff", "#4b5563"),
                        "sem_procuracao": ("#ffecb8", "#7a4b00"), "erro": ("#f9d4d4", "#8b1a1a"),
                        "cancelado": ("#f1f3f5", "#4b5563"), "rodando": ("#d2e3fc", "#1a3d7c"),
                        "fila": ("#ffffff", "#6b7280")}),
    "dark": dict(BRAND="#16324f", INK="#e6e8eb", MUTED="#9aa3ad", LINE="#4a5058", SIDE="#23272c",
                 CARD="#2b3036", FIELD="#1e2125", LOGBG="#1a1d21",
                 GREEN="#5cc98a", AMBER="#e8b45a", RED="#f07b6f", BLUE="#8fb4f5",
                 ROWS={"ok": ("#1f3a2a", "#b9f0cf"), "vazio": ("#1c1c1c", "#c3c9d0"),
                       "sem_procuracao": ("#3d3217", "#f5d796"), "erro": ("#45211f", "#ffc2bb"),
                       "cancelado": ("#26292d", "#c3c9d0"), "rodando": ("#1e2f4d", "#bcd3ff"),
                       "fila": ("#1c1c1c", "#9aa3ad")}),
}
BRAND = INK = MUTED = LINE = SIDE = CARD = FIELD = LOGBG = GREEN = AMBER = RED = BLUE = ""
ROWS: dict = {}


def set_palette(name: str) -> None:
    globals().update(PALETTES[name])


set_palette("light")
UI_FONT = ["Segoe UI"]  # trocada em _build se a máquina não tiver a Segoe UI
ECAC_PROCURACAO = "https://cav.receita.fazenda.gov.br/ecac/"
STATUS_LABEL = {"ok": "Baixado", "vazio": "Nada novo", "sem_procuracao": "Sem procuração",
                "erro": "Erro", "cancelado": "Cancelado", "fila": "Na fila", "rodando": "Baixando…"}


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} — {APP_VERSION}"); self.geometry("1240x800"); self.minsize(1080, 680)
        icon = resource_path("assets/app.ico")
        if icon.is_file():
            try: self.iconbitmap(str(icon))
            except tk.TclError: pass
        self.store, self.events = Store(), queue.Queue()
        self.worker, self.stop_flag = None, threading.Event()
        self.logger = self._make_logger()
        self.theme = self.store.get("theme", "light") if self.store.get("theme") in PALETTES else "light"
        self._build(); self._load(); self.after(100, self._drain); self.after(300, self._keep_opaque)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _make_logger(self):
        logger = logging.getLogger("nfse"); logger.setLevel(logging.INFO); logger.handlers.clear()
        folder = data_dir() / "logs"; folder.mkdir(exist_ok=True)
        handler = logging.FileHandler(folder / f"execucao-{date.today().isoformat()}.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        logger.addHandler(handler)
        return logger

    # ── Tela ────────────────────────────────────────────────────────────────
    def _build(self):
        families = set(tkfont.families(self))
        UI_FONT[0] = next((f for f in ("Segoe UI Variable Text", "Segoe UI", "Calibri", "Arial")
                           if f in families), "TkDefaultFont")
        set_palette(self.theme)
        sv_ttk.set_theme(self.theme)
        for name in ("TkDefaultFont", "TkTextFont", "TkHeadingFont", "TkMenuFont", "SunValleyBodyFont",
                     "SunValleyBodyStrongFont", "SunValleyCaptionFont"):
            try: tkfont.nametofont(name, self).configure(family=UI_FONT[0])
            except tk.TclError: pass
        style = ttk.Style(self)
        style.configure(".", font=(UI_FONT[0], 10))
        style.configure("Side.TFrame", background=SIDE)
        style.configure("Side.TLabel", background=SIDE)
        style.configure("SideTitle.TLabel", background=SIDE, font=(UI_FONT[0], 10, "bold"), foreground=INK)
        style.configure("SideHint.TLabel", background=SIDE, foreground=MUTED, font=(UI_FONT[0], 9))
        style.configure("Side.TCheckbutton", background=SIDE)
        style.configure("Treeview", rowheight=28)
        style.configure("Treeview.Heading", font=(UI_FONT[0], 9, "bold"))
        style.configure("Big.Accent.TButton", font=(UI_FONT[0], 11, "bold"), padding=(22, 8))
        # Tk 8.6 + tema com imagens: sem isso o fundo das tags da Treeview é ignorado (só a cor do texto aparece).
        style.map("Treeview", background=[("selected", "#2f6fb5")], foreground=[("selected", "#ffffff")])
        self.configure(bg=CARD)

        # Cabeçalho
        header = tk.Frame(self, bg=BRAND, height=68); header.pack(fill="x"); header.pack_propagate(False)
        badge = resource_path("assets/logo-badge.png")
        if badge.is_file():
            self.logo_image = tk.PhotoImage(file=str(badge))
            tk.Label(header, image=self.logo_image, bg=BRAND).pack(side="left", padx=(16, 0))
        tk.Label(header, text="NFS-e em lote", bg=BRAND, fg="white",
                 font=(UI_FONT[0], 16, "bold")).pack(side="left", padx=(14, 14))
        tk.Label(header, text="Hiperion Assessoria Contábil · um certificado, várias empresas", bg=BRAND,
                 fg="#c9d8ee", font=(UI_FONT[0], 10)).pack(side="left")
        tk.Label(header, text=f"v{APP_VERSION}", bg=BRAND, fg="#c9d8ee", font=(UI_FONT[0], 9)).pack(side="right", padx=(8, 20))
        toggle = tk.Label(header, text="☀  Tema claro" if self.theme == "dark" else "☾  Tema escuro", bg=BRAND,
                          fg="white", font=(UI_FONT[0], 9), cursor="hand2", padx=10, pady=4,
                          highlightthickness=1, highlightbackground="#5f86b3")
        toggle.pack(side="right")
        toggle.bind("<Button-1>", lambda _e: self._toggle_theme())

        shell = ttk.Frame(self); shell.pack(fill="both", expand=True)
        shell.columnconfigure(1, weight=1); shell.rowconfigure(0, weight=1)

        # ── Barra lateral: configuração em passos ──
        side = ttk.Frame(shell, style="Side.TFrame", padding=(18, 14), width=350)
        side.grid(row=0, column=0, sticky="nsew"); side.grid_propagate(False); side.columnconfigure(0, weight=1)
        r = 0

        def title(text):
            nonlocal r
            ttk.Label(side, text=text, style="SideTitle.TLabel").grid(row=r, column=0, sticky="w", pady=(14 if r else 0, 4))
            r += 1

        def row(widget, **kw):
            nonlocal r
            widget.grid(row=r, column=0, sticky=kw.pop("sticky", "ew"), **kw)
            r += 1
            return widget

        self.cert_path, self.cert_pass = tk.StringVar(), tk.StringVar()
        self.remember = tk.BooleanVar(value=True)
        title("1  Certificado A1 do escritório")
        line = row(ttk.Frame(side, style="Side.TFrame")); line.columnconfigure(0, weight=1)
        ttk.Entry(line, textvariable=self.cert_path).grid(row=0, column=0, sticky="ew")
        self._btn(line, text="…", width=3, command=self._choose_cert).grid(row=0, column=1, padx=(4, 0))
        line = row(ttk.Frame(side, style="Side.TFrame"), pady=(6, 0)); line.columnconfigure(0, weight=1)
        ttk.Entry(line, textvariable=self.cert_pass, show="•").grid(row=0, column=0, sticky="ew")
        self._btn(line, text="Testar", command=self._test_cert).grid(row=0, column=1, padx=(4, 0))
        row(ttk.Checkbutton(side, text="Lembrar senha neste PC", variable=self.remember, style="Side.TCheckbutton"),
            sticky="w", pady=(4, 0))
        self.cert_info = row(ttk.Label(side, text="Escolha o .pfx e digite a senha", style="SideHint.TLabel",
                                       wraplength=310), sticky="w")

        self.root_path = tk.StringVar()
        title("2  Pasta de destino")
        line = row(ttk.Frame(side, style="Side.TFrame")); line.columnconfigure(0, weight=1)
        ttk.Entry(line, textvariable=self.root_path).grid(row=0, column=0, sticky="ew")
        self._btn(line, text="…", width=3, command=self._choose_root).grid(row=0, column=1, padx=(4, 0))
        self._btn(line, text="Abrir", command=lambda: self._open(self.root_path.get())).grid(row=0, column=2, padx=(4, 0))
        row(ttk.Label(side, text="EMPRESA - CNPJ \\ Ano \\ Mês \\ Emitidas | Recebidas", style="SideHint.TLabel"), sticky="w")

        title("3  Empresas (CNPJ)")
        box = row(ttk.Frame(side, style="Side.TFrame"), sticky="nsew"); side.rowconfigure(r - 1, weight=1)
        box.columnconfigure(0, weight=1); box.rowconfigure(0, weight=1)
        self.cnpj_text = tk.Text(box, height=6, font=("Consolas", 10), undo=True, relief="flat", bd=0, bg=FIELD, fg=INK, insertbackground=INK,
                                 highlightthickness=1, highlightbackground=LINE, highlightcolor=BRAND, padx=6, pady=4)
        self.cnpj_text.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.cnpj_text.yview); sb.grid(row=0, column=1, sticky="ns")
        self.cnpj_text.configure(yscrollcommand=sb.set)
        line = row(ttk.Frame(side, style="Side.TFrame"), pady=(6, 0)); line.columnconfigure((0, 1), weight=1)
        self._btn(line, text="Importar TXT", command=self._import_txt).grid(row=0, column=0, sticky="ew")
        self._btn(line, text="Conferir", command=self._check_list).grid(row=0, column=1, sticky="ew", padx=(4, 0))
        self.list_info = row(ttk.Label(side, text="", style="SideHint.TLabel", wraplength=310), sticky="w")

        prev = date.fromordinal(date.today().replace(day=1).toordinal() - 1)  # padrão: mês anterior
        self.by_competence = tk.BooleanVar(value=False)
        self.comp_vars = [tk.IntVar(value=prev.month), tk.IntVar(value=prev.year),
                          tk.IntVar(value=prev.month), tk.IntVar(value=prev.year)]
        title("4  Competência")
        row(ttk.Checkbutton(side, text="Baixar só este período", variable=self.by_competence,
                            command=self._toggle_competence, style="Side.TCheckbutton"), sticky="w")
        comp = row(ttk.Frame(side, style="Side.TFrame"), sticky="w", pady=(4, 0))
        self.comp_widgets = []
        for i, (label, (m, y)) in enumerate((("de", self.comp_vars[:2]), ("até", self.comp_vars[2:]))):
            ttk.Label(comp, text=label, style="Side.TLabel", width=4).grid(row=i, column=0, sticky="w", pady=2)
            for col, (var, lo, hi, width) in enumerate(((m, 1, 12, 4), (y, 2020, 2100, 6)), 1):
                spin = ttk.Spinbox(comp, from_=lo, to=hi, width=width, textvariable=var)
                spin.grid(row=i, column=col, padx=(0, 6), pady=2); self.comp_widgets.append(spin)
        self.comp_hint = row(ttk.Label(side, text="", style="SideHint.TLabel", wraplength=310), sticky="w")
        self.from_zero = tk.BooleanVar(value=False)
        self.from_zero_box = row(ttk.Checkbutton(side, text="Baixar tudo de novo (desde o NSU 0)",
                                                 variable=self.from_zero, style="Side.TCheckbutton"), sticky="w", pady=(2, 0))
        self._toggle_competence()

        # ── Área principal ──
        main = ttk.Frame(shell, padding=(20, 16)); main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1); main.rowconfigure(3, weight=1)

        actions = ttk.Frame(main); actions.grid(row=0, column=0, sticky="ew"); actions.columnconfigure(2, weight=1)
        self.run_button = ttk.Button(actions, text="Baixar XMLs", style="Big.Accent.TButton", command=self._start)
        self.run_button.grid(row=0, column=0)
        stop = self._btn(actions, text="Parar", command=self._stop, state="disabled")
        stop.grid(row=0, column=1, padx=8); self.stop_button = stop.button
        self._btn(actions, text="Relatório de faturamento", command=self._report).grid(row=0, column=3)
        self._btn(actions, text="Procuração no e-CAC ↗",
                   command=lambda: webbrowser.open(ECAC_PROCURACAO)).grid(row=0, column=4, padx=(8, 0))

        cards = ttk.Frame(main); cards.grid(row=1, column=0, sticky="ew", pady=(16, 10))
        self.card_vars = {}
        for i, (key, label, color) in enumerate((("total", "Empresas", INK), ("ok", "Com notas novas", GREEN),
                                                  ("vazio", "Sem novidade", MUTED), ("sem_procuracao", "Sem procuração", AMBER),
                                                  ("erro", "Com erro", RED))):
            cards.columnconfigure(i, weight=1)
            card = tk.Frame(cards, bg=CARD, highlightthickness=1, highlightbackground=LINE)
            card.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 8, 0))
            tk.Frame(card, bg=color, height=3).pack(fill="x")
            self.card_vars[key] = tk.StringVar(value="0")
            tk.Label(card, textvariable=self.card_vars[key], bg=CARD, fg=color,
                     font=(UI_FONT[0], 20, "bold")).pack(anchor="w", padx=12, pady=(6, 0))
            tk.Label(card, text=label, bg=CARD, fg=MUTED, font=(UI_FONT[0], 9)).pack(anchor="w", padx=12, pady=(0, 8))

        prog = ttk.Frame(main); prog.grid(row=2, column=0, sticky="ew", pady=(0, 10)); prog.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(prog, maximum=1); self.progress.grid(row=0, column=0, sticky="ew")
        self.status = ttk.Label(prog, text="Pronto", foreground=MUTED); self.status.grid(row=1, column=0, sticky="w", pady=(4, 0))

        table = ttk.Frame(main); table.grid(row=3, column=0, sticky="nsew")
        table.rowconfigure(0, weight=1); table.columnconfigure(0, weight=1)
        cols = (("doc", "CNPJ", 150), ("name", "Empresa", 240), ("status", "Situação", 130),
                ("new", "Novos", 60), ("nsu", "Último NSU", 85), ("msg", "Detalhe", 280))
        self.tree = ttk.Treeview(table, columns=[c[0] for c in cols], show="headings")
        for key, text, width in cols:
            self.tree.heading(key, text=text, anchor="w")
            self.tree.column(key, width=width, stretch=key in ("name", "msg"),
                             anchor="center" if key in ("new", "nsu") else "w")
        for tag, (bg, fg) in ROWS.items():
            self.tree.tag_configure(tag, background=bg, foreground=fg)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew"); scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<Double-1>", self._open_company)
        self.tree.bind("<<TreeviewSelect>>", self._show_detail)
        self.detail = ttk.Label(main, text="Clique numa empresa para ver o detalhe; dois cliques abre a pasta dela.",
                                foreground=MUTED, wraplength=860)
        self.detail.grid(row=4, column=0, sticky="w", pady=(6, 0))

        foot = ttk.Frame(main); foot.grid(row=5, column=0, sticky="ew", pady=(8, 0)); foot.columnconfigure(1, weight=1)
        toggle = self._btn(foot, text="▸ Mostrar log", command=self._toggle_log)
        toggle.grid(row=0, column=0, sticky="w"); self.log_toggle = toggle.button
        ttk.Label(foot, text="Guilherme Andrade dos Santos Trevisan", foreground=MUTED,
                  font=(UI_FONT[0], 8)).grid(row=0, column=2, sticky="e")
        self.log = tk.Text(main, height=7, state="disabled", wrap="word", font=("Consolas", 9), relief="flat",
                           bg=LOGBG, fg=INK, highlightthickness=1, highlightbackground=LINE, padx=8, pady=6)

    def _keep_opaque(self):
        """Desfaz transparência/blur que programas de personalização aplicam em todas as janelas.

        Eles marcam a janela como "layered" com alpha < 255 ou ligam o efeito acrílico do DWM;
        aqui tiramos os dois e repetimos a cada 1,5 s, porque o programa reaplica.
        """
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.winfo_id()) or self.winfo_id()
            GWL_EXSTYLE, WS_EX_LAYERED = -20, 0x00080000
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if style & WS_EX_LAYERED:
                user32.SetLayeredWindowAttributes(hwnd, 0, 255, 0x2)  # LWA_ALPHA = 255 (opaco)
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style & ~WS_EX_LAYERED)

            class ACCENT(ctypes.Structure):
                _fields_ = [("state", ctypes.c_int), ("flags", ctypes.c_int),
                            ("color", ctypes.c_uint), ("anim", ctypes.c_int)]

            class WCAD(ctypes.Structure):
                _fields_ = [("attr", ctypes.c_int), ("data", ctypes.c_void_p), ("size", ctypes.c_size_t)]

            accent = ACCENT(0, 0, 0, 0)  # ACCENT_DISABLED
            data = WCAD(19, ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p), ctypes.sizeof(accent))
            user32.SetWindowCompositionAttribute(wintypes.HWND(hwnd), ctypes.byref(data))
            backdrop = ctypes.c_int(1)  # DWMSBT_NONE: sem Mica/acrílico
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(backdrop), ctypes.sizeof(backdrop))
        except Exception:
            return  # fora do Windows ou API indisponível: não insiste
        self.after(1500, self._keep_opaque)

    def _btn(self, parent, **kw):
        """Botão com contorno visível (o do tema some em fundo claro). Devolve a moldura; o botão fica em .button."""
        frame = tk.Frame(parent, bg=LINE, padx=1, pady=1)
        frame.button = ttk.Button(frame, **kw)
        frame.button.pack(fill="both", expand=True)
        return frame

    def _toggle_theme(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Tema", "Espere o download terminar para trocar o tema."); return
        keep = {name: getattr(self, name).get() for name in
                ("cert_path", "cert_pass", "remember", "root_path", "by_competence", "from_zero")}
        comp = [v.get() for v in self.comp_vars]
        cnpj = self.cnpj_text.get("1.0", "end-1c")
        rows = [(i, self.tree.item(i, "values"), self.tree.item(i, "tags")) for i in self.tree.get_children()]
        log, log_open = self.log.get("1.0", "end-1c"), self.log.winfo_ismapped()
        texts = {name: getattr(self, name).cget("text") for name in ("cert_info", "list_info", "status", "detail")}
        prog = (self.progress["maximum"], self.progress["value"])

        self.theme = "dark" if self.theme == "light" else "light"
        self.store.set("theme", self.theme)
        for child in self.winfo_children():
            child.destroy()
        self._build()

        for name, value in keep.items():
            getattr(self, name).set(value)
        for var, value in zip(self.comp_vars, comp):
            var.set(value)
        self._toggle_competence()
        self.cnpj_text.insert("1.0", cnpj)
        for iid, values, tags in rows:
            self.tree.insert("", "end", iid=iid, values=values, tags=tags)
        self._update_cards()
        self.log.configure(state="normal"); self.log.insert("1.0", log); self.log.configure(state="disabled")
        if log_open: self._toggle_log()
        for name, text in texts.items():
            getattr(self, name).configure(text=text)
        info = texts["cert_info"]
        self.cert_info.configure(foreground=GREEN if info.startswith("✓") else RED if info.startswith("✗") else MUTED)
        self.list_info.configure(foreground=RED if "inválido" in texts["list_info"] else MUTED)
        self.progress.configure(maximum=prog[0], value=prog[1])

    def _toggle_log(self):
        if self.log.winfo_ismapped():
            self.log.grid_remove(); self.log_toggle.configure(text="▸ Mostrar log")
        else:
            self.log.grid(row=6, column=0, sticky="nsew", pady=(6, 0)); self.log_toggle.configure(text="▾ Esconder log")

    def _show_detail(self, _event=None):
        sel = self.tree.selection()
        if sel:
            v = self.tree.item(sel[0], "values")
            self.detail.configure(text=f"{v[0]}  {v[1]} — {v[2] or 'na lista'}: {v[5] or '—'}")

    def _update_cards(self):
        counts = {"total": len(self.tree.get_children())}
        for iid in self.tree.get_children():
            for tag in self.tree.item(iid, "tags"):
                counts[tag] = counts.get(tag, 0) + 1
        for key, var in self.card_vars.items():
            var.set(str(counts.get(key, 0)))

    # ── Estado salvo ────────────────────────────────────────────────────────
    def _load(self):
        self.cert_path.set(self.store.get("cert_path"))
        self.root_path.set(self.store.get("root_path"))
        secret = self.store.get("cert_pass", b"")
        if secret:
            try: self.cert_pass.set(unprotect(secret))
            except OSError: pass
        self.cnpj_text.insert("1.0", self.store.get("cnpj_list"))
        self._check_list(quiet=True)

    def _save(self, docs: list[str]):
        self.store.set("cert_path", self.cert_path.get().strip())
        self.store.set("root_path", self.root_path.get().strip())
        self.store.set("cert_pass", protect(self.cert_pass.get()) if self.remember.get() else b"")
        self.store.set("cnpj_list", "\n".join(fmt(d) for d in docs))

    # ── Ações ──────────────────────────────────────────────────────────────
    def _choose_cert(self):
        path = filedialog.askopenfilename(title="Certificado A1", filetypes=[("Certificado A1", "*.pfx *.p12"), ("Todos", "*.*")])
        if path: self.cert_path.set(path)

    def _choose_root(self):
        path = filedialog.askdirectory(title="Pasta onde salvar as notas", initialdir=self.root_path.get() or None)
        if path: self.root_path.set(path)

    def _toggle_competence(self):
        on = self.by_competence.get()
        if hasattr(self, "from_zero_box"): self.from_zero_box.configure(state="disabled" if on else "normal")
        self.comp_hint.configure(text="Lê a caixa inteira e salva só esse período (não mexe no último NSU)."
                                 if on else "Desmarcado: baixa tudo o que entrou desde a última vez. "
                                            "O período também é usado no relatório.")

    def _competence(self):
        """("AAAA-MM", "AAAA-MM") ou None; levanta ValueError se o período for inválido."""
        if not self.by_competence.get(): return None
        try: m1, y1, m2, y2 = (int(v.get()) for v in self.comp_vars)
        except (tk.TclError, ValueError): raise ValueError("Preencha mês e ano da competência.")
        if not (1 <= m1 <= 12 and 1 <= m2 <= 12): raise ValueError("Mês deve ser de 1 a 12.")
        lo, hi = f"{y1:04d}-{m1:02d}", f"{y2:04d}-{m2:02d}"
        if lo > hi: raise ValueError("A competência inicial é depois da final.")
        return lo, hi

    def _test_cert(self):
        try:
            _, info = certificate.load(Path(self.cert_path.get().strip()), self.cert_pass.get())
        except RuntimeError as exc:
            self.cert_info.configure(text=f"✗ {exc}", foreground=RED); return None
        self.cert_info.configure(foreground=GREEN, text=(
            f"✓ {info.holder}\n{fmt(info.document) or 'documento não identificado'} · válido até {info.expires:%d/%m/%Y}"))
        return info

    def _import_txt(self):
        path = filedialog.askopenfilename(title="Lista de CNPJ", filetypes=[("Texto", "*.txt *.csv"), ("Todos", "*.*")])
        if not path: return
        raw = Path(path).read_bytes()
        try: text = raw.decode("utf-8-sig")
        except UnicodeDecodeError: text = raw.decode("cp1252", errors="replace")
        docs, invalid = parse_list(text)
        current, _ = parse_list(self.cnpj_text.get("1.0", "end"))
        merged = list(dict.fromkeys(current + docs))
        self.cnpj_text.delete("1.0", "end"); self.cnpj_text.insert("1.0", "\n".join(fmt(d) for d in merged))
        self._check_list(quiet=True)
        msg = f"{len(docs)} CNPJ/CPF lidos do arquivo."
        if invalid: msg += f"\n\n{len(invalid)} inválido(s) ignorado(s):\n" + "\n".join(fmt(d) for d in invalid[:20])
        messagebox.showinfo("Importar TXT", msg)

    def _check_list(self, quiet=False):
        docs, invalid = parse_list(self.cnpj_text.get("1.0", "end"))
        known = self.store.companies()
        self.tree.delete(*self.tree.get_children())
        for d in docs:
            c = known.get(d)
            self.tree.insert("", "end", iid=d, values=(fmt(d), c.name if c else "", "", "",
                                                       c.last_nsu if c else 0, f"última consulta {c.last_sync}" if c and c.last_sync else ""))
        text = f"{len(docs)} empresa(s) na lista"
        if invalid: text += f" — {len(invalid)} inválido(s): {', '.join(fmt(d) for d in invalid[:3])}"
        self.list_info.configure(text=text, foreground=RED if invalid else MUTED)
        self._update_cards()
        if not quiet and invalid:
            messagebox.showwarning("CNPJ inválido", "Estes não passaram no dígito verificador e serão ignorados:\n\n"
                                   + "\n".join(fmt(d) for d in invalid))
        return docs

    def _start(self):
        docs = self._check_list(quiet=True)
        root = self.root_path.get().strip()
        if not docs: messagebox.showwarning("Lista vazia", "Digite ou importe pelo menos um CNPJ."); return
        if not root: messagebox.showwarning("Pasta", "Escolha a pasta onde salvar."); return
        try: competence = self._competence()
        except ValueError as exc: messagebox.showwarning("Competência", str(exc)); return
        try:
            context, info = certificate.load(Path(self.cert_path.get().strip()), self.cert_pass.get())
        except RuntimeError as exc:
            messagebox.showerror("Certificado", str(exc)); return
        self._test_cert()
        Path(root).mkdir(parents=True, exist_ok=True)
        self._save(docs)
        if not competence and self.from_zero.get() and not messagebox.askyesno(
                "Baixar tudo de novo", "Vai baixar a caixa inteira de cada empresa desde o NSU 0. Pode demorar. Continuar?"):
            return
        self.stop_flag.clear()
        self.run_button.configure(state="disabled"); self.stop_button.configure(state="normal")
        self.progress.configure(maximum=len(docs), value=0)
        for d in docs: self._row(d, status="fila", new="", msg="")
        period = f" — competência {competence[0]} a {competence[1]}" if competence else ""
        self._log(f"Certificado: {info.holder} ({fmt(info.document)}) — {len(docs)} empresa(s){period}")
        syncer = Syncer(AdnClient(context, info.document), self.store, Path(root),
                        cancelled=self.stop_flag.is_set)
        from_zero = self.from_zero.get()

        def work():
            totals = {}
            for i, d in enumerate(docs):
                if self.stop_flag.is_set(): break
                self.events.put(("start", d, i))
                result = syncer.run_one(d, from_zero, progress=lambda n, d=d: self.events.put(("count", d, n)),
                                        competence=competence)
                totals[result.status] = totals.get(result.status, 0) + 1
                self.events.put(("result", result, i + 1))
            self.events.put(("done", totals))
        self.worker = threading.Thread(target=work, daemon=True); self.worker.start()

    def _report(self):
        """Excel de faturamento entrada/saída do período de/até, lendo os XML já baixados."""
        root = self.root_path.get().strip()
        if not root or not Path(root).is_dir():
            messagebox.showwarning("Relatório", "Escolha a pasta onde as notas foram salvas."); return
        try:
            m1, y1, m2, y2 = (int(v.get()) for v in self.comp_vars)
            start, end = f"{y1:04d}-{m1:02d}", f"{y2:04d}-{m2:02d}"
            if not (1 <= m1 <= 12 and 1 <= m2 <= 12) or start > end: raise ValueError
        except (tk.TclError, ValueError):
            messagebox.showwarning("Relatório", "Confira o período de/até (mês e ano)."); return
        docs = set(self._check_list(quiet=True))
        name = f"Faturamento {start}" + ("" if start == end else f" a {end}") + ".xlsx"
        path = filedialog.asksaveasfilename(title="Salvar relatório", initialdir=root, initialfile=name,
                                            defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
        if not path: return
        rows = report.collect(Path(root), start, end, docs or None)
        if not rows:
            messagebox.showinfo("Relatório", "Nenhuma nota encontrada nesse período nas pastas"
                                + (" das empresas da lista." if docs else ".")); return
        try:
            report.write_xlsx(Path(path), rows, start, end)
        except PermissionError:
            messagebox.showerror("Relatório", "Não deu pra salvar — o arquivo está aberto no Excel?"); return
        self._log(f"Relatório salvo: {path} ({len(rows)} nota(s))")
        os.startfile(path)

    def _stop(self):
        self.stop_flag.set(); self.status.configure(text="Parando depois do lote atual…")

    # ── Eventos do worker ──────────────────────────────────────────────────
    def _drain(self):
        try:
            while True:
                ev = self.events.get_nowait()
                if ev[0] == "start":
                    _, d, i = ev
                    self._row(d, status="rodando")
                    self.status.configure(text=f"{i + 1}/{self.progress['maximum']:.0f} — {fmt(d)}")
                elif ev[0] == "count":
                    self._row(ev[1], new=ev[2])
                elif ev[0] == "result":
                    _, r, done = ev
                    c = self.store.company(r.document)
                    self._row(r.document, status=r.status, new=r.new_files, msg=r.message, name=c.name, nsu=c.last_nsu)
                    self.progress.configure(value=done)
                    line = f"{fmt(r.document)} {c.name} — {STATUS_LABEL[r.status]}: {r.message}"
                    self._log(line)
                    (self.logger.info if r.status in ("ok", "vazio") else self.logger.warning)(line)
                elif ev[0] == "done":
                    t = ev[1]
                    summary = (f"Concluído — {t.get('ok', 0)} com notas novas, {t.get('vazio', 0)} sem novidade, "
                               f"{t.get('sem_procuracao', 0)} sem procuração, {t.get('erro', 0)} com erro")
                    self.status.configure(text=summary); self._log(summary)
                    self.run_button.configure(state="normal"); self.stop_button.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def _row(self, d, status=None, new=None, msg=None, name=None, nsu=None):
        if not self.tree.exists(d): return
        values = list(self.tree.item(d, "values"))
        for idx, val in ((1, name), (2, STATUS_LABEL.get(status) if status else None), (3, new), (4, nsu), (5, msg)):
            if val is not None: values[idx] = val
        self.tree.item(d, values=values, tags=(status,) if status else self.tree.item(d, "tags"))
        if status: self._update_cards()

    def _log(self, text):
        self.log.configure(state="normal"); self.log.insert("end", text + "\n"); self.log.see("end")
        self.log.configure(state="disabled")

    def _open_company(self, _event=None):
        sel = self.tree.selection()
        if not sel: return
        c = self.store.company(sel[0])
        self._open(str(Path(self.root_path.get()) / c.folder) if c.folder else self.root_path.get())

    @staticmethod
    def _open(path):
        if path and Path(path).exists(): os.startfile(path)

    def _close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("Download em andamento", "Parar o download e sair? O que já baixou fica salvo."):
                return
            self.stop_flag.set()
        self.destroy()


def main():
    try:  # nítido em telas com escala 125%/150% (sem isso o Windows borra a janela)
        import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception: pass
    App().mainloop()


if __name__ == "__main__":
    main()
