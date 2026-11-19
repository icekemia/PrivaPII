"""PrivaPII local text-review desktop demonstrator."""

import argparse
import sqlite3
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from ingestion import extract
from nus import NusDetector, checkpoint_ready
from policy import ALL_CATEGORIES, CATEGORY_GROUPS, PROFILES, selected_indices
from privapii import Case, Span, hybrid
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
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.case = Case()
        self.document_id = new_id()
        self.document_name = "Pasted text"
        self.document_ids = []
        self.excluded = set()
        self.categories = set(ALL_CATEGORIES)
        self.profile_name = "Standard"
        self.session_profiles = dict(PROFILES)
        self.snapshot = None
        self.export_review = None
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
        self.button(controls, "Redact", lambda: self.transform(True))
        self.button(controls, "Save reviewed export", self.save_export)
        self.export = self.text(review, "Export preview · review before sharing", 8, readonly=True)
        self.derived = self.text(restore, "Paste the derived text for this case", 12)
        restore_actions = ttk.Frame(restore)
        restore_actions.pack(fill="x")
        self.button(restore_actions, "Import derived text", self.import_derived)
        self.button(restore_actions, "Preview local restoration", self.restore)
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
        self.profile_name = workspace.active_profile
        self.categories = set(workspace.profiles.get(self.profile_name, PROFILES["Standard"]))
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
        self.categories = set(ALL_CATEGORIES)
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
        paths = filedialog.askopenfilenames(filetypes=[("Supported documents", "*.txt *.md *.markdown *.pdf")])
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

    def detect(self):
        text = self.value(self.source)
        if not text.strip():
            return
        mode = self.mode.get()
        document_id, workspace = self.document_id, self.case
        self.detect_button.state(["disabled"])
        self.status.set("Detecting on this device…")
        future = self.worker.submit(self.compute, text, mode)

        def poll():
            if not future.done():
                self.root.after(100, poll)
                return
            self.detect_button.state(["!disabled"])
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
            reviewed = [span for span in self.spans if span.source == "manual"] if self.snapshot == text else []
            corrected = {(span.start, span.end) for span in reviewed}
            self.snapshot = text
            self.show_findings(sorted(reviewed + [span for span in spans
                                                 if (span.start, span.end) not in corrected]), text)
            self.status.set(f"{mode}: {len(spans)} findings. Inspect the source for omissions.")

        self.root.after(100, poll)

    def compute(self, text, mode):
        if mode == "Rules only":
            return hybrid(text)
        if self.detector is None:
            self.detector = NusDetector(self.model_dir)
        baseline = self.detector(text)
        return baseline if mode == "NUS only" else hybrid(text, baseline)

    def show_findings(self, spans, text):
        self.clear_export()
        self.spans = spans
        self.findings.delete(0, "end")
        self.source.tag_remove("detected", "1.0", "end")
        document = self.case.documents.get(self.document_id, {}) if self.workspace_active() else {}
        entities = {(item["start"], item["end"], item["label"]): item["entity"]
                    for item in document.get("occurrences", []) if document["text"] == text}
        for span in spans:
            value = text[span.start:span.end]
            action = "keep" if span in self.excluded or span.label not in self.categories else "protect"
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
        new = replace(old, label=categories[dialog.result], source="manual",
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
                result = self.case.transform(self.document_id, indices, redact=redact)
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
        if not messagebox.askyesno("Confirm export", "Have you reviewed this exact export for residual personal data?"):
            return
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text", "*.txt")])
        if path:
            try:
                Path(path).write_text(text, encoding="utf-8")
                self.status.set("Reviewed export saved.")
            except (OSError, UnicodeError) as error:
                messagebox.showerror("Save failed", str(error))

    def restore(self):
        self.replace(self.restored, "")
        try:
            restored, count = self.case.restore(self.value(self.derived))
            self.derived.edit_modified(False)
            if count:
                self.replace(self.restored, restored)
            self.status.set(f"{count} exact references restored. Review attribution and Lithuanian grammar.")
        except ValueError as error:
            self.status.set("Restoration blocked.")
            messagebox.showerror("Restoration blocked", str(error))

    def import_derived(self):
        paths = filedialog.askopenfilenames(filetypes=[("Text and Markdown", "*.txt *.md *.markdown")])
        if paths:
            try:
                content = [Path(path).read_text(encoding="utf-8-sig") for path in paths]
                self.replace(self.derived, "\n\n".join(content))
                self.derived.edit_reset()
                self.replace(self.restored, "")
                self.status.set(f"Imported {len(paths)} derived text files.")
            except (OSError, UnicodeError) as error:
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
