"""PrivaPII local text-review desktop demonstrator."""

import argparse
import hashlib
import sqlite3
import tkinter as tk
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from batch_export_view import BatchExportView
from export_formats import TEXT_FORMATS, parse_csv, render_export, restore_csv, table_rows
from export_review import inspect_export, retained_identifiers, retained_transcriptions
from ingestion import extract_with_coverage
from nus import NusDetector, checkpoint_ready
from ocr import raster_pages
from ocr_review import Reviewer, ScanProcessor, export_review
from pdf_redaction_view import PdfRedactionView
from pdf_tables import extract_pdf_tables
from person_review_view import PersonReviewView
from policy import ALL_CATEGORIES, CATEGORY_GROUPS, PROFILES, selected_indices
from privapii import TOKEN, Case, Span, hybrid, review_spans
from raster_tables import find_grids
from table_grid_view import TableGridView
from tabular import detect_table
from token_review import compare_tokens
from vault import Workspace, new_id
from word_documents import extract_word, extract_word_tables, write_word


class ChoiceDialog(simpledialog.Dialog):
    def __init__(self, parent, title, values):
        self.values = values
        super().__init__(parent, title)

    def body(self, master):
        self.field = ttk.Combobox(master, values=self.values, state="readonly", width=62)
        self.field.pack(padx=8, pady=6)
        self.field.current(0)
        return self.field

    def apply(self):
        self.result = self.field.current()


