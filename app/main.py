import logging
import os
import queue
import threading
import webbrowser
import sys
from datetime import date
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .database import Database, data_dir
from .folders import find_a1_certificate, legal_name_from_folder
from .importer import read_sieg_companies, scan_legalization_certificates, write_report
from .models import Company
from .providers import AdnProvider, SimulationProvider
from .security import protect
from .service import BatchService
from .version import APP_NAME, APP_VERSION

PORTAL_NFSE = "https://www.nfse.gov.br/EmissorNacional"


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative


class QueueHandler(logging.Handler):
    def __init__(self, events):
        super().__init__(); self.events = events
    def emit(self, record):
        self.events.put(("log", self.format(record)))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} — {APP_VERSION}"); self.geometry("930x760"); self.minsize(780, 650)
        icon = resource_path("assets/app.ico")
        if icon.is_file():
            try: self.iconbitmap(str(icon))
            except tk.TclError: pass
        self.db, self.events = Database(), queue.Queue()
        self.result_records, self.show_errors_only = [], False
        self.logger = self._make_logger()
        self._build(); self._refresh(); self.after(100, self._drain); self.after(300, self._first_run)

    def _make_logger(self):
        logger = logging.getLogger("nfse_lote"); logger.setLevel(logging.INFO); logger.handlers.clear()
        folder = data_dir() / "logs"; folder.mkdir(exist_ok=True)
        formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
        file_handler = logging.FileHandler(folder / f"execucao-{date.today().isoformat()}.log", encoding="utf-8")
        screen_handler = QueueHandler(self.events)
        file_handler.setFormatter(formatter); screen_handler.setFormatter(formatter)
        logger.addHandler(file_handler); logger.addHandler(screen_handler)
        return logger

    def _build(self):
        header = ttk.Frame(self, padding=(12, 8, 12, 0)); header.pack(fill="x")
        logo = resource_path("assets/logo-header.png")
        if logo.is_file():
            self.logo_image = tk.PhotoImage(file=str(logo))
            ttk.Label(header, image=self.logo_image).pack(side="left")
        title = ttk.Frame(header); title.pack(side="left", padx=14)
        ttk.Label(title, text="NFS-e em lote", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(title, text="Hiperion Assessoria Contábil", font=("Segoe UI", 10)).pack(anchor="w")
        tabs = ttk.Notebook(self); tabs.pack(fill="both", expand=True, padx=10, pady=10); self.tabs = tabs
        run, companies, config = (ttk.Frame(tabs, padding=14) for _ in range(3))
        tabs.add(run, text="Baixar"); tabs.add(companies, text="Empresas"); tabs.add(config, text="Configurações")
        now = date.today(); self.month = tk.IntVar(value=now.month); self.year = tk.IntVar(value=now.year)
        ttk.Label(run, text="Competência (mês / ano)").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Spinbox(run, from_=1, to=12, width=5, textvariable=self.month).grid(row=1, column=0, sticky="w")
        ttk.Spinbox(run, from_=2020, to=2100, width=8, textvariable=self.year).grid(row=1, column=1, sticky="w")
        ttk.Label(run, text="Empresa").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.company_choice = tk.StringVar(value="Todas as empresas")
        self.company_combo = ttk.Combobox(run, textvariable=self.company_choice, state="readonly", width=42)
        self.company_combo.grid(row=1, column=2, sticky="ew", padx=(12, 0))
        self.simulation = tk.BooleanVar(value=True)
        self.download_issued = tk.BooleanVar(value=False); self.download_received = tk.BooleanVar(value=True)
        ttk.Checkbutton(run, text="Emitidas / Prestados (saídas)", variable=self.download_issued).grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Checkbutton(run, text="Recebidas / Tomados (entradas)", variable=self.download_received).grid(row=3, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(run, text="Modo simulação (não consulta a API)", variable=self.simulation).grid(row=4, column=0, columnspan=3, sticky="w", pady=10)
        self.run_button = ttk.Button(run, text="Iniciar download", command=self._start)
        self.run_button.grid(row=5, column=0, columnspan=3, sticky="ew")
        self.progress = ttk.Progressbar(run, maximum=1); self.progress.grid(row=6, column=0, columnspan=3, sticky="ew", pady=10)
        self.status = ttk.Label(run, text="Pronto"); self.status.grid(row=7, column=0, columnspan=3, sticky="w")
        summary = ttk.Frame(run); summary.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(10, 6))
        self.summary_vars = {key: tk.StringVar(value="0") for key in ("processed", "success", "empty", "error")}
        for column, (key, label) in enumerate((("processed", "Processadas"), ("success", "Baixadas"), ("empty", "Sem notas"), ("error", "Erros"))):
            card = ttk.LabelFrame(summary, text=label, padding=(18, 7)); card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 5, 0))
            ttk.Label(card, textvariable=self.summary_vars[key], font=("Segoe UI", 16, "bold")).pack()
            summary.columnconfigure(column, weight=1)
        ttk.Label(run, text="Resultado por empresa — dê dois cliques para ver detalhes ou abrir a pasta").grid(row=9, column=0, columnspan=2, sticky="w", pady=(4, 2))
        self.error_button = ttk.Button(run, text="Ver pendências (0)", command=self._toggle_errors)
        self.error_button.grid(row=9, column=2, sticky="e", pady=(4, 2))
        self.result_tree = ttk.Treeview(run, columns=("company", "result", "detail"), show="headings", height=8)
        for key, title, width in (("company", "Empresa", 280), ("result", "Situação", 110), ("detail", "Detalhe", 360)):
            self.result_tree.heading(key, text=title); self.result_tree.column(key, width=width)
        self.result_tree.tag_configure("success", background="#d9f2df", foreground="#165b2b")
        self.result_tree.tag_configure("empty", background="#ffd9d9", foreground="#8b0000")
        self.result_tree.tag_configure("error", background="#ffd9d9", foreground="#8b0000")
        self.result_tree.bind("<Double-1>", self._open_result)
        self.result_tree.grid(row=10, column=0, columnspan=3, sticky="nsew")
        self.log = tk.Text(run, height=7, state="disabled", wrap="word"); self.log.grid(row=11, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
        run.columnconfigure(2, weight=1); run.rowconfigure(10, weight=1); run.rowconfigure(11, weight=1)
        self.company_count = tk.StringVar(value="0 empresas cadastradas")
        ttk.Label(companies, textvariable=self.company_count, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
        self.tree = ttk.Treeview(companies, columns=("cnpj", "name", "cert"), show="headings")
        for key, title, width in (("cnpj", "CNPJ", 130), ("name", "Razão social", 260), ("cert", "Certificado", 280)):
            self.tree.heading(key, text=title); self.tree.column(key, width=width)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _event: self._edit_company())
        bar = ttk.Frame(companies); bar.pack(fill="x", pady=8)
        ttk.Button(bar, text="Adicionar", command=self._company_dialog).pack(side="left")
        ttk.Button(bar, text="Editar", command=self._edit_company).pack(side="left", padx=6)
        ttk.Button(bar, text="Importar…", command=self._import_companies).pack(side="left", padx=6)
        ttk.Button(bar, text="Excluir", command=self._delete).pack(side="left", padx=6)
        ttk.Label(config, text="Pasta raiz FISCAL do ano (exemplo: H:\\2026)").pack(anchor="w")
        line = ttk.Frame(config); line.pack(fill="x", pady=8)
        self.root_path = tk.StringVar(value=self.db.setting("clients_root"))
        ttk.Entry(line, textvariable=self.root_path).pack(side="left", fill="x", expand=True)
        ttk.Button(line, text="Escolher…", command=self._choose_root).pack(side="left", padx=6)
        ttk.Button(config, text="Salvar configuração", command=self._save_config).pack(anchor="w")
        ttk.Label(config, text="Não selecione a pasta de Legalização/certificados aqui. Cada empresa deve aparecer logo abaixo desta raiz.").pack(anchor="w", pady=(4, 0))
        ttk.Label(config, text=f"{APP_NAME} — versão {APP_VERSION}", foreground="#555555").pack(anchor="w", pady=(16, 2))
        ttk.Label(
            config, text="Desenvolvido por Guilherme Andrade dos Santos Trevisan",
            foreground="#777777", font=("Segoe UI", 8),
        ).pack(anchor="w")

    def _first_run(self):
        if self.db.setting("setup_complete") == "1": return
        messagebox.showinfo(
            "Primeira configuração",
            "Bem-vindo! Primeiro escolha a raiz fiscal do ano. Depois, cadastre as empresas e os certificados A1.",
        )
        suggested = Path(f"H:\\{date.today().year}")
        selected = filedialog.askdirectory(
            title="Selecione a raiz fiscal do ano",
            initialdir=str(suggested) if suggested.is_dir() else None,
        )
        if selected:
            self.root_path.set(selected)
            self.db.set_setting("clients_root", selected)
            self.db.set_setting("setup_complete", "1")
            self.tabs.select(1)
            messagebox.showinfo("Próximo passo", "Raiz fiscal salva. Agora cadastre as empresas e os certificados A1.")
        else:
            self.tabs.select(2)

    def _choose_root(self):
        selected = filedialog.askdirectory(title="Selecione a raiz fiscal do ano (ex.: H:\\2026)")
        if selected: self.root_path.set(selected)
    def _save_config(self):
        self.db.set_setting("clients_root", self.root_path.get().strip()); self.db.set_setting("setup_complete", "1"); messagebox.showinfo("Configuração", "Raiz fiscal do ano salva.")
    def _refresh(self):
        for item in self.tree.get_children(): self.tree.delete(item)
        companies = self.db.companies()
        self.company_count.set(f"{len(companies)} empresa(s) cadastrada(s)")
        for c in companies: self.tree.insert("", "end", iid=str(c.id), values=(c.cnpj, c.legal_name, c.certificate_path))
        choices = ["Todas as empresas"] + [f"{c.legal_name} — {c.cnpj}" for c in companies]
        self.company_combo.configure(values=choices)
        if self.company_choice.get() not in choices: self.company_choice.set("Todas as empresas")
    def _delete(self):
        selected = self.tree.selection()
        if selected and messagebox.askyesno("Excluir", "Excluir a empresa selecionada?"):
            self.db.delete_company(int(selected[0])); self._refresh()

    def _edit_company(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Editar empresa", "Selecione uma empresa na lista.")
            return
        company_id = int(selected[0])
        company = next((item for item in self.db.companies() if item.id == company_id), None)
        if company:
            self._company_dialog(company)

    def _import_companies(self):
        saved_sheet = self.db.setting("sieg_spreadsheet")
        default_sheet = Path.home() / "OneDrive - Hiperion Contabil" / "Área de Trabalho" / "Cadastros-31-08-2026.xlsx"
        suggested_sheet = Path(saved_sheet) if saved_sheet else default_sheet
        spreadsheet = filedialog.askopenfilename(
            title="Importar — selecione a planilha Cadastros do SIEG",
            initialdir=str(suggested_sheet.parent) if suggested_sheet.parent.is_dir() else None,
            initialfile=suggested_sheet.name if suggested_sheet.is_file() else None,
            filetypes=[("Planilha Excel do SIEG", "*.xlsx")],
        )
        if not spreadsheet:
            return
        self.db.set_setting("sieg_spreadsheet", spreadsheet)
        saved_root = self.db.setting("legalization_root")
        default_root = Path(saved_root) if saved_root else Path.home() / "Hiperion Contabil" / "Hiperion Contabil Intranet - Documentos" / "LEGALIZAÇÃO"
        selected_root = filedialog.askdirectory(
            title="Importar — selecione a pasta LEGALIZAÇÃO",
            initialdir=str(default_root) if default_root.is_dir() else None,
        )
        if not selected_root:
            return
        self.db.set_setting("legalization_root", selected_root)
        try:
            companies = read_sieg_companies(Path(spreadsheet))
            items = scan_legalization_certificates(Path(selected_root), companies)
        except PermissionError:
            messagebox.showerror(
                "Importação",
                "O Windows bloqueou a leitura da planilha. Feche o Excel e confirme que o arquivo está disponível offline no OneDrive.",
            )
            return
        except Exception as exc:
            messagebox.showerror("Importação", f"Não foi possível analisar os arquivos:\n{exc}")
            return
        ready = [item for item in items if item.status == "PRONTO"]
        expired = sum(item.status == "VENCIDO" for item in items)
        errors = sum(item.status == "ERRO" for item in items)
        if not messagebox.askyesno(
            "Conferir importação",
            f"Certificados válidos e mais recentes: {len(ready)}\n"
            f"Vencidos: {expired}\nIlegíveis/senha inválida: {errors}\n"
            f"Outras pendências: {len(items) - len(ready) - expired - errors}\n\n"
            "Cadastrar somente os certificados prontos?",
        ):
            return
        for item in ready:
            self.db.upsert_company(Company(None, item.cnpj, item.legal_name, item.certificate, protect(item.password)))
        report = data_dir() / "relatorio-legalizacao.csv"
        write_report(report, items)
        self._refresh()
        messagebox.showinfo(
            "Importação concluída",
            f"Cadastros incluídos/atualizados: {len(ready)}\n\nRelatório salvo em:\n{report}\n\n"
            "Foram ignorados certificados vencidos, ilegíveis e versões anteriores.",
        )

    def _company_dialog(self, company=None):
        dialog = tk.Toplevel(self); dialog.title("Editar empresa" if company else "Adicionar empresa"); dialog.transient(self); dialog.grab_set()
        fields = {}
        for row, (key, label, show) in enumerate((("cnpj", "CNPJ", ""), ("name", "Razão social", ""), ("cert", "Certificado A1", ""), ("password", "Senha do A1", "*"))):
            ttk.Label(dialog, text=label).grid(row=row, column=0, sticky="w", padx=10, pady=7)
            fields[key] = tk.StringVar(); ttk.Entry(dialog, textvariable=fields[key], show=show, width=55).grid(row=row, column=1, padx=10, pady=7)
        if company:
            fields["cnpj"].set(company.cnpj)
            fields["name"].set(company.legal_name)
            fields["cert"].set(str(company.certificate_path))
        def choose():
            selected = filedialog.askopenfilename(filetypes=[("Certificado A1", "*.pfx *.p12")])
            if selected: fields["cert"].set(selected)
        ttk.Button(dialog, text="Escolher…", command=choose).grid(row=2, column=2, padx=8)
        def choose_company_folder():
            selected = filedialog.askdirectory(title="Selecione a pasta NUMERO BOX - RAZAO SOCIAL")
            if not selected: return
            folder = Path(selected); fields["name"].set(legal_name_from_folder(folder))
            try: fields["cert"].set(str(find_a1_certificate(folder)))
            except Exception as exc: messagebox.showwarning("Certificado", str(exc), parent=dialog)
        ttk.Button(dialog, text="Ler pasta do cliente…", command=choose_company_folder).grid(row=4, column=0, padx=10, pady=10, sticky="w")
        def save():
            cnpj = "".join(ch for ch in fields["cnpj"].get() if ch.isdigit()); cert = Path(fields["cert"].get().strip())
            if len(cnpj) != 14 or not fields["name"].get().strip() or cert.suffix.lower() not in {".pfx", ".p12"}:
                messagebox.showerror("Dados inválidos", "Informe CNPJ, razão social e certificado PFX/P12.", parent=dialog); return
            password = protect(fields["password"].get()) if fields["password"].get() else (company.encrypted_password if company else b"")
            try: self.db.save_company(Company(company.id if company else None, cnpj, fields["name"].get().strip(), cert, password))
            except Exception as exc: messagebox.showerror("Erro", str(exc), parent=dialog); return
            dialog.destroy(); self._refresh()
        ttk.Button(dialog, text="Salvar", command=save).grid(row=4, column=1, sticky="e", padx=10, pady=10)

    def _start(self):
        root, companies = Path(self.root_path.get().strip()), self.db.companies()
        selected_company = self.company_choice.get()
        if selected_company != "Todas as empresas":
            selected_cnpj = selected_company.rsplit("—", 1)[-1].strip()
            companies = [company for company in companies if company.cnpj == selected_cnpj]
        directions = set()
        if self.download_issued.get(): directions.add("Emitidas")
        if self.download_received.get(): directions.add("Recebidas")
        if not directions: messagebox.showerror("Tipo de nota", "Marque Emitidas, Recebidas ou ambas."); return
        if not root.is_dir(): messagebox.showerror("Configuração", "Selecione uma raiz fiscal válida, por exemplo H:\\2026."); return
        if not companies: messagebox.showerror("Empresas", "A empresa selecionada não foi encontrada."); return
        for item in self.result_tree.get_children(): self.result_tree.delete(item)
        self.result_records.clear(); self.show_errors_only = False; self.error_button.configure(text="Ver pendências (0)"); self._update_summary()
        self.run_button.state(["disabled"]); self.progress.configure(value=0, maximum=max(1, len(companies)))
        service = BatchService(SimulationProvider() if self.simulation.get() else AdnProvider(), self.logger)
        def status(done, total, text): self.events.put(("status", done, total, text))
        def result(company, state, detail, paths): self.events.put(("result", company.cnpj, company.legal_name, state, detail, paths))
        def worker(): self.events.put(("done", *service.run(companies, root, self.year.get(), self.month.get(), status, directions, result)))
        threading.Thread(target=worker, daemon=True).start()

    def _toggle_errors(self):
        self.show_errors_only = not self.show_errors_only
        self._render_results()

    def _render_results(self):
        for item in self.result_tree.get_children():
            self.result_tree.delete(item)
        labels = {"success": "Baixado", "empty": "Sem notas", "error": "Erro"}
        pending = sum(record[2] in {"empty", "error"} for record in self.result_records)
        for cnpj, company, state, detail, _paths in self.result_records:
            if self.show_errors_only and state not in {"empty", "error"}:
                continue
            self.result_tree.insert("", "end", iid=cnpj, values=(company, labels[state], detail), tags=(state,))
        self.error_button.configure(text=("Ver todos" if self.show_errors_only else f"Ver pendências ({pending})"))
        self._update_summary()

    def _update_summary(self):
        counts = {state: sum(record[2] == state for record in self.result_records) for state in ("success", "empty", "error")}
        self.summary_vars["processed"].set(str(len(self.result_records)))
        for state in ("success", "empty", "error"):
            self.summary_vars[state].set(str(counts[state]))

    def _open_result(self, _event=None):
        selected = self.result_tree.selection()
        if not selected:
            return
        record = next((item for item in self.result_records if item[0] == selected[0]), None)
        if not record:
            return
        _cnpj, company, state, detail, paths = record
        if state == "empty":
            webbrowser.open(PORTAL_NFSE)
            return
        if state == "error":
            path_text = "\n".join(f"{label}: {path}" for label, path in paths.items())
            messagebox.showerror("Detalhes do erro", f"{company}\n\n{detail}\n\n{path_text}")
            root = paths.get("Empresa") or paths.get("Pasta pesquisada")
            if root and Path(root).is_dir() and messagebox.askyesno("Abrir pasta", "Deseja abrir a pasta pesquisada?"):
                os.startfile(root)
            return
        available = [(direction, path) for direction, path in paths.items()
                     if direction in {"Emitidas", "Recebidas"} and Path(path).is_dir()]
        if not available:
            messagebox.showwarning("Pasta", "A pasta de destino não está disponível.")
            return
        if len(available) == 1:
            os.startfile(available[0][1]); return
        choice = messagebox.askyesnocancel(
            "Abrir pasta", "Qual pasta deseja abrir?\n\nSim: Tomados / Recebidas\nNão: Prestados / Emitidas"
        )
        if choice is None:
            return
        wanted = "Recebidas" if choice else "Emitidas"
        path = next((path for direction, path in available if direction == wanted), None)
        if path:
            os.startfile(path)

    def _drain(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "log":
                    self.log.configure(state="normal"); self.log.insert("end", event[1] + "\n"); self.log.see("end"); self.log.configure(state="disabled")
                elif event[0] == "status":
                    _, done, total, text = event; self.progress.configure(value=done, maximum=max(1, total)); self.status.configure(text=text)
                elif event[0] == "result":
                    _, cnpj, company, state, detail, paths = event
                    self.result_records.append((cnpj, company, state, detail, paths)); self._render_results()
                elif event[0] == "done":
                    _, ok, empty, failed = event; self.run_button.state(["!disabled"]); self.status.configure(text=f"Finalizado: {ok} baixada(s), {empty} sem notas, {failed} erro(s)"); messagebox.showinfo("Lote finalizado", f"Baixadas: {ok}\nSem notas: {empty}\nErros: {failed}")
        except queue.Empty: pass
        self.after(100, self._drain)


def main(): App().mainloop()
if __name__ == "__main__": main()
