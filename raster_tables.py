"""Find complete ruled grids in page rasters for cell-by-cell OCR review."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RasterTable:
    page: int
    columns: tuple[int, ...]
    rows: tuple[int, ...]
    merges: tuple[tuple[int, int, int, int], ...] = ()

    def __post_init__(self):
        if any(len(axis) < 3 or any(right - left < 12 for left, right in zip(axis, axis[1:]))
               for axis in (self.columns, self.rows)):
            raise ValueError("A table needs at least two rows and two columns with separate guides.")
        taken = set()
        for r0, c0, r1, c1 in self.merges:
            height, width = self.shape
            if not (0 <= r0 <= r1 < height and 0 <= c0 <= c1 < width) or (r0, c0) == (r1, c1):
                raise ValueError("A merged area must cover several cells inside the grid.")
            cells = {(row, column) for row in range(r0, r1 + 1) for column in range(c0, c1 + 1)}
            if cells & taken:
                raise ValueError("Merged areas must not overlap.")
            taken.update(cells)

    @property
    def shape(self):
        return len(self.rows) - 1, len(self.columns) - 1

    def cells(self):
        for row, (top, bottom) in enumerate(zip(self.rows, self.rows[1:])):
            for column, (left, right) in enumerate(zip(self.columns, self.columns[1:])):
                merged = self.merge_at(row, column)
                cell_right, cell_bottom = right, bottom
                if merged and merged[:2] == (row, column):
                    cell_right = self.columns[merged[3] + 1]
                    cell_bottom = self.rows[merged[2] + 1]
                yield row, column, (left, top, cell_right, cell_bottom)

    def merge_at(self, row, column):
        return next(((r0, c0, r1, c1) for r0, c0, r1, c1 in self.merges
                     if r0 <= row <= r1 and c0 <= column <= c1), None)


def centers(indices):
    runs = []
    for value in map(int, indices):
        if runs and value == runs[-1][-1] + 1:
            runs[-1].append(value)
        else:
            runs.append([value])
    return [(run[0] + run[-1]) // 2 for run in runs]


def find_grids(image, page):
    import cv2
    import numpy as np

    gray = np.asarray(image.convert("L"))
    height, width = gray.shape
    if min(width, height) < 40:
        return []
    ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((1, max(20, width // 26)), np.uint8))
    vertical = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((max(20, height // 26), 1), np.uint8))
    _, _, stats, _ = cv2.connectedComponentsWithStats(cv2.bitwise_or(horizontal, vertical))
    tables = []
    for left, top, w, h, _ in stats[1:]:
        if w < 40 or h < 35:
            continue
        a = horizontal[top:top + h, left:left + w] > 0
        b = vertical[top:top + h, left:left + w] > 0
        ys = centers(np.flatnonzero(a.mean(axis=1) >= 0.75))
        xs = centers(np.flatnonzero(b.mean(axis=0) >= 0.75))
        if min(len(xs), len(ys)) < 3 or min(np.diff(xs)) < 12 or min(np.diff(ys)) < 12:
            continue
        if any(a[max(0, y - 2):y + 3, x0:x1].any(axis=0).mean() < 0.85
               for y in ys for x0, x1 in zip(xs, xs[1:])):
            continue
        if any(b[y0:y1, max(0, x - 2):x + 3].any(axis=1).mean() < 0.85
               for x in xs for y0, y1 in zip(ys, ys[1:])):
            continue
        tables.append(RasterTable(page, tuple(int(left + x) for x in xs),
                                  tuple(int(top + y) for y in ys)))
    return sorted(tables, key=lambda table: (table.rows[0], table.columns[0]))