class TableDialog(simpledialog.Dialog):
    def __init__(self, parent, tables):
        self.tables = tables
        super().__init__(parent, "Review PDF table before importing")

    def body(self, master):
        values = [f"{'Page ' + str(table.page) + ' · ' if hasattr(table, 'page') else ''}"
                  f"Table {table.number} · {len(table.rows)} rows × {len(table.rows[0])} columns"
                  for table in self.tables]
        self.selector = ttk.Combobox(master, values=values, state="readonly", width=58)
        self.selector.pack(fill="x", pady=(0, 6))
        self.selector.current(0)
        self.selector.bind("<<ComboboxSelected>>", self.refresh)
        frame = ttk.Frame(master)
        frame.pack(fill="both", expand=True)
        self.grid = ttk.Treeview(frame, show="headings", height=10, selectmode="none")
        vertical = ttk.Scrollbar(frame, orient="vertical", command=self.grid.yview)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=self.grid.xview)
        self.grid.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
        self.grid.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.refresh()
        return self.selector

    def refresh(self, _event=None):
        rows = self.tables[self.selector.current()].rows
        self.grid.delete(*self.grid.get_children())
        columns = list(range(len(rows[0])))
        self.grid.configure(columns=columns)
        for index in columns:
            self.grid.heading(index, text=f"Column {index + 1}")
            self.grid.column(index, width=min(180, max(65, 720 // len(columns))), stretch=False)
        for row in rows:
            self.grid.insert("", "end", values=row)

    def apply(self):
        self.result = self.tables[self.selector.current()]


class PolicyDialog(simpledialog.Dialog):
    def __init__(self, parent, categories, name, profiles):
        self.categories, self.name, self.profiles = categories, name, profiles
        super().__init__(parent, "Categories and profiles")

    def body(self, master):
        self.fields = {category: tk.BooleanVar(value=category in self.categories)
                       for category in ALL_CATEGORIES}
        self.selector = ttk.Combobox(master, values=sorted(self.profiles), width=30)
        self.selector.set(self.name)
        self.selector.grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Button(master, text="Load profile", command=self.load).grid(row=0, column=1, sticky="w")
        ttk.Label(master, text="Edit checkboxes and enter a name to save a custom profile.").grid(
            row=1, column=0, columnspan=2, sticky="w", padx=6)
        for index, (title, labels) in enumerate(CATEGORY_GROUPS.items()):
            frame = ttk.LabelFrame(master, text=title, padding=6)
            frame.grid(row=2 + index // 2, column=index % 2, padx=6, pady=6, sticky="nsew")
            for column, (caption, value) in enumerate((("Select group", True), ("Clear group", False))):
                ttk.Button(frame, text=caption, command=lambda labels=labels, value=value:
                           self.set_group(labels, value)).grid(row=0, column=column, sticky="w")
            for position, category in enumerate(labels):
                ttk.Checkbutton(frame, text=category, variable=self.fields[category]).grid(
                    row=1 + position // 2, column=position % 2, sticky="w")
        return self.selector

    def set_group(self, labels, value):
        for label in labels:
            self.fields[label].set(value)

    def load(self):
        categories = self.profiles.get(self.selector.get())
        if categories is not None:
            for category, field in self.fields.items():
                field.set(category in categories)

    def apply(self):
        self.result = (self.selector.get().strip() or "Custom",
                       {category for category, field in self.fields.items() if field.get()})


class App:
    def __init__(self, root, model_dir):
        self.root = root
        self.model_dir = model_dir
        self.detector = None
        self.scan_processor = None
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.case = Case()
        self.document_id = new_id()
        self.document_name = "Pasted text"
        self.document_ids = []
        self.excluded = set()
        self.categories = set(PROFILES["Standard"])
        self.profile_name = "Standard"
        self.session_profiles = dict(PROFILES)
        self.snapshot = None
        self.export_review = None
        self.link_person_forms = tk.BooleanVar(value=False)
        self.form_source = None
        self.restore_overrides = {}
        self.restored_result = None
        self.spans = []
        self.status = tk.StringVar(value="Open or paste a Lithuanian text document.")
        root.title("PrivaPII · Local review")
        root.geometry("1040x760")
        root.minsize(760, 520)
        root.protocol("WM_DELETE_WINDOW", self.close)
        tabs = ttk.Notebook(root)
        tabs.pack(fill="both", expand=True, padx=12, pady=12)
        review, restore = ttk.Frame(tabs, padding=10), ttk.Frame(tabs, padding=10)
        tabs.add(review, text="Review and export")
        tabs.add(restore, text="Restore derived text")
        workspace = ttk.Frame(review)
        workspace.pack(fill="x")
        self.button(workspace, "Create workspace", lambda: self.open_workspace(True))
        self.button(workspace, "Open workspace", lambda: self.open_workspace(False))
        self.button(workspace, "Lock", self.lock_workspace)
        self.button(workspace, "Backup", self.backup_workspace)
        self.button(workspace, "Retention", self.manage_retention)
        self.button(workspace, "New document", self.new_document)
        self.documents = ttk.Combobox(workspace, state="readonly", width=28)
        self.documents.pack(side="left", padx=4)
        self.documents.bind("<<ComboboxSelected>>", self.switch_document)
        self.workspace_label = tk.StringVar(value="Temporary session")
        ttk.Label(workspace, textvariable=self.workspace_label).pack(side="right")
        bar = ttk.Frame(review)
        bar.pack(fill="x")
        self.detect_button = self.button(bar, "Detect", self.detect)
        self.button(bar, "Import document", self.open_source)
        self.table_button = ttk.Menubutton(bar, text="Import table")
        table_menu = tk.Menu(self.table_button, tearoff=False)
        table_menu.add_command(label="Digital PDF", command=self.open_pdf_table)
        table_menu.add_command(label="Word document", command=lambda: self.open_table(word=True))
        self.table_button.configure(menu=table_menu)
        self.table_button.pack(side="left", padx=(0, 6))
        self.scan_button = ttk.Menubutton(bar, text="Review scan")
        scan_menu = tk.Menu(self.scan_button, tearoff=False)
        scan_menu.add_command(label="Document lines", command=self.open_scan)
        scan_menu.add_command(label="Table cells", command=lambda: self.open_scan(table=True))
        self.scan_button.configure(menu=scan_menu)
        self.scan_button.pack(side="left", padx=(0, 6))
        self.button(bar, "Mark selected text", self.mark)
        self.button(bar, "Categories and profiles", self.edit_policy)
        modes = ("Rules only", "NUS only", "NUS + rules") if checkpoint_ready(model_dir) else ("Rules only",)
        self.mode = tk.StringVar(value=modes[-1])
        ttk.Combobox(bar, textvariable=self.mode, values=modes, width=14, state="readonly").pack(side="right")
        panes = ttk.Panedwindow(review, orient="horizontal")
        panes.pack(fill="both", expand=True, pady=8)
        left, right = ttk.Frame(panes), ttk.Frame(panes)
        panes.add(left, weight=3)
        panes.add(right, weight=2)
        self.source = self.text(left, "Source document", 10)
        self.source.tag_configure("detected", background="#ffedbb")
        self.source.bind("<<Modified>>", self.source_changed)
        ttk.Label(right, text="Findings · select rows to edit or link").pack(anchor="w")
        self.findings = tk.Listbox(right, selectmode="extended", exportselection=False)
        self.findings.pack(fill="both", expand=True)
        edits = ttk.Frame(right)
        edits.pack(fill="x")
        self.button(edits, "Toggle exclusion", self.toggle_exclusion)
        self.button(edits, "Edit category", self.edit_category)
        self.button(edits, "Link entity", self.link_entity)
        controls = ttk.Frame(review)
        controls.pack(fill="x")
        self.button(controls, "Pseudonymize", lambda: self.transform(False))
        self.button(controls, "Redact irreversibly", lambda: self.transform(True))
        self.button(controls, "Save reviewed export", self.save_export)
        self.button(controls, "Export workspace ZIP", self.export_workspace)
        self.button(controls, "Review people", self.review_people)
        self.link_checkbox = ttk.Checkbutton(
            controls, text="Expose linked person IDs", variable=self.link_person_forms,
            command=self.clear_export, state="disabled",
        )
        self.link_checkbox.pack(side="left", padx=8)
        self.export = self.text(review, "Export preview · review before sharing", 8, readonly=True)
        self.derived = self.text(restore, "Paste the derived text for this case", 12)
        restore_actions = ttk.Frame(restore)
        restore_actions.pack(fill="x")
        self.derived_format = tk.StringVar(value="Text / Markdown")
        restore_format = ttk.Combobox(restore_actions, textvariable=self.derived_format,
                                     state="readonly", values=("Text / Markdown", "CSV", "Word"), width=16)
        restore_format.pack(side="left", padx=4)
        restore_format.bind("<<ComboboxSelected>>", lambda _: self.reset_restoration())
        self.button(restore_actions, "Import derived text", self.import_derived)
        self.button(restore_actions, "Preview local restoration", self.restore)
        self.button(restore_actions, "Choose verified person form", self.choose_person_form)
        self.button(restore_actions, "Save restored file", self.save_restored_file)
        self.button(restore_actions, "Compare tokens", self.compare_returned_tokens)
        self.restored = self.text(restore, "Restored preview · contains original values", 12, readonly=True)
        self.derived.bind("<<Modified>>", self.derived_changed)
        ttk.Label(root, textvariable=self.status, padding=(12, 0, 12, 10)).pack(fill="x")

    @staticmethod
    def button(parent, title, callback):
        button = ttk.Button(parent, text=title, command=callback)
        button.pack(side="left", padx=(0, 6), pady=4, anchor="w")
        return button

    @staticmethod
    def text(parent, title, height, readonly=False):
        box = ttk.Frame(parent)
        box.pack(fill="both", expand=True, pady=(4, 0))
        ttk.Label(box, text=title).pack(anchor="w")
        text = tk.Text(box, height=height, wrap="word", undo=not readonly)
        scroll = ttk.Scrollbar(box, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set, state="disabled" if readonly else "normal")
        scroll.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        return text

    @staticmethod
    def value(widget):
        return widget.get("1.0", "end-1c")

    @staticmethod
    def replace(widget, value):
        state = widget.cget("state")
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state=state)

    def workspace_active(self):
        return isinstance(self.case, Workspace)

    def clear_export(self):
        self.export_review = None
        self.replace(self.export, "")

    def source_changed(self, _event):
        if self.source.edit_modified():
            self.source.edit_modified(False)
            if self.export_review and self.export_review[0] != self.value(self.source):
                self.clear_export()

    def derived_changed(self, _event):
        if self.derived.edit_modified():
            self.derived.edit_modified(False)
            self.reset_restoration()

    def reset_restoration(self):
        self.form_source = None
        self.restore_overrides.clear()
        self.restored_result = None
        self.replace(self.restored, "")

    def review_current(self):
        text = self.value(self.source)
        if not text.strip():
            return
        previous = self.case.documents.get(self.document_id)
        if previous and text != previous["text"]:
            self.document_id = new_id()
            self.document_name += " (edited)"
        spans = self.spans if self.snapshot == text else []
        self.case.review(self.document_id, self.document_name, text, spans,
                         [index for index, span in enumerate(spans) if span in self.excluded])

    def persist(self):
        if not self.workspace_active():
            return True
        try:
            self.review_current()
            self.case.profiles[self.profile_name] = sorted(self.categories)
            self.case.active_profile = self.profile_name
            self.case.save()
            self.refresh_documents()
            return True
        except (ValueError, OSError, sqlite3.Error) as error:
            messagebox.showerror("Workspace save failed", str(error))
            return False

    def refresh_documents(self):
        self.document_ids = list(self.case.documents)
        self.documents.configure(values=[
            f'{self.case.documents[key]["name"]} · {key[:8]}' for key in self.document_ids
        ])
        if self.document_id in self.document_ids:
            self.documents.current(self.document_ids.index(self.document_id))
        else:
            self.documents.set("")

    def load_document(self, document_id, name="Pasted text", text=""):
        self.document_id, self.document_name = document_id, name
        self.snapshot = None
        self.excluded = set()
        self.replace(self.source, text)
        self.source.edit_reset()
        spans = []
        if self.workspace_active() and document_id in self.case.documents:
            document = self.case.documents[document_id]
            self.document_name = document["name"]
            self.replace(self.source, document["text"])
            self.source.edit_reset()
            self.snapshot = document["text"]
            spans = [Span(**{key: occurrence[key] for key in
                            ("start", "end", "label", "source", "confidence", "validation")})
                     for occurrence in document["occurrences"]]
            self.excluded = {spans[index] for index in document["excluded"]}
        self.show_findings(spans, self.value(self.source))
        if self.workspace_active():
            self.refresh_documents()

    def open_workspace(self, create):
        options = {"filetypes": [("PrivaPII workspace", "*.sqlite")]}
        path = (filedialog.asksaveasfilename(defaultextension=".sqlite", **options)
                if create else filedialog.askopenfilename(**options))
        if not path or not self.persist():
            return
        password = simpledialog.askstring("Workspace passphrase", "Enter the workspace passphrase.",
                                          show="*", parent=self.root)
        if not password:
            return
        if create:
            confirmation = simpledialog.askstring("Confirm passphrase", "Enter the passphrase again.",
                                                  show="*", parent=self.root)
            if confirmation != password:
                messagebox.showerror("Passphrase mismatch", "The workspace was not created.")
                return
        try:
            workspace = Workspace(Path(path), password, create=create)
        except (ValueError, OSError, sqlite3.Error) as error:
            messagebox.showerror("Workspace unavailable", str(error))
            return
        self.case = workspace
        self.link_person_forms.set(False)
        self.link_checkbox.state(["!disabled"])
        self.derived_format.set("Text / Markdown")
        self.reset_restoration()
        self.profile_name = workspace.active_profile
        categories = set(workspace.profiles.get(self.profile_name, PROFILES["Standard"]))
        if self.profile_name == "Standard" and categories == ALL_CATEGORIES - {"DOB"}:
            categories = set(PROFILES["Standard"])
        self.categories = categories
        self.workspace_label.set(f"Unlocked · {workspace.path.name}")
        self.replace(self.derived, "")
        self.derived.edit_reset()
        self.replace(self.restored, "")
        self.load_document(next(iter(workspace.documents), new_id()))
        self.status.set("Workspace unlocked. Import documents or open a saved review.")
        if workspace.retention_review_on and workspace.retention_review_on <= date.today().isoformat():
            self.status.set(f"Workspace retention review due · {workspace.retention_review_on}.")

    def lock_workspace(self):
        if not self.workspace_active() or not self.persist():
            return
        self.case = Case()
        self.link_person_forms.set(False)
        self.link_checkbox.state(["disabled"])
        self.derived_format.set("Text / Markdown")
        self.reset_restoration()
        self.categories = set(PROFILES["Standard"])
        self.profile_name = "Standard"
        self.document_ids = []
        self.documents.configure(values=())
        self.documents.set("")
        self.workspace_label.set("Workspace locked")
        self.load_document(new_id())
        self.replace(self.derived, "")
        self.derived.edit_reset()
        self.replace(self.restored, "")
        self.status.set("Workspace locked. Open it again to restore references.")

    def backup_workspace(self):
        if not self.workspace_active():
            self.status.set("Open a persistent workspace before backing it up.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".sqlite",
                                           initialfile="privapii-backup.sqlite",
                                           filetypes=[("Encrypted workspace", "*.sqlite")])
        if not path or not self.persist():
            return
        try:
            self.case.backup(Path(path))
        except (OSError, ValueError, sqlite3.Error) as error:
            messagebox.showerror("Backup failed", str(error), parent=self.root)
            return
        self.status.set("Encrypted backup verified. Open it with the same workspace passphrase.")

    def manage_retention(self):
        if not self.workspace_active() or not self.persist():
            return
        choices = ["Set retention review date"]
        if self.document_id in self.case.documents:
            choices.append("Forget current document and its exclusive restoration references")
        action = ChoiceDialog(self.root, "Workspace retention", choices).result
        if action is None:
            return
        try:
            if action == 0:
                value = simpledialog.askstring("Retention review", "Enter YYYY-MM-DD, or leave blank to clear.",
                                              initialvalue=self.case.retention_review_on or "", parent=self.root)
                if value is None:
                    return
                self.case.set_retention_review(value.strip())
                self.status.set("Retention review reminder updated.")
                return
            if not messagebox.askyesno(
                    "Forget current document",
                    f"Remove {self.document_name} and its exclusive restoration references from this workspace? "
                    "Existing backups and files remain separate copies.", parent=self.root):
                return
            removed = self.case.forget_document(self.document_id)
            self.load_document(next(iter(self.case.documents), new_id()))
            self.replace(self.derived, "")
            self.reset_restoration()
            self.status.set(f"Document forgotten. {removed} exclusive restoration references removed.")
        except (ValueError, OSError, sqlite3.Error) as error:
            messagebox.showerror("Retention change failed", str(error), parent=self.root)

    def switch_document(self, _event=None):
        index = self.documents.current()
        if index < 0:
            return
        target = self.document_ids[index]
        if target != self.document_id and self.persist():
            self.load_document(target)

    def new_document(self):
        if self.persist():
            self.load_document(new_id())
            self.status.set("Paste text or import a document.")

    def open_source(self):
        paths = filedialog.askopenfilenames(filetypes=[("Supported documents", "*.txt *.tsv *.md *.markdown *.pdf *.docx")])
        if not paths or not self.persist():
            return
        imported = sum_empty = word_count = 0
        mixed_pdfs = []
        for filename in paths:
            try:
                path = Path(filename)
                text, empty, mixed = extract_with_coverage(path)
                if not text.strip():
                    raise ValueError("The document contains no text.")
                self.load_document(new_id(), path.name, text)
                if not self.persist():
                    return
                imported += 1
                sum_empty += empty
                word_count += path.suffix.lower() == ".docx"
                if mixed:
                    mixed_pdfs.append((path, mixed))
                if not self.workspace_active():
                    break
            except (OSError, ValueError) as error:
                messagebox.showerror("Import failed", str(error))
        if imported:
            note = " Word import covers body text and tables. Review headers, footers and images separately." if word_count else ""
            self.status.set(f"{imported} imported. Detect and review extracted text. {sum_empty} PDF pages had no text.{note}")
        if mixed_pdfs:
            details = "\n".join(f"{path.name} · pages {', '.join(map(str, pages))}"
                                for path, pages in mixed_pdfs)
            notice = "These pages contain embedded images alongside native text. Image content needs visual or OCR review.\n\n"
            if len(mixed_pdfs) == 1 and self.workspace_active():
                if messagebox.askyesno("Mixed PDF pages", notice + details + "\n\nOpen this PDF in OCR review?",
                                       parent=self.root):
                    self.open_scan(path=mixed_pdfs[0][0])
            else:
                messagebox.showwarning("Mixed PDF pages", notice + details, parent=self.root)

    def set_processing(self, active):
        for button in (self.detect_button, self.scan_button, self.table_button):
            button.state(["disabled" if active else "!disabled"])

    def open_pdf_table(self):
        self.open_table(word=False)

    def open_table(self, *, word):
        kind, extension, extractor = ("Word", "*.docx", extract_word_tables) if word else (
            "PDF", "*.pdf", extract_pdf_tables)
        path = filedialog.askopenfilename(filetypes=[(kind, extension)])
        if not path or not self.persist():
            return
        workspace = self.case
        self.set_processing(True)
        self.status.set(f"Looking for complete tables in the {kind}…")
        future = self.worker.submit(extractor, Path(path))

        def poll():
            if not future.done():
                self.root.after(100, poll)
                return
            self.set_processing(False)
            if self.case is not workspace:
                return
            try:
                tables = future.result()
                if not tables:
                    self.status.set(f"No complete rectangular table found in the {kind}.")
                    return
                table = TableDialog(self.root, tables).result
                if table is None or not self.persist():
                    return
                page = f"_p{table.page}" if not word else ""
                name = f"{Path(path).stem}{page}_table{table.number}.tsv"
                self.load_document(new_id(), name, table.tsv())
                if self.persist():
                    self.status.set("Table imported. Detect, review and choose CSV in the export preview.")
            except Exception as error:
                self.status.set(f"{kind} table import failed.")
                messagebox.showerror(f"{kind} table import failed", str(error), parent=self.root)

        self.root.after(100, poll)

    def detect(self):
        text = self.value(self.source)
        if not text.strip():
            return
        mode = self.mode.get()
        document_id, workspace = self.document_id, self.case
        self.set_processing(True)
        self.status.set("Detecting on this device…")
        future = self.worker.submit(self.compute_document, text, mode, self.document_name)

        def poll():
            if not future.done():
                self.root.after(100, poll)
                return
            self.set_processing(False)
            try:
                spans = future.result()
            except Exception as error:
                self.status.set("Detection failed. Local rules can be run independently.")
                messagebox.showerror("Detection failed", str(error))
                return
            if (workspace is not self.case or document_id != self.document_id
                    or text != self.value(self.source)):
                self.status.set("Source changed during detection. Run detection again.")
                return
            reviewed = [span for span in self.spans if span.source in {"manual", "ocr-human-verified"}
                        ] if self.snapshot == text else []
            corrected = {(span.start, span.end) for span in reviewed}
            self.snapshot = text
            self.show_findings(sorted(reviewed + [span for span in spans
                                                 if (span.start, span.end) not in corrected]), text)
            self.status.set(f"{mode}: {len(spans)} findings. Inspect the source for omissions.")

        self.root.after(100, poll)

    def open_scan(self, *, table=False, path=None):
        if not self.workspace_active():
            self.status.set("Create or unlock a workspace before reviewing a scan.")
            return
        if not checkpoint_ready(self.model_dir):
            self.status.set("Install the local NUS checkpoint and OCR models to review a scan.")
            return
        if path is None:
            path = filedialog.askopenfilename(filetypes=[("Scans and images", "*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp")])
        if not path or not self.persist():
            return
        source = Path(path)
        workspace = self.case
        if table:
            self.scan_task(workspace, "Looking for table grids…", lambda: self.read_scan_grids(source),
                           lambda result: self.select_scan_grid(workspace, source, result))
        else:
            self.scan_task(workspace, "Reading the scan with both local OCR engines…",
                           lambda: self.read_scan(source),
                           lambda result: self.review_scan_output(workspace, source, result))

    def scan_task(self, workspace, status, work, ready):
        self.set_processing(True)
        self.status.set(status)
        future = self.worker.submit(work)

        def poll():
            if not future.done():
                self.root.after(100, poll)
                return
            self.set_processing(False)
            if self.case is not workspace:
                return
            try:
                ready(future.result())
            except Exception as error:
                self.status.set("OCR review failed.")
                messagebox.showerror("OCR review failed", str(error), parent=self.root)

        self.root.after(100, poll)

    @staticmethod
    def read_scan_grids(source):
        with source.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        pages = dict(raster_pages(source))
        if not pages:
            raise ValueError("No pages were available for grid review.")
        with source.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                raise ValueError("The source changed while rendering. Import it again.")
        return pages, {page: find_grids(raster, page) for page, raster in pages.items()}, digest

    def select_scan_grid(self, workspace, source, result):
        pages, grids, digest = result
        view = TableGridView(self.root, pages, grids)
        view.window.grab_set()
        self.root.wait_window(view.window)
        if not view.result:
            self.status.set("Table grid review canceled.")
            return
        table = view.result

        def read_table():
            self.ready_scan_engines()
            reviews = self.scan_processor.read_table(pages[table.page], table, self.detector)
            return pages, reviews, digest

        self.scan_task(workspace, "Reading the selected cells with both OCR engines…", read_table,
                       lambda output: self.review_scan_output(workspace, source, output))

    def review_scan_output(self, workspace, source, result):
        pages, reviews, digest = result
        window = tk.Toplevel(self.root)
        window.transient(self.root)
        review = Reviewer(window, pages, reviews)
        window.grab_set()
        self.root.wait_window(window)
        if not review.confirmed:
            self.status.set("OCR review canceled.")
            return
        if self.case is not workspace or not self.persist():
            return
        output = export_review(workspace, source, digest, 250, reviews)
        self.load_document(next(reversed(workspace.documents)))
        document = workspace.documents[self.document_id]
        retained = retained_transcriptions(item.verified for item in reviews if item.action == "keep")
        self.preview_text_export(output, document["name"], source_text=document["text"],
                                 retained=retained,
                                 pdf_review=lambda parent: self.preview_pdf(parent, pages, reviews))
        self.status.set("OCR review saved to the encrypted workspace.")

    def ready_scan_engines(self):
        if self.scan_processor is None:
            self.scan_processor = ScanProcessor(self.model_dir.parent)
        if self.detector is None:
            self.detector = NusDetector(self.model_dir)

    def read_scan(self, source):
        self.ready_scan_engines()
        return self.scan_processor.read(source, 250, self.detector)

    def preview_text_export(self, output, source_name, *, source_text=None, retained=(), pdf_review=None):
        window = tk.Toplevel(self.root)
        window.title("Review document export")
        window.transient(self.root)
        window.geometry("860x650")
        options = ttk.Frame(window, padding=8)
        options.pack(fill="x")
        ttk.Label(options, text="Format").pack(side="left", padx=(0, 8))
        default = "Markdown" if Path(source_name).suffix.lower() in {".md", ".markdown"} else "TXT"
        format_name = tk.StringVar(value=default)
        choices = {"TXT": output, "Markdown": render_export(output, "Markdown", source_name), "Word": output}
        word_rows = None
        try:
            choices["CSV"] = render_export(output, "CSV", source_name, source_text)
        except ValueError:
            pass
        else:
            word_rows = parse_csv(choices["CSV"])
            choices["Word"] = "\n".join("\t".join(row) for row in word_rows)
        selector = ttk.Combobox(options, textvariable=format_name, values=list(choices),
                                state="readonly", width=14)
        selector.pack(side="left")
        summary = ttk.Label(options)
        summary.pack(side="left", padx=12)
        preview = self.text(window, "Exact file contents · review before sharing", 16, readonly=True)
        review = ttk.LabelFrame(window, text="Local structured identifier check", padding=6)
        review.pack(fill="x", padx=8, pady=6)
        findings = ttk.Treeview(review, columns=("category", "decision", "value"),
                               show="headings", selectmode="none", height=4)
        for column, title, width in (("category", "Category", 115), ("decision", "Review", 160),
                                     ("value", "Visible value", 530)):
            findings.heading(column, text=title)
            findings.column(column, width=width, stretch=column == "value")
        scroll = ttk.Scrollbar(review, orient="vertical", command=findings.yview)
        findings.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        findings.pack(fill="x", expand=True)
        ttk.Label(window, text="Checks structured values only. Review names, addresses and context in the preview.",
                  padding=(8, 0, 8, 4)).pack(anchor="w")

        bar = ttk.Frame(window, padding=8)
        bar.pack(fill="x")

        def refresh(_event=None):
            kind = format_name.get()
            rendered = choices[kind]
            self.replace(preview, rendered)
            findings.delete(*findings.get_children())
            try:
                tokens, residuals = inspect_export(rendered, kind, output, retained)
            except ValueError as error:
                summary.configure(text=str(error))
                save_button.state(["disabled"])
                return False
            save_button.state(["!disabled"])
            unreviewed = sum(not item.intentionally_retained for item in residuals)
            summary.configure(text=f"{tokens} tokens · {unreviewed} need review · "
                                   f"{len(residuals) - unreviewed} retained")
            for item in residuals:
                state = "Retained by review" if item.intentionally_retained else "Needs review"
                findings.insert("", "end", values=(item.category, state, item.value))
            return True

        selector.bind("<<ComboboxSelected>>", refresh)

        def save():
            if not refresh():
                return
            kind = format_name.get()
            extension = TEXT_FORMATS[kind]
            path = filedialog.asksaveasfilename(parent=window, defaultextension=extension,
                                               initialfile=Path(source_name).stem + "_reviewed" + extension,
                                               filetypes=[(kind, "*" + extension)])
            if not path:
                return
            if Path(path).suffix.lower() != extension:
                messagebox.showerror("Choose a matching extension", f"Use {extension} for this format.",
                                     parent=window)
                return
            try:
                if kind == "Word":
                    with Path(path).open("xb") as stream:
                        write_word(stream, choices[kind], word_rows)
                else:
                    with Path(path).open("x", encoding="utf-8", newline="") as stream:
                        stream.write(choices[kind])
            except (OSError, UnicodeError) as error:
                messagebox.showerror("Save failed", str(error), parent=window)
                return
            self.status.set(f"Reviewed {kind} export saved.")
            window.destroy()

        save_button = self.button(bar, "Save reviewed file", save)
        if pdf_review is not None:
            self.button(bar, "Review PDF masks", lambda: pdf_review(window))
        self.button(bar, "Close preview", window.destroy)
        refresh()
        window.grab_set()
        self.root.wait_window(window)

    def preview_pdf(self, parent, pages, reviews):
        reviewer = PdfRedactionView(parent, pages, reviews, dpi=250)
        reviewer.window.grab_set()
        self.root.wait_window(reviewer.window)
        if parent.winfo_exists():
            parent.grab_set()

    def compute(self, text, mode):
        if mode == "Rules only":
            return review_spans(text, hybrid(text))
        if self.detector is None:
            self.detector = NusDetector(self.model_dir)
        baseline = self.detector(text)
        return review_spans(text, baseline if mode == "NUS only" else hybrid(text, baseline))

    def compute_document(self, text, mode, name):
        if Path(name).suffix.lower() == ".tsv":
            return detect_table(text, lambda cell: self.compute(cell, mode))
        return self.compute(text, mode)

    def show_findings(self, spans, text):
        self.clear_export()
        self.spans = spans
        self.findings.delete(0, "end")
        self.source.tag_remove("detected", "1.0", "end")
        document = self.case.documents.get(self.document_id, {}) if self.workspace_active() else {}
        entities = {(item["start"], item["end"], item["label"]): item["entity"]
                    for item in document.get("occurrences", []) if document["text"] == text}
        protected = set(selected_indices(spans, self.categories, self.excluded))
        for index, span in enumerate(spans):
            value = text[span.start:span.end]
            action = "protect" if index in protected else "keep"
            entity = entities.get((span.start, span.end, span.label), "")
            confidence = f"{span.confidence:.2f}" if span.confidence is not None else ""
            evidence = "/".join(item for item in (span.source, confidence, span.validation, entity[:8]) if item)
            self.findings.insert("end", f"{action} · {span.label} · {value[:60]!r} · {evidence}")
            start = self.text_index(text, span.start)
            end = self.text_index(text, span.end)
            self.source.tag_add("detected", start, end)

    @staticmethod
    def text_index(text, offset):
        prefix = text[:offset]
        column = prefix.rsplit("\n", 1)[-1]
        return f"{prefix.count(chr(10)) + 1}.{len(column.encode('utf-16-le')) // 2}"

    def mark(self):
        selection = self.source.tag_ranges("sel")
        if not selection:
            self.status.set("Select a span in the source document first.")
            return
        text = self.value(self.source)
        if text != self.snapshot:
            self.snapshot = text
            self.show_findings([], text)
        start, end = (len(self.source.get("1.0", cursor)) for cursor in selection)
        span = Span(start, end, "MANUAL")
        self.excluded.discard(span)
        self.show_findings(sorted(set(self.spans) | {span}), text)
        self.findings.selection_set(self.spans.index(span))

    def valid_review(self):
        if self.snapshot != self.value(self.source):
            self.status.set("Review the current source before changing findings or exporting.")
            return False
        return True

    def toggle_exclusion(self):
        if not self.valid_review():
            return
        self.excluded.symmetric_difference_update(self.spans[index] for index in self.findings.curselection())
        self.show_findings(self.spans, self.snapshot)

    def edit_category(self):
        selected = self.findings.curselection()
        if len(selected) != 1 or not self.valid_review():
            return
        categories = sorted(ALL_CATEGORIES)
        dialog = ChoiceDialog(self.root, "Change finding category", categories)
        if dialog.result is None:
            return
        old = self.spans[selected[0]]
        source = "ocr-human-verified" if old.source == "ocr-human-verified" else "manual"
        new = replace(old, label=categories[dialog.result], source=source,
                      confidence=None, validation=None)
        if old in self.excluded:
            self.excluded.remove(old)
            self.excluded.add(new)
        self.show_findings(sorted((set(self.spans) - {old}) | {new}), self.snapshot)

    def edit_policy(self):
        profiles = (PROFILES | self.case.profiles) if self.workspace_active() else self.session_profiles
        result = PolicyDialog(self.root, self.categories, self.profile_name, profiles).result
        if result is None:
            return
        self.profile_name, self.categories = result
        self.session_profiles[self.profile_name] = set(self.categories)
        if not self.persist():
            return
        if self.snapshot == self.value(self.source):
            self.show_findings(self.spans, self.snapshot)
        self.status.set(f"Profile '{self.profile_name}' applied to cached findings.")

    def link_entity(self):
        selected = self.findings.curselection()
        if len(selected) != 1 or not self.valid_review():
            return
        if not self.workspace_active():
            self.status.set("Open a persistent workspace to link mentions.")
            return
        self.review_current()
        index = selected[0]
        item = self.case.documents[self.document_id]["occurrences"][index]
        choices = self.case.entity_choices(item["label"])
        entries = ["Keep this mention as a separate entity"] + [
            f"{description[:84]} · {key[:8]}" for key, description in choices.items()
        ]
        result = ChoiceDialog(self.root, "Confirm identity link", entries).result
        if result is None:
            return
        if result == 0:
            item["entity"] = new_id()
        else:
            self.case.link(self.document_id, index, list(choices)[result - 1])
        if self.persist():
            self.show_findings(self.spans, self.snapshot)
            self.status.set("Identity decision saved. Regenerate an export to apply it.")

    def transform(self, redact):
        text = self.value(self.source)
        if not self.valid_review():
            return
        self.clear_export()
        indices = selected_indices(self.spans, self.categories, self.excluded)
        try:
            selected = [self.spans[index] for index in indices]
            if self.workspace_active():
                self.review_current()
                self.case.profiles[self.profile_name] = sorted(self.categories)
                self.case.active_profile = self.profile_name
                linked = self.link_person_forms.get() and not redact
                result = self.case.transform(self.document_id, indices, redact=redact,
                                             link_person_forms=linked)
                self.refresh_documents()
            else:
                result = self.case.transform(text, selected, redact=redact)
            self.replace(self.export, result)
            self.export_review = (text, selected)
            self.status.set(f"{len(indices)} findings selected. Review the export for residual identifying information.")
        except (ValueError, OSError, sqlite3.Error) as error:
            messagebox.showerror("Export blocked", str(error))

    def save_export(self):
        text = self.value(self.export)
        if not text:
            return
        source = self.value(self.source)
        indices = selected_indices(self.spans, self.categories, self.excluded)
        selection = [self.spans[index] for index in indices]
        if self.export_review != (source, selection):
            self.status.set("Source or findings changed. Generate a current export first.")
            return
        retained = retained_identifiers(source, self.spans, indices)
        self.preview_text_export(text, self.document_name, source_text=source, retained=retained)

    def export_workspace(self):
        if not self.workspace_active():
            self.status.set("Open a persistent workspace before creating an archive.")
            return
        if not self.persist():
            return
        if not self.case.documents:
            self.status.set("Import a document before creating an archive.")
            return
        view = BatchExportView(self.root, self.case, self.categories, self.link_person_forms.get())
        view.window.grab_set()
        self.root.wait_window(view.window)
        if view.saved:
            self.status.set("Reviewed workspace archive saved.")

    def review_people(self):
        if not self.workspace_active():
            self.status.set("Open a persistent workspace to review people across documents.")
            return
        if not self.persist():
            return
        view = PersonReviewView(self.root, self.case)
        view.window.grab_set()
        self.root.wait_window(view.window)
        if view.changed:
            if self.document_id in self.case.documents:
                self.load_document(self.document_id)
            self.status.set("Person links saved. Regenerate exports to include the updated links.")

    def restore(self):
        self.replace(self.restored, "")
        self.restored_result = None
        text = self.value(self.derived)
        if self.form_source != text:
            self.restore_overrides.clear()
        self.form_source = text
        try:
            if self.derived_format.get() == "CSV":
                restorer = self.case.restore if self.workspace_active() else lambda cell, _: self.case.restore(cell)
                restored, count = restore_csv(text, restorer, self.restore_overrides)
            elif self.workspace_active():
                restored, count = self.case.restore(text, self.restore_overrides)
            else:
                restored, count = self.case.restore(text)
            self.derived.edit_modified(False)
            if text.strip():
                self.replace(self.restored, restored)
                self.restored_result = (text, self.derived_format.get(), restored)
            self.status.set(f"{count} exact references restored. Review attribution and Lithuanian grammar.")
        except ValueError as error:
            self.status.set("Restoration blocked.")
            messagebox.showerror("Restoration blocked", str(error))

    def save_restored_file(self):
        kind = self.derived_format.get()
        if not self.restored_result or self.restored_result[:2] != (
                self.value(self.derived), kind):
            self.status.set("Preview the current restoration before saving.")
            return
        if kind == "Text / Markdown":
            extensions = {".txt", ".md"}
            extension = ".txt"
            filters = [("Text", "*.txt"), ("Markdown", "*.md")]
        else:
            extension = TEXT_FORMATS[kind]
            extensions = {extension}
            filters = [(kind, "*" + extension)]
        path = filedialog.asksaveasfilename(defaultextension=extension, filetypes=filters)
        if not path:
            return
        if Path(path).suffix.lower() not in extensions:
            messagebox.showerror("Choose a matching extension", f"Use {' or '.join(sorted(extensions))}.")
            return
        try:
            if kind == "Word":
                try:
                    rows = table_rows(self.restored_result[2], "restored.tsv")
                except ValueError:
                    rows = None
                with Path(path).open("xb") as stream:
                    write_word(stream, self.restored_result[2], rows)
            else:
                with Path(path).open("x", encoding="utf-8", newline="") as stream:
                    stream.write(self.restored_result[2])
        except (OSError, UnicodeError) as error:
            messagebox.showerror("Save failed", str(error))
            return
        self.status.set("Restored file saved locally. Review it before sharing.")

    def compare_returned_tokens(self):
        if not self.workspace_active():
            self.status.set("Open the original workspace to compare tokens.")
            return
        returned = self.value(self.derived)
        if not returned.strip():
            self.status.set("Import or paste the returned text before comparing tokens.")
            return
        paths = filedialog.askopenfilenames(
            title="Select original pseudonymized exports",
            filetypes=[("Pseudonymized exports", "*.txt *.md *.markdown *.csv *.docx")],
        )
        if not paths:
            return
        try:
            originals = [extract_word(Path(path)) if Path(path).suffix.lower() == ".docx"
                         else Path(path).read_text(encoding="utf-8-sig") for path in paths]
            report = compare_tokens(originals, returned, self.case.references.keys())
        except (OSError, ValueError) as error:
            messagebox.showerror("Could not compare tokens", str(error), parent=self.root)
            return
        messagebox.showinfo("Returned token review", "\n".join((
            f"Expected tokens returned: {report.returned} of {report.expected}",
            f"Missing from the return: {report.missing}",
            f"Workspace tokens outside the selected exports: {report.other_workspace_tokens}",
            f"Unknown tokens: {report.unknown_tokens}",
            f"Possibly damaged token fragments: {report.malformed_mentions}",
            f"Repeated occurrences: {report.repeated_occurrences}",
            "",
            "Check omissions against the requested transformation.",
        )), parent=self.root)

    def choose_person_form(self):
        if not self.workspace_active():
            self.status.set("Open the original workspace to choose a verified form.")
            return
        text = self.value(self.derived)
        try:
            choices = self.case.forms_by_occurrence(text)
        except ValueError as error:
            messagebox.showerror("Restoration blocked", str(error), parent=self.root)
            return
        if not choices:
            self.status.set("No linked alternate person forms are available in this text.")
            return
        if self.form_source != text:
            self.restore_overrides.clear()
        self.form_source = text
        self.derived.edit_modified(False)
        labels = []
        for index, match in enumerate(TOKEN.finditer(text)):
            if index not in choices:
                continue
            left = TOKEN.sub("…", text[max(0, match.start() - 32):match.start()])
            right = TOKEN.sub("…", text[match.end():match.end() + 32])
            value = self.restore_overrides.get(index, choices[index][0])
            labels.append(" ".join(f"{index + 1} · {left} ‹{value}› {right}".split()))
        position = ChoiceDialog(self.root, "Choose an occurrence in the derived text", labels).result
        if position is None:
            return
        index = list(choices)[position]
        forms = choices[index]
        selection = ChoiceDialog(self.root, "Choose an attested person form",
                                 [forms[0] + " (original)", *forms[1:]]).result
        if selection is not None:
            if selection == 0:
                self.restore_overrides.pop(index, None)
            else:
                self.restore_overrides[index] = forms[selection]
            self.restore()

    def import_derived(self):
        paths = filedialog.askopenfilenames(filetypes=[("Derived documents", "*.txt *.md *.markdown *.csv *.docx")])
        if paths:
            try:
                csv_selected = any(Path(path).suffix.lower() == ".csv" for path in paths)
                if csv_selected and len(paths) != 1:
                    raise ValueError("Import one CSV at a time to preserve row and column structure.")
                word_selected = all(Path(path).suffix.lower() == ".docx" for path in paths)
                content = [extract_word(Path(path)) if Path(path).suffix.lower() == ".docx"
                           else Path(path).read_text(encoding="utf-8-sig") for path in paths]
                self.replace(self.derived, "\n\n".join(content))
                self.derived.edit_reset()
                self.derived_format.set("CSV" if csv_selected else "Word" if word_selected else "Text / Markdown")
                self.reset_restoration()
                self.status.set(f"Imported {len(paths)} derived text files.")
            except (OSError, ValueError) as error:
                messagebox.showerror("Derived text import failed", str(error))

    def close(self):
        if (self.workspace_active() or messagebox.askyesno(
                "Close PrivaPII", "Close and discard temporary restoration references?")) and self.persist():
            self.worker.shutdown(wait=False, cancel_futures=True)
            self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=Path("models/nus"))
    args = parser.parse_args()
    root = tk.Tk()
    App(root, args.model)
    root.mainloop()


if __name__ == "__main__":
    main()
