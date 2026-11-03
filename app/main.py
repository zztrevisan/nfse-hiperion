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

from . import certificate
from .adn import AdnClient
from .documents import fmt, parse_list
from .security import protect, unprotect
from .store import Store, data_dir
from .sync import Syncer
from .version import APP_NAME, APP_VERSION

ECAC_PROCURACAO = "https://cav.receita.fazenda.gov.br/ecac/"
STATUS_LABEL = {"ok": "Baixado", "vazio": "Nada novo", "sem_procuracao": "Sem procuração",
                "erro": "Erro", "cancelado": "Cancelado", "fila": "Na fila", "rodando": "Baixando…"}


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} — {APP_VERSION}"); self.geometry("980x780"); self.minsize(820, 640)
        icon = resource_path("assets/app.ico")
        if icon.is_file():
            try: self.iconbitmap(str(icon))
            except tk.TclError: pass
        self.store, self.events = Store(), queue.Queue()
        self.worker, self.stop_flag = None, threading.Event()
        self.logger = self._make_logger()
        self._build(); self._load(); self.after(100, self._drain)
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
        header = ttk.Frame(self, padding=(12, 8, 12, 0)); header.pack(fill="x")
        logo = resource_path("assets/logo-header.png")
        if logo.is_file():
            self.logo_image = tk.PhotoImage(file=str(logo))
            ttk.Label(header, image=self.logo_image).pack(side="left")
        title = ttk.Frame(header); title.pack(side="left", padx=14)
        ttk.Label(title, text="NFS-e em lote", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(title, text="Um certificado, várias empresas — procuração eletrônica no ADN",
                  font=("Segoe UI", 10)).pack(anchor="w")

        body = ttk.Frame(self, padding=12); body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)

        # 1. Certificado
        cert = ttk.LabelFrame(body, text="1. Certificado do procurador (A1 .pfx / .p12)", padding=10)
        cert.grid(row=0, column=0, sticky="ew"); cert.columnconfigure(1, weight=1)
        self.cert_path, self.cert_pass = tk.StringVar(), tk.StringVar()
        self.remember = tk.BooleanVar(value=True)
        ttk.Label(cert, text="Arquivo").grid(row=0, column=0, sticky="w")
        ttk.Entry(cert, textvariable=self.cert_path).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(cert, text="Escolher…", command=self._choose_cert).grid(row=0, column=2)
        ttk.Label(cert, text="Senha").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(cert, textvariable=self.cert_pass, show="•").grid(row=1, column=1, sticky="ew", padx=6, pady=(6, 0))
        ttk.Button(cert, text="Testar", command=self._test_cert).grid(row=1, column=2, pady=(6, 0))
        ttk.Checkbutton(cert, text="Lembrar senha neste computador (protegida pelo Windows)",
                        variable=self.remember).grid(row=2, column=1, sticky="w", padx=6, pady=(4, 0))
        self.cert_info = ttk.Label(cert, text="", foreground="#555")
        self.cert_info.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))

        # 2. Pasta
        dest = ttk.LabelFrame(body, text="2. Pasta onde salvar", padding=10)
        dest.grid(row=1, column=0, sticky="ew", pady=8); dest.columnconfigure(0, weight=1)
        self.root_path = tk.StringVar()
        ttk.Entry(dest, textvariable=self.root_path).grid(row=0, column=0, sticky="ew")
        ttk.Button(dest, text="Escolher…", command=self._choose_root).grid(row=0, column=1, padx=(6, 0))
        ttk.Button(dest, text="Abrir", command=lambda: self._open(self.root_path.get())).grid(row=0, column=2, padx=(6, 0))
        ttk.Label(dest, text="Fica: EMPRESA - CNPJ \\ Ano \\ Mês \\ Emitidas | Recebidas | Eventos",
                  foreground="#555").grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        # 3. Empresas + resultado
        mid = ttk.Frame(body); mid.grid(row=2, column=0, sticky="nsew"); body.rowconfigure(2, weight=1)
        mid.columnconfigure(1, weight=1); mid.rowconfigure(0, weight=1)

        lst = ttk.LabelFrame(mid, text="3. CNPJ das empresas", padding=10)
        lst.grid(row=0, column=0, sticky="nsew", padx=(0, 8)); lst.rowconfigure(1, weight=1)
        ttk.Label(lst, text="Um por linha (pode colar com nome, ponto, traço…)", foreground="#555").grid(row=0, column=0, columnspan=2, sticky="w")
        self.cnpj_text = tk.Text(lst, width=30, height=10, font=("Consolas", 10), undo=True)
        self.cnpj_text.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=4)
        ttk.Button(lst, text="Importar TXT…", command=self._import_txt).grid(row=2, column=0, sticky="ew")
        ttk.Button(lst, text="Conferir lista", command=self._check_list).grid(row=2, column=1, sticky="ew", padx=(4, 0))
        self.list_info = ttk.Label(lst, text="", foreground="#555"); self.list_info.grid(row=3, column=0, columnspan=2, sticky="w")

        res = ttk.LabelFrame(mid, text="Resultado — dois cliques abre a pasta da empresa", padding=10)
        res.grid(row=0, column=1, sticky="nsew"); res.rowconfigure(0, weight=1); res.columnconfigure(0, weight=1)
        cols = (("doc", "CNPJ", 140), ("name", "Empresa", 220), ("status", "Situação", 110),
                ("new", "Novos", 60), ("nsu", "Último NSU", 80), ("msg", "Detalhe", 260))
        self.tree = ttk.Treeview(res, columns=[c[0] for c in cols], show="headings", height=10)
        for key, text, width in cols:
            self.tree.heading(key, text=text); self.tree.column(key, width=width, stretch=key in ("name", "msg"))
        for tag, bg in (("ok", "#d9f2df"), ("vazio", "#eef1f4"), ("sem_procuracao", "#fff1cc"),
                        ("erro", "#ffd9d9"), ("cancelado", "#eef1f4"), ("rodando", "#dbe9ff")):
            self.tree.tag_configure(tag, background=bg)
        scroll = ttk.Scrollbar(res, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew"); scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<Double-1>", self._open_company)

        # 4. Ações
        act = ttk.Frame(body); act.grid(row=3, column=0, sticky="ew", pady=(8, 0)); act.columnconfigure(3, weight=1)
        self.from_zero = tk.BooleanVar(value=False)
        self.run_button = ttk.Button(act, text="Baixar XMLs", command=self._start)
        self.run_button.grid(row=0, column=0)
        self.stop_button = ttk.Button(act, text="Parar", command=self._stop, state="disabled")
        self.stop_button.grid(row=0, column=1, padx=6)
        ttk.Checkbutton(act, text="Baixar tudo de novo (ignora o último NSU)", variable=self.from_zero).grid(row=0, column=2, padx=6)
        ttk.Button(act, text="Procuração no e-CAC", command=lambda: webbrowser.open(ECAC_PROCURACAO)).grid(row=0, column=4)
        self.progress = ttk.Progressbar(act, maximum=1); self.progress.grid(row=1, column=0, columnspan=5, sticky="ew", pady=(8, 2))
        self.status = ttk.Label(act, text="Pronto"); self.status.grid(row=2, column=0, columnspan=5, sticky="w")

        self.log = tk.Text(body, height=6, state="disabled", wrap="word", font=("Consolas", 9))
        self.log.grid(row=4, column=0, sticky="nsew", pady=(6, 0))
        ttk.Label(body, text=f"{APP_NAME} {APP_VERSION} — Guilherme Andrade dos Santos Trevisan",
                  foreground="#888", font=("Segoe UI", 8)).grid(row=5, column=0, sticky="e")

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

    def _test_cert(self):
        try:
            _, info = certificate.load(Path(self.cert_path.get().strip()), self.cert_pass.get())
        except RuntimeError as exc:
            self.cert_info.configure(text=f"✗ {exc}", foreground="#a40000"); return None
        self.cert_info.configure(foreground="#165b2b", text=(
            f"✓ {info.holder} — {fmt(info.document) or 'documento não identificado'} — válido até {info.expires:%d/%m/%Y}"))
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
        self.list_info.configure(text=text, foreground="#a40000" if invalid else "#555")
        if not quiet and invalid:
            messagebox.showwarning("CNPJ inválido", "Estes não passaram no dígito verificador e serão ignorados:\n\n"
                                   + "\n".join(fmt(d) for d in invalid))
        return docs

    def _start(self):
        docs = self._check_list(quiet=True)
        root = self.root_path.get().strip()
        if not docs: messagebox.showwarning("Lista vazia", "Digite ou importe pelo menos um CNPJ."); return
        if not root: messagebox.showwarning("Pasta", "Escolha a pasta onde salvar."); return
        try:
            context, info = certificate.load(Path(self.cert_path.get().strip()), self.cert_pass.get())
        except RuntimeError as exc:
            messagebox.showerror("Certificado", str(exc)); return
        self._test_cert()
        Path(root).mkdir(parents=True, exist_ok=True)
        self._save(docs)
        if self.from_zero.get() and not messagebox.askyesno(
                "Baixar tudo de novo", "Vai baixar a caixa inteira de cada empresa desde o NSU 0. Pode demorar. Continuar?"):
            return
        self.stop_flag.clear()
        self.run_button.configure(state="disabled"); self.stop_button.configure(state="normal")
        self.progress.configure(maximum=len(docs), value=0)
        for d in docs: self._row(d, status="fila", new="", msg="")
        self._log(f"Certificado: {info.holder} ({fmt(info.document)}) — {len(docs)} empresa(s)")
        syncer = Syncer(AdnClient(context, info.document), self.store, Path(root),
                        cancelled=self.stop_flag.is_set)
        from_zero = self.from_zero.get()

        def work():
            totals = {}
            for i, d in enumerate(docs):
                if self.stop_flag.is_set(): break
                self.events.put(("start", d, i))
                result = syncer.run_one(d, from_zero, progress=lambda n, d=d: self.events.put(("count", d, n)))
                totals[result.status] = totals.get(result.status, 0) + 1
                self.events.put(("result", result, i + 1))
            self.events.put(("done", totals))
        self.worker = threading.Thread(target=work, daemon=True); self.worker.start()

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


def main(): App().mainloop()


if __name__ == "__main__":
    main()
