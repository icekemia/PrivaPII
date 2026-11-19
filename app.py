"""PrivaPII local text-review desktop demonstrator."""

import argparse
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from nus import NusDetector
from privapii import Case, Span, hybrid


class App:
    def __init__(self, root, model_dir):
        self.root = root
        self.model_dir = model_dir
        self.detector = None
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.case = Case()
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
        bar = ttk.Frame(review)
        bar.pack(fill="x")
        self.detect_button = self.button(bar, "Detect", self.detect)
        self.button(bar, "Open TXT / Markdown", self.open_source)
        self.button(bar, "Mark selected text", self.mark)
        self.button(bar, "New case", self.new_case)
        self.use_nus = tk.BooleanVar(value=(model_dir / "model.safetensors").is_file())
        ttk.Checkbutton(bar, text="Use local NUS checkpoint", variable=self.use_nus).pack(side="right")
        panes = ttk.Panedwindow(review, orient="horizontal")
        panes.pack(fill="both", expand=True, pady=8)
        left, right = ttk.Frame(panes), ttk.Frame(panes)
        panes.add(left, weight=3)
        panes.add(right, weight=2)
        self.source = self.text(left, "Source document", 10)
        self.source.tag_configure("detected", background="#ffedbb")
        ttk.Label(right, text="Select the findings to transform").pack(anchor="w")
        self.findings = tk.Listbox(right, selectmode="extended", exportselection=False)
        self.findings.pack(fill="both", expand=True)
        controls = ttk.Frame(review)
        controls.pack(fill="x")
        self.button(controls, "Pseudonymize", lambda: self.transform(False))
        self.button(controls, "Redact", lambda: self.transform(True))
        self.button(controls, "Save reviewed export", self.save_export)
        self.export = self.text(review, "Export preview · review before sharing", 8, readonly=True)
        self.derived = self.text(restore, "Paste the derived text for this case", 12)
        self.button(restore, "Preview local restoration", self.restore)
        self.restored = self.text(restore, "Restored preview · contains original values", 12, readonly=True)
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

    def open_source(self):
        path = filedialog.askopenfilename(filetypes=[("Text and Markdown", "*.txt *.md")])
        if path:
            try:
                text = Path(path).read_text(encoding="utf-8-sig")
                self.replace(self.source, text)
                self.snapshot = None
                self.show_findings([], text)
                self.replace(self.export, "")
                self.status.set("Document opened. Detect or mark spans for review.")
            except (OSError, UnicodeError) as error:
                messagebox.showerror("Open failed", str(error))

    def detect(self):
        text = self.value(self.source)
        if not text.strip():
            return
        use_nus = self.use_nus.get()
        self.detect_button.state(["disabled"])
        self.status.set("Detecting on this device…")
        future = self.worker.submit(self.compute, text, use_nus)

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
            if text != self.value(self.source):
                self.status.set("Source changed during detection. Run detection again.")
                return
            self.snapshot = text
            self.show_findings(spans, text)
            self.status.set(f"{len(spans)} findings. Inspect the source for omissions.")

        self.root.after(100, poll)

    def compute(self, text, use_nus):
        if use_nus and self.detector is None:
            self.detector = NusDetector(self.model_dir)
        return hybrid(text, self.detector(text) if use_nus else ())

    def show_findings(self, spans, text):
        self.spans = spans
        self.findings.delete(0, "end")
        self.source.tag_remove("detected", "1.0", "end")
        for span in spans:
            value = text[span.start:span.end]
            self.findings.insert("end", f"{span.label}   {value[:100]!r}")
            start = self.text_index(text, span.start)
            end = self.text_index(text, span.end)
            self.source.tag_add("detected", start, end)
        self.findings.selection_set(0, "end")

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
        previously_selected = {self.spans[index] for index in self.findings.curselection()}
        start, end = (len(self.source.get("1.0", cursor)) for cursor in selection)
        span = Span(start, end, "MANUAL")
        self.show_findings(sorted(set(self.spans) | {span}), text)
        self.findings.selection_clear(0, "end")
        for index, finding in enumerate(self.spans):
            if finding == span or finding in previously_selected:
                self.findings.selection_set(index)

    def transform(self, redact):
        text = self.value(self.source)
        if self.snapshot != text or not self.findings.curselection():
            self.status.set("Review the current document and select findings first.")
            return
        try:
            selected = [self.spans[index] for index in self.findings.curselection()]
            self.replace(self.export, self.case.transform(text, selected, redact=redact))
            self.export_review = (text, selected)
            self.status.set("Review the export for residual identifying information.")
        except ValueError as error:
            messagebox.showerror("Export blocked", str(error))

    def save_export(self):
        text = self.value(self.export)
        if not text:
            return
        selection = [self.spans[index] for index in self.findings.curselection()]
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
            if count:
                self.replace(self.restored, restored)
            self.status.set(f"{count} exact references restored. Review attribution and Lithuanian grammar.")
        except ValueError as error:
            self.status.set("Restoration blocked.")
            messagebox.showerror("Restoration blocked", str(error))

    def new_case(self):
        if messagebox.askyesno("New case", "Discard the current case and its restoration references?"):
            self.case = Case()
            self.snapshot = None
            for widget in (self.source, self.export, self.derived, self.restored):
                self.replace(widget, "")
            self.show_findings([], "")
            self.status.set("New case. Previous references cannot be restored.")

    def close(self):
        if messagebox.askyesno("Close PrivaPII", "Close and discard this session's restoration references?"):
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
