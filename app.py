"""PrivaPII local text-review desktop demonstrator."""

import argparse
import sqlite3
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from export_formats import TEXT_FORMATS, render_export, restore_csv
from ingestion import extract
from nus import NusDetector, checkpoint_ready
from ocr_review import Reviewer, ScanProcessor, export_review
from pdf_redaction_view import PdfRedactionView
from pdf_tables import extract_pdf_tables
from policy import ALL_CATEGORIES, CATEGORY_GROUPS, PROFILES, selected_indices
from privapii import TOKEN, Case, Span, hybrid, review_spans
from tabular import detect_table
from vault import Workspace, new_id


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
        values = [f"Page {table.page} · Table {table.number} · "
                  f"{len(table.rows)} rows × {len(table.rows[0])} columns" for table in self.tables]
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
        self.table_button = self.button(bar, "PDF table", self.open_pdf_table)
        self.scan_button = self.button(bar, "Review scan", self.open_scan)
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
                                     state="readonly", values=("Text / Markdown", "CSV"), width=16)
        restore_format.pack(side="left", padx=4)
        restore_format.bind("<<ComboboxSelected>>", lambda _: self.reset_restoration())
        self.button(restore_actions, "Import derived text", self.import_derived)
        self.button(restore_actions, "Preview local restoration", self.restore)
        self.button(restore_actions, "Choose verified person form", self.choose_person_form)
        self.button(restore_actions, "Save restored CSV", self.save_restored_csv)
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
        paths = filedialog.askopenfilenames(filetypes=[("Supported documents", "*.txt *.tsv *.md *.markdown *.pdf")])
        if not paths or not self.persist():
            return
        imported = sum_empty = 0
        for filename in paths:
            try:
                path = Path(filename)
                text, empty = extract(path)
                if not text.strip():
                    raise ValueError("The document contains no text.")
                self.load_document(new_id(), path.name, text)
                if not self.persist():
                    return
                imported += 1
                sum_empty += empty
                if not self.workspace_active():
                    break
            except (OSError, ValueError) as error:
                messagebox.showerror("Import failed", str(error))
        if imported:
            self.status.set(f"{imported} imported. Detect and review extracted text. {sum_empty} PDF pages had no text.")

    def set_processing(self, active):
        for button in (self.detect_button, self.scan_button, self.table_button):
            button.state(["disabled" if active else "!disabled"])

    def open_pdf_table(self):
        path = filedialog.askopenfilename(filetypes=[("Digital PDF", "*.pdf")])
        if not path or not self.persist():
            return
        workspace = self.case
        self.set_processing(True)
        self.status.set("Looking for complete table grids in the PDF…")
        future = self.worker.submit(extract_pdf_tables, Path(path))

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
                    self.status.set("No complete native-text table grids found in this PDF.")
                    return
                table = TableDialog(self.root, tables).result
                if table is None or not self.persist():
                    return
                name = f"{Path(path).stem}_p{table.page}_table{table.number}.tsv"
                self.load_document(new_id(), name, table.tsv())
                if self.persist():
                    self.status.set("Table imported. Detect, review and choose CSV in the export preview.")
            except Exception as error:
                self.status.set("PDF table import failed.")
                messagebox.showerror("PDF table import failed", str(error), parent=self.root)

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

    def open_scan(self):
        if not self.workspace_active():
            self.status.set("Create or unlock a workspace before reviewing a scan.")
            return
        if not checkpoint_ready(self.model_dir):
            self.status.set("Install the local NUS checkpoint and OCR models to review a scan.")
            return
        path = filedialog.askopenfilename(filetypes=[("Scans and images", "*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp")])
        if not path or not self.persist():
            return
        source = Path(path)
        workspace = self.case
        self.set_processing(True)
        self.status.set("Reading the scan with both local OCR engines…")
        future = self.worker.submit(self.read_scan, source)

        def poll():
            if not future.done():
                self.root.after(100, poll)
                return
            self.set_processing(False)
            if self.case is not workspace:
                return
            try:
                pages, reviews, digest = future.result()
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
                self.preview_text_export(output, source.name, source_text=document["text"],
                                         pdf_review=lambda parent: self.preview_pdf(parent, pages, reviews))
                self.status.set("OCR review saved to the encrypted workspace.")
            except Exception as error:
                self.status.set("OCR review failed.")
                messagebox.showerror("OCR review failed", str(error), parent=self.root)

        self.root.after(100, poll)

    def read_scan(self, source):
        if self.scan_processor is None:
            self.scan_processor = ScanProcessor(self.model_dir.parent)
        if self.detector is None:
            self.detector = NusDetector(self.model_dir)
        return self.scan_processor.read(source, 250, self.detector)

    def preview_text_export(self, output, source_name, *, source_text=None, pdf_review=None):
        window = tk.Toplevel(self.root)
        window.title("Review document export")
        window.transient(self.root)
        window.geometry("820x540")
        options = ttk.Frame(window, padding=8)
        options.pack(fill="x")
        ttk.Label(options, text="Format").pack(side="left", padx=(0, 8))
        default = "Markdown" if Path(source_name).suffix.lower() in {".md", ".markdown"} else "TXT"
        format_name = tk.StringVar(value=default)
        choices = {"TXT": output, "Markdown": render_export(output, "Markdown", source_name)}
        try:
            choices["CSV"] = render_export(output, "CSV", source_name, source_text)
        except ValueError:
            pass
        selector = ttk.Combobox(options, textvariable=format_name, values=list(choices),
                                state="readonly", width=14)
        selector.pack(side="left")
        preview = self.text(window, "Exact file contents · review before sharing", 16, readonly=True)

        def refresh(_event=None):
            self.replace(preview, choices[format_name.get()])

        selector.bind("<<ComboboxSelected>>", refresh)
        refresh()
        bar = ttk.Frame(window, padding=8)
        bar.pack(fill="x")

        def save():
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
                with Path(path).open("x", encoding="utf-8", newline="") as stream:
                    stream.write(self.value(preview))
            except (OSError, UnicodeError) as error:
                messagebox.showerror("Save failed", str(error), parent=window)
                return
            self.status.set(f"Reviewed {kind} export saved.")
            window.destroy()

        self.button(bar, "Save reviewed file", save)
        if pdf_review is not None:
            self.button(bar, "Review PDF masks", lambda: pdf_review(window))
        self.button(bar, "Close preview", window.destroy)
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
        selection = [self.spans[index] for index in selected_indices(self.spans, self.categories, self.excluded)]
        if self.export_review != (self.value(self.source), selection):
            self.status.set("Source or findings changed. Generate a current export first.")
            return
        self.preview_text_export(text, self.document_name, source_text=self.value(self.source))

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
            if count or self.derived_format.get() == "CSV":
                self.replace(self.restored, restored)
                self.restored_result = (text, self.derived_format.get(), restored)
            self.status.set(f"{count} exact references restored. Review attribution and Lithuanian grammar.")
        except ValueError as error:
            self.status.set("Restoration blocked.")
            messagebox.showerror("Restoration blocked", str(error))

    def save_restored_csv(self):
        if not self.restored_result or self.restored_result[:2] != (self.value(self.derived), "CSV") or self.derived_format.get() != "CSV":
            self.status.set("Preview the current CSV restoration before saving.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        if Path(path).suffix.lower() != ".csv":
            messagebox.showerror("Choose a matching extension", "Use .csv for the restored table.")
            return
        try:
            with Path(path).open("x", encoding="utf-8", newline="") as stream:
                stream.write(self.restored_result[2])
        except OSError as error:
            messagebox.showerror("Save failed", str(error))
            return
        self.status.set("Restored CSV saved locally. It contains original values.")

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
        paths = filedialog.askopenfilenames(filetypes=[("Derived documents", "*.txt *.md *.markdown *.csv")])
        if paths:
            try:
                csv_selected = any(Path(path).suffix.lower() == ".csv" for path in paths)
                if csv_selected and len(paths) != 1:
                    raise ValueError("Import one CSV at a time to preserve row and column structure.")
                content = [Path(path).read_text(encoding="utf-8-sig") for path in paths]
                self.replace(self.derived, "\n\n".join(content))
                self.derived.edit_reset()
                self.derived_format.set("CSV" if csv_selected else "Text / Markdown")
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
