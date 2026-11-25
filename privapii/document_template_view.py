"""Configure and validate form rules, then check folders before export."""

import sqlite3
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .batch_export_view import BatchExportView
from .document_templates import Field, Template, check_folders, read_form, save_template, stage_documents
from .policy import ALL_CATEGORIES


class DocumentTemplateView:
    def __init__(self, parent, workspace, detector):
        self.window = tk.Toplevel(parent)
        self.window.title("Document models")
        self.window.geometry("920x700")
        self.window.transient(parent)
        self.workspace = workspace
        self.detector = detector
        self.sample = self.heading = ""
        self.sample_path = None
        self.fields = []
        self.validated = None
        self.version = 1
        self.folders = []
        tabs = ttk.Notebook(self.window)
        tabs.pack(fill="both", expand=True, padx=12, pady=12)
        setup = ttk.Frame(tabs, padding=12)
        batch = ttk.Frame(tabs, padding=12)
        tabs.add(setup, text="Set up a document model")
        tabs.add(batch, text="Process client folders")

        actions = ttk.Frame(setup)
        actions.pack(fill="x")
        for caption, action in (
            ("Open example PDF", self.open_example), ("Edit approved model", self.load_model),
            ("Use selection as heading", self.set_heading), ("Add selected label", self.add_field),
            ("Remove rule", self.remove_field),
        ):
            ttk.Button(actions, text=caption, command=action).pack(side="left", padx=(0, 6))
        ttk.Label(setup, text="Select a printed heading unique to this form version, then add labels "
                  "such as “Gimimo data” from lines with one label and one value.",
                  wraplength=800).pack(anchor="w", pady=6)
        self.source = self.text_area(setup, height=16, expand=True)
        self.rules = tk.Listbox(setup, height=5, exportselection=False)
        self.rules.pack(fill="x", pady=6)
        self.setup_status = tk.StringVar(value="Open a PDF with selectable text to start.")
        ttk.Label(setup, textvariable=self.setup_status, wraplength=800).pack(anchor="w")
        footer = ttk.Frame(setup)
        footer.pack(fill="x", pady=6)
        ttk.Button(footer, text="Test on another PDF", command=self.test).pack(side="left")
        self.approve = ttk.Button(footer, text="Approve model", command=self.approve_model, state="disabled")
        self.approve.pack(side="right")

        ttk.Label(batch, text="Select a parent folder containing one folder per client. Each client "
                  "folder must contain one PDF for each selected model.", wraplength=780).pack(anchor="w")
        ttk.Button(batch, text="Choose parent folder", command=self.choose_folders).pack(anchor="w", pady=6)
        self.models = tk.Listbox(batch, height=6, selectmode="extended", exportselection=False)
        self.models.pack(fill="x")
        self.partial = tk.BooleanVar()
        ttk.Checkbutton(batch, text="Include checked documents from incomplete client folders",
                        variable=self.partial).pack(anchor="w", pady=6)
        self.group_export = tk.BooleanVar()
        ttk.Checkbutton(batch, text="Keep each client's files together under a temporary ID",
                        variable=self.group_export).pack(anchor="w", pady=6)
        self.check_button = ttk.Button(batch, text="Check client folders", command=self.run_check)
        self.check_button.pack(anchor="w")
        self.batch_status = tk.StringVar(value="Choose a parent folder and select the required models.")
        ttk.Label(batch, textvariable=self.batch_status, wraplength=800).pack(anchor="w", pady=6)
        self.report = self.text_area(batch, height=14, expand=True)
        self.update_models()

    @staticmethod
    def text_area(parent, *, height, expand):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=expand)
        area = tk.Text(frame, wrap="none", height=height, state="disabled")
        scroll = ttk.Scrollbar(frame, command=area.yview)
        area.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        area.pack(side="left", fill="both", expand=True)
        return area

    @staticmethod
    def display(area, value):
        area.configure(state="normal")
        area.delete("1.0", "end")
        area.insert("1.0", value)
        area.configure(state="disabled")

    def pick_pdf(self):
        selected = filedialog.askopenfilename(parent=self.window, filetypes=[("PDF", "*.pdf")])
        return Path(selected) if selected else None

    def open_example(self):
        path = self.pick_pdf()
        if not path:
            return
        try:
            content = read_form(path)
        except (OSError, ValueError) as error:
            self.error(error)
            return
        self.sample, self.sample_path = content, path
        self.display(self.source, content)
        self.invalidate()

    def selection(self):
        try:
            return self.source.get("sel.first", "sel.last").strip()
        except tk.TclError:
            return ""

    def set_heading(self):
        heading = self.selection()
        if not heading or "\n" in heading:
            self.error("Select one complete heading in the PDF text.")
            return
        self.heading = heading
        self.invalidate()

    def add_field(self):
        label = self.selection()
        if not label or "\n" in label or ":" in label:
            self.error("Select the printed field label, without its colon or value.")
            return
        dialog = FieldDialog(self.window, label)
        if dialog.result:
            self.fields.append(dialog.result)
            self.invalidate()

    def remove_field(self):
        selected = self.rules.curselection()
        if selected:
            del self.fields[selected[0]]
            self.invalidate()

    def invalidate(self):
        self.validated = None
        self.approve.state(["disabled"])
        self.rules.delete(0, "end")
        for field in self.fields:
            action = "Keep visible" if field.keep else "Protect"
            self.rules.insert("end", f"{action}  ·  {field.label}  ·  {field.category}"
                              + ("  ·  may be blank" if field.allow_empty else ""))
        self.setup_status.set(f"Heading: {self.heading or 'select a printed heading'}")

    def update_models(self):
        self.approved = [Template.load(versions[-1]) for versions in self.workspace.document_templates.values()]
        self.models.delete(0, "end")
        for model in self.approved:
            self.models.insert("end", f"{model.name}  ·  version {model.version}")
        self.models.selection_set(0, "end")

    def load_model(self):
        if not self.approved:
            self.error("No approved models yet. Open an example PDF to create one.")
            return
        choice = ModelDialog(self.window, self.approved).result
        if choice is None:
            return
        model = self.approved[choice]
        self.heading, self.fields = model.heading, list(model.fields)
        self.invalidate()
        self.setup_status.set(f"Editing {model.name}. Use the same model name when approving.")

    def test(self):
        self.invalidate()
        path = self.pick_pdf()
        if not path:
            return
        try:
            template = Template("Draft", self.heading, tuple(self.fields))
            if self.sample_path is None or path.samefile(self.sample_path):
                raise ValueError("Open a configuration example and test on a different PDF.")
            content = read_form(path)
            if content == self.sample:
                raise ValueError("Choose a test PDF with different extracted content.")
            template.apply(self.sample, detector=lambda _: ())
            template.apply(content, detector=lambda _: ())
        except (OSError, ValueError) as error:
            self.error(error)
            return
        preview = tk.Toplevel(self.window)
        preview.title("Verify matched fields")
        preview.geometry("730x490")
        preview.transient(self.window)
        area = self.text_area(preview, height=18, expand=True)
        self.display(area, content)
        for field in template.fields:
            start, end = field.locations(content)[0]
            tag = "keep" if field.keep else "protect"
            area.tag_add(tag, f"1.0 + {start} chars", f"1.0 + {end} chars")
        area.tag_configure("keep", background="#d8efdf")
        area.tag_configure("protect", background="#ffe2a3")
        ttk.Label(preview, text="Amber = protect  ·  Green = keep visible. Check these fields against the PDF.").pack()
        confirmed = tk.BooleanVar()
        ttk.Checkbutton(preview, text="The matched fields and actions are correct", variable=confirmed).pack(pady=4)
        ttk.Button(preview, text="Done", command=preview.destroy).pack(pady=4)
        preview.grab_set()
        self.window.wait_window(preview)
        self.window.grab_set()
        if confirmed.get():
            self.validated = template
            self.approve.state(["!disabled"])
            self.setup_status.set("Test confirmed. You can approve this model for batch use.")

    def approve_model(self):
        name = simpledialog.askstring("Approve model", "Model name", parent=self.window)
        if not name or not name.strip() or self.validated is None:
            return
        name = name.strip()
        history = self.workspace.document_templates.get(name, [])
        if history and not messagebox.askyesno("Approve new version",
                                               f"Use this version for future checks of {name}?",
                                               parent=self.window):
            return
        draft = self.validated
        try:
            save_template(self.workspace, Template(name, draft.heading, draft.fields, len(history) + 1))
        except (ValueError, sqlite3.Error, OSError) as error:
            self.error(error)
            return
        self.invalidate()
        self.update_models()
        self.setup_status.set(f"{name} version {len(history) + 1} approved.")

    def choose_folders(self):
        path = filedialog.askdirectory(parent=self.window)
        if path:
            try:
                self.folders = sorted(item for item in Path(path).iterdir() if item.is_dir())
            except OSError as error:
                self.error(error)
                return
            self.batch_status.set(f"{len(self.folders)} client folders selected.")
            self.display(self.report, "")

    def run_check(self):
        templates = [self.approved[index] for index in self.models.curselection()]
        if not self.folders or not templates:
            self.error("Choose client folders and select at least one required model.")
            return
        self.check_button.state(["disabled"])
        self.batch_status.set("Checking document types and required fields…")
        group_export = self.group_export.get()
        folder_count = len(self.folders)
        revision = self.workspace.revision
        worker = ThreadPoolExecutor(max_workers=1)
        check = worker.submit(check_folders, tuple(self.folders), templates,
                              allow_incomplete=self.partial.get(), detector=self.detector)
        worker.shutdown(wait=False)
        self.window.protocol("WM_DELETE_WINDOW", lambda: None)

        def poll():
            if not check.done():
                self.window.after(100, poll)
                return
            self.check_button.state(["!disabled"])
            self.window.protocol("WM_DELETE_WINDOW", self.window.destroy)
            try:
                ready, issues = check.result()
                if self.workspace.revision != revision:
                    raise ValueError("The workspace changed during the check. Check the folders again.")
                self.review_batch(ready, issues, folder_count, group_export)
            except Exception as error:
                self.batch_status.set("Batch check did not finish. No archive was saved.")
                self.error(error)

        self.window.after(100, poll)

    def review_batch(self, ready, issues, folder_count, group_export):
        count = sum(map(len, ready))
        self.display(self.report, "\n\n".join(issues) if issues else "All selected folders passed the model checks.")
        self.batch_status.set(f"{count} documents ready for review · {len(ready)} of {folder_count} "
                              f"client folders included · {len(issues)} issues")
        if not ready or not messagebox.askyesno(
            "Open export previews",
            f"Review {count} checked documents for export? "
            "Files with unresolved checks are excluded.", parent=self.window,
        ):
            return
        group_ids = [index for index, group in enumerate(ready, 1) for _ in group]
        keys = stage_documents(self.workspace, [item for group in ready for item in group])
        fields = dict(zip(keys, (item[-1] for group in ready for item in group)))
        revision = self.workspace.revision
        try:
            groups = dict(zip(keys, group_ids)) if group_export else None
            view = BatchExportView(self.window, self.workspace, ALL_CATEGORIES, False,
                                   document_ids=keys, groups=groups, fields=fields)
            view.window.grab_set()
            self.window.wait_window(view.window)
            if view.saved:
                self.batch_status.set(f"Archive saved with {count} reviewed documents.")
        finally:
            if self.workspace.revision == revision:
                for key in keys:
                    self.workspace.documents.pop(key, None)
            self.window.grab_set()

    def error(self, error):
        messagebox.showerror("Document models", str(error), parent=self.window)


