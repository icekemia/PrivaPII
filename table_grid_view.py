"""Review detected grid boundaries or draw a rectangular grid over a scan."""

import tkinter as tk
from bisect import bisect_right
from tkinter import ttk

from raster_tables import RasterTable


class TableGridView:
    def __init__(self, parent, pages, grids):
        self.window = tk.Toplevel(parent)
        self.window.title("Choose a grid for table OCR")
        self.window.transient(parent)
        self.window.geometry("1000x800")
        self.pages = pages
        self.grids = grids
        self.index = 0
        self.numbers = sorted(pages)
        self.guides = {number: ([], []) for number in pages}
        self.history = {number: [] for number in pages}
        self.merges = {number: [] for number in pages}
        self.merge_origin = None
        self.result = None
        self.zoom = False
        self.axis = tk.StringVar(value="Column guides")
        toolbar = ttk.Frame(self.window, padding=8)
        toolbar.pack(fill="x")
        self.page_label = ttk.Label(toolbar)
        self.page_label.pack(side="left", padx=(0, 10))
        for title, callback in (
            ("Previous page", lambda: self.move(-1)), ("Next page", lambda: self.move(1)),
            ("Fit / full size", self.toggle_zoom), ("Clear guides", self.clear),
            ("Undo guide", self.undo),
        ):
            ttk.Button(toolbar, text=title, command=callback).pack(side="left", padx=(0, 5))
        ttk.Combobox(toolbar, textvariable=self.axis, state="readonly", width=14,
                     values=("Column guides", "Row guides", "Merge cells")).pack(side="left", padx=5)
        candidates = ttk.Frame(self.window, padding=(8, 0, 8, 6))
        candidates.pack(fill="x")
        self.selector = ttk.Combobox(candidates, state="readonly", width=40)
        self.selector.pack(side="left")
        self.selector.bind("<<ComboboxSelected>>", self.use_candidate)
        self.status = ttk.Label(candidates)
        self.status.pack(side="left", padx=8)
        ttk.Label(self.window, padding=(8, 0, 8, 5), wraplength=920,
                  text="Check the grid against the page. To draw a grid, click its outer edges and inner "
                       "dividers. To merge cells, choose Merge cells and click opposite corners inside the grid.").pack(anchor="w")
        bottom = ttk.Frame(self.window, padding=8)
        bottom.pack(side="bottom", fill="x")
        ttk.Button(bottom, text="Cancel", command=self.window.destroy).pack(side="right")
        self.confirm = ttk.Button(bottom, text="Review cells in this grid", command=self.apply)
        self.confirm.pack(side="right", padx=6)
        frame = ttk.Frame(self.window)
        frame.pack(fill="both", expand=True, padx=8)
        self.canvas = tk.Canvas(frame, background="#e0e0e0", highlightthickness=0)
        vertical = ttk.Scrollbar(frame, orient="vertical", command=self.canvas.yview)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.canvas.bind("<Button-1>", self.add_guide)
        self.load_page()

    @property
    def number(self):
        return self.numbers[self.index]

    def load_page(self):
        self.merge_origin = None
        self.selector.configure(values=["Draw a grid manually"] + [
            f"Detected grid {index + 1} · {grid.shape[0]} rows × {grid.shape[1]} columns"
            for index, grid in enumerate(self.grids.get(self.number, []))
        ])
        self.selector.current(0)
        if not self.guides[self.number][0] and not self.guides[self.number][1] and self.grids.get(self.number):
            self.selector.current(1)
            self.use_candidate()
        self.show(reset_scroll=True)

    def show(self, reset_scroll=False):
        from PIL import Image, ImageTk

        raster = self.pages[self.number].copy()
        width, height = raster.size
        if not self.zoom:
            raster.thumbnail((920, 600), Image.Resampling.LANCZOS)
        self.scale = raster.width / width, raster.height / height
        self.photo = ImageTk.PhotoImage(raster, master=self.window)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.canvas.configure(scrollregion=(0, 0, raster.width, raster.height))
        if reset_scroll:
            self.canvas.xview_moveto(0)
            self.canvas.yview_moveto(0)
        self.draw_guides()

    def draw_guides(self):
        self.canvas.delete("guide")
        columns, rows = self.guides[self.number]
        sx, sy = self.scale
        image = self.pages[self.number]
        left, right = (min(columns), max(columns)) if len(columns) > 1 else (0, image.width)
        top, bottom = (min(rows), max(rows)) if len(rows) > 1 else (0, image.height)
        for x in columns:
            self.canvas.create_line(x * sx, top * sy, x * sx, bottom * sy, fill="#1264a3", width=2, tags="guide")
        for y in rows:
            self.canvas.create_line(left * sx, y * sy, right * sx, y * sy, fill="#ba3a18", width=2, tags="guide")
        xs, ys = sorted(columns), sorted(rows)
        for r0, c0, r1, c1 in self.merges[self.number]:
            self.canvas.create_rectangle(xs[c0] * sx, ys[r0] * sy, xs[c1 + 1] * sx,
                                         ys[r1 + 1] * sy, outline="#1b8242", width=4, tags="guide")
        self.page_label.configure(text=f"Page {self.index + 1} of {len(self.numbers)}")
        self.status.configure(text=f"{max(0, len(rows) - 1)} rows × {max(0, len(columns) - 1)} columns")
        self.confirm.state(["!disabled" if min(len(columns), len(rows)) >= 3 else "disabled"])

    def move(self, amount):
        self.index = max(0, min(self.index + amount, len(self.numbers) - 1))
        self.load_page()

    def toggle_zoom(self):
        self.zoom = not self.zoom
        self.show(reset_scroll=True)

    def use_candidate(self, _event=None):
        index = self.selector.current()
        if index:
            grid = self.grids[self.number][index - 1]
            self.guides[self.number] = list(grid.columns), list(grid.rows)
        else:
            self.guides[self.number] = [], []
        self.history[self.number].clear()
        self.merges[self.number].clear()
        self.merge_origin = None
        if hasattr(self, "scale"):
            self.draw_guides()

    def add_guide(self, event):
        if self.axis.get() == "Merge cells":
            self.select_merge(event)
            return
        if self.merges[self.number]:
            self.status.configure(text="Undo merged areas before moving grid boundaries.")
            return
        axis = int(self.axis.get() == "Row guides")
        point = (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))[axis]
        value = round(point / self.scale[axis])
        guides = self.guides[self.number][axis]
        if 0 <= value <= self.pages[self.number].size[axis] and all(abs(value - other) >= 12 for other in guides):
            guides.append(value)
            self.history[self.number].append((axis, value))
            self.selector.current(0)
            self.draw_guides()

    def undo(self):
        if self.history[self.number]:
            axis, value = self.history[self.number].pop()
            if axis == "merge":
                self.merges[self.number].remove(value)
            else:
                self.guides[self.number][axis].remove(value)
            self.merge_origin = None
            self.draw_guides()

    def select_merge(self, event):
        xs, ys = (sorted(guides) for guides in self.guides[self.number])
        if min(len(xs), len(ys)) < 3:
            self.status.configure(text="Draw the row and column boundaries first.")
            return
        x = self.canvas.canvasx(event.x) / self.scale[0]
        y = self.canvas.canvasy(event.y) / self.scale[1]
        row, column = bisect_right(ys, y) - 1, bisect_right(xs, x) - 1
        if not (0 <= row < len(ys) - 1 and 0 <= column < len(xs) - 1):
            return
        if self.merge_origin is None:
            self.merge_origin = row, column
            self.status.configure(text="Click the cell at the opposite corner.")
            return
        origin_row, origin_column = self.merge_origin
        self.merge_origin = None
        area = (min(row, origin_row), min(column, origin_column),
                max(row, origin_row), max(column, origin_column))
        merges = self.merges[self.number]
        try:
            RasterTable(self.number, tuple(xs), tuple(ys), (*merges, area))
        except ValueError as error:
            self.status.configure(text=str(error))
            return
        merges.append(area)
        self.history[self.number].append(("merge", area))
        self.draw_guides()

    def clear(self):
        self.selector.current(0)
        self.use_candidate()

    def apply(self):
        columns, rows = self.guides[self.number]
        if min(len(columns), len(rows)) >= 3:
            self.result = RasterTable(self.number, tuple(sorted(columns)), tuple(sorted(rows)),
                                      tuple(self.merges[self.number]))
            self.window.destroy()
