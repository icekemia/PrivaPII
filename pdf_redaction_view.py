"""Page-by-page desktop review of raster PDF redactions."""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from pdf_redaction import clamp_box, masked_page, review_masks, write_redacted_pdf


class PdfRedactionView:
    def __init__(self, parent, pages, reviews, dpi):
        self.window = tk.Toplevel(parent)
        self.window.title("Review irreversible PDF redaction")
        self.window.geometry("1000x800")
        self.window.transient(parent)
        self.pages, self.dpi = pages, dpi
        self.numbers = sorted(pages)
        self.index = 0
        self.automatic = review_masks(pages, reviews)
        self.manual = {number: [] for number in pages}
        self.checked = set()
        self.zoom = False
        self.origin = None
        self.outline = None
        header = ttk.Frame(self.window, padding=8)
        header.pack(fill="x")
        self.status = ttk.Label(header)
        self.status.pack(anchor="w")
        ttk.Label(header, text="Review all visible content. Drag to cover regions missed by OCR. "
                  "PDF masks are permanent and apply only to the PDF.").pack(anchor="w")
        controls = ttk.Frame(self.window, padding=(8, 0, 8, 8))
        controls.pack(side="bottom", fill="x")
        for title, action in (
            ("Previous", lambda: self.move(-1)), ("Next", lambda: self.move(1)),
            ("Fit / full size", self.toggle_zoom), ("Undo manual mask", self.undo),
            ("Confirm page reviewed", self.confirm),
        ):
            ttk.Button(controls, text=title, command=action).pack(side="left", padx=(0, 5))
        self.save_button = ttk.Button(controls, text="Save new redacted PDF", command=self.save)
        self.save_button.pack(side="right")
        frame = ttk.Frame(self.window)
        frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.canvas = tk.Canvas(frame, background="#e0e0e0", highlightthickness=0)
        vertical = ttk.Scrollbar(frame, orient="vertical", command=self.canvas.yview)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.canvas.bind("<ButtonPress-1>", self.begin)
        self.canvas.bind("<B1-Motion>", self.drag)
        self.canvas.bind("<ButtonRelease-1>", self.end)
        self.window.protocol("WM_DELETE_WINDOW", self.window.destroy)
        self.show(reset_scroll=True)

    @property
    def number(self):
        return self.numbers[self.index]

    def show(self, reset_scroll=False):
        from PIL import Image, ImageTk

        number = self.number
        raster = masked_page(self.pages[number], self.automatic[number] + self.manual[number])
        width, height = raster.size
        if not self.zoom:
            raster.thumbnail((920, 630), Image.Resampling.LANCZOS)
        self.scale = raster.width / width, raster.height / height
        self.photo = ImageTk.PhotoImage(raster, master=self.window)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.canvas.configure(scrollregion=(0, 0, raster.width, raster.height))
        if reset_scroll:
            self.canvas.xview_moveto(0)
            self.canvas.yview_moveto(0)
        self.origin = self.outline = None
        self.update_status()

    def update_status(self):
        indicator = "reviewed" if self.number in self.checked else "review required"
        self.status.configure(text=f"Page {self.index + 1} of {len(self.numbers)} · {indicator} · "
                                   f"{len(self.checked)} pages confirmed")
        self.save_button.state(["!disabled" if len(self.checked) == len(self.numbers) else "disabled"])

    def move(self, step):
        self.index = max(0, min(self.index + step, len(self.numbers) - 1))
        self.show(reset_scroll=True)

    def toggle_zoom(self):
        self.zoom = not self.zoom
        self.show(reset_scroll=True)

    def pixel(self, event):
        return self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

    def begin(self, event):
        self.origin = self.pixel(event)
        self.outline = self.canvas.create_rectangle(*self.origin, *self.origin, outline="#d5462f", width=2)

    def drag(self, event):
        if self.origin is not None:
            self.canvas.coords(self.outline, *self.origin, *self.pixel(event))

    def end(self, event):
        from math import ceil, floor

        if self.origin is None:
            return
        sx, sy = self.scale
        x, y = self.pixel(event)
        x0, x1 = sorted((self.origin[0] / sx, x / sx))
        y0, y1 = sorted((self.origin[1] / sy, y / sy))
        if x1 - x0 >= 2 and y1 - y0 >= 2:
            try:
                box = clamp_box((floor(x0), floor(y0), ceil(x1), ceil(y1)),
                                self.pages[self.number].size)
            except ValueError:
                pass
            else:
                self.manual[self.number].append(box)
                self.checked.discard(self.number)
        self.show()

    def undo(self):
        if self.manual[self.number]:
            self.manual[self.number].pop()
            self.checked.discard(self.number)
            self.show()

    def confirm(self):
        self.checked.add(self.number)
        self.update_status()

    def save(self):
        if len(self.checked) != len(self.numbers):
            return
        filename = filedialog.asksaveasfilename(parent=self.window, defaultextension=".pdf",
                                               filetypes=[("PDF", "*.pdf")])
        if not filename:
            return
        target = Path(filename)
        masks = {page: self.automatic[page] + self.manual[page] for page in self.numbers}
        created = False
        try:
            with target.open("xb") as stream:
                created = True
                write_redacted_pdf(stream, self.pages, masks, dpi=self.dpi)
        except (OSError, ValueError) as error:
            if created:
                target.unlink(missing_ok=True)
            messagebox.showerror("PDF export failed", str(error), parent=self.window)
            return
        messagebox.showinfo("PDF saved", "Saved a new image-only PDF with permanent pixel masks.",
                            parent=self.window)