class FieldDialog(simpledialog.Dialog):
    def __init__(self, parent, label):
        self.label = label
        super().__init__(parent, title="Add a field rule")

    def body(self, frame):
        ttk.Label(frame, text=self.label).pack(anchor="w")
        self.action = tk.StringVar(value="Protect")
        ttk.Combobox(frame, state="readonly", textvariable=self.action,
                     values=("Protect", "Keep visible")).pack(fill="x", pady=4)
        self.category = tk.StringVar(value="MANUAL")
        common = {"Name": "PER", "Birth date": "DOB", "Document date": "DATE",
                  "Customer or reference code": "ID_MISC", "Personal identifier": "ID_PER",
                  "Account number (IBAN)": "IBAN", "Amount": "VALUE", "Other": "MANUAL"}
        self.categories = {**common, **{code: code for code in sorted(ALL_CATEGORIES - set(common.values()))}}
        self.category.set("Other")
        ttk.Label(frame, text="What kind of value is this?").pack(anchor="w")
        ttk.Combobox(frame, state="readonly", textvariable=self.category,
                     values=list(self.categories)).pack(fill="x", pady=4)
        self.empty = tk.BooleanVar()
        ttk.Checkbutton(frame, text="Allow a visibly blank field", variable=self.empty).pack(anchor="w")

    def apply(self):
        self.result = Field(self.label, self.categories[self.category.get()],
                            self.action.get() == "Keep visible", self.empty.get())


class ModelDialog(simpledialog.Dialog):
    def __init__(self, parent, models):
        self.models = models
        super().__init__(parent, title="Edit approved model")

    def body(self, frame):
        self.choice = ttk.Combobox(frame, state="readonly", width=45,
                                   values=[model.name for model in self.models])
        self.choice.current(0)
        self.choice.pack(padx=8, pady=8)
        return self.choice

    def apply(self):
        self.result = self.choice.current()
