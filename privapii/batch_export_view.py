"""Review selected workspace files before saving an export archive."""

import sqlite3
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .batch_export import BATCH_FORMATS, Batch


class BatchExportView:
    def __init__(self, parent, workspace, categories, link_person_forms):
        self.window = tk.Toplevel(parent)
        self.window.title("Review workspace archive")
        self.window.geometry("980x680")
        self.window.transient(parent)
        self.workspace = workspace
        self.categories = set(categories)
        self.link_person_forms = link_person_forms
        self.keys = list(workspace.documents)
        self.batch = None
        self.saved = False

        options = ttk.Frame(self.window, padding=8)
        options.pack(fill="x")
        ttk.Label(options, text="Archive format").pack(side="left")
        self.format_name = tk.StringVar(value="Markdown")
        selector = ttk.Combobox(options, textvariable=self.format_name, values=BATCH_FORMATS,
                                state="readonly", width=13)
        selector.pack(side="left", padx=8)
        selector.bind("<<ComboboxSelected>>", self.invalidate)
        ttk.Label(options, text="Linked person IDs on" if link_person_forms else "Linked person IDs off").pack(side="left")

        panes = ttk.Panedwindow(self.window, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=8, pady=(0, 6))
        left, right = ttk.Frame(panes, padding=6), ttk.Frame(panes, padding=6)
        panes.add(left, weight=1)
        panes.add(right, weight=3)
        ttk.Label(left, text="Select saved documents").pack(anchor="w")
        listing = ttk.Frame(left)
        listing.pack(fill="both", expand=True, pady=4)
        self.documents = tk.Listbox(listing, selectmode="extended", exportselection=False, width=30)
        document_scroll = ttk.Scrollbar(listing, orient="vertical", command=self.documents.yview)
        self.documents.configure(yscrollcommand=document_scroll.set)
        document_scroll.pack(side="right", fill="y")
        self.documents.pack(side="left", fill="both", expand=True)
        for key in self.keys:
            name = workspace.documents[key]["name"]
            self.documents.insert("end", f"{name} · {key[:8]}")
        self.documents.bind("<<ListboxSelect>>", self.invalidate)
        ttk.Button(left, text="Select all", command=self.select_all).pack(fill="x", pady=2)
        ttk.Button(left, text="Prepare previews", command=self.prepare).pack(fill="x", pady=2)

        self.files = ttk.Combobox(right, state="readonly")
        self.files.pack(fill="x")
        self.files.bind("<<ComboboxSelected>>", self.show_item)
        self.status = tk.StringVar(value="Select documents, then prepare their exact export previews.")
        ttk.Label(right, textvariable=self.status, wraplength=650).pack(anchor="w", pady=6)
        frame = ttk.Frame(right)
        frame.pack(fill="both", expand=True)
        self.preview = tk.Text(frame, wrap="word", state="disabled", width=40)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.preview.yview)
        self.preview.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.preview.pack(fill="both", expand=True)
        self.confirmed = tk.BooleanVar(value=False)
        self.confirm_button = ttk.Checkbutton(right, text="I reviewed this file for information still visible",
                                              variable=self.confirmed, command=self.approve)
        self.confirm_button.pack(anchor="w", pady=6)

        bottom = ttk.Frame(self.window, padding=8)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Close", command=self.window.destroy).pack(side="right")
        self.save_button = ttk.Button(bottom, text="Save reviewed ZIP", command=self.save)
        self.save_button.pack(side="right", padx=8)
        self.invalidate()

    def replace_text(self, value):
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", value)
        self.preview.configure(state="disabled")

    def invalidate(self, _event=None):
        self.batch = None
        self.files.configure(values=())
        self.files.set("")
        self.confirmed.set(False)
        self.confirm_button.state(["disabled"])
        self.save_button.state(["disabled"])
        self.replace_text("")
        self.status.set("Prepare previews for the selected documents.")

    def select_all(self):
        self.documents.selection_set(0, "end")
        self.invalidate()

    def prepare(self):
        keys = [self.keys[index] for index in self.documents.curselection()]
        if not keys:
            self.status.set("Select at least one document.")
            return
        self.invalidate()
        try:
            self.batch = Batch(self.workspace, keys, self.categories, self.format_name.get(),
                               link_person_forms=self.link_person_forms)
        except ValueError as error:
            messagebox.showerror("Could not prepare archive", str(error), parent=self.window)
            return
        self.files.configure(values=[f"{item.archive_name} · {item.source_name}" for item in self.batch.items])
        self.files.current(0)
        self.confirm_button.state(["!disabled"])
        self.show_item()

    def show_item(self, _event=None):
        index = self.files.current()
        if self.batch is None or index < 0:
            return
        item = self.batch.items[index]
        self.replace_text(item.text)
        self.confirmed.set(index in self.batch.approved)
        unreviewed = [entry.category for entry in item.residuals if not entry.intentionally_retained]
        alerts = ", ".join(sorted(set(unreviewed)))
        details = f" · inspect: {alerts}" if alerts else ""
        self.status.set(f"{len(self.batch.approved)}/{len(self.batch.items)} approved · "
                        f"{item.token_count} tokens · {len(unreviewed)} visible identifiers need review{details}")

    def approve(self):
        self.batch.approve(self.files.current(), self.confirmed.get())
        self.show_item()
        complete = len(self.batch.approved) == len(self.batch.items)
        self.save_button.state(["!disabled" if complete else "disabled"])

    def save(self):
        if not self.batch or len(self.batch.approved) != len(self.batch.items):
            return
        path = filedialog.asksaveasfilename(parent=self.window, defaultextension=".zip",
                                           initialfile="privapii-export.zip", filetypes=[("ZIP", "*.zip")])
        if not path:
            return
        try:
            self.batch.write(Path(path))
        except (OSError, ValueError, sqlite3.Error) as error:
            messagebox.showerror("Archive not saved", str(error), parent=self.window)
            return
        self.saved = True
        self.window.destroy()
