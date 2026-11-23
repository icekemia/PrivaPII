"""Local review window for linking selected people across documents."""

import sqlite3
import tkinter as tk
from tkinter import messagebox, ttk

from person_review import normalized, person_mentions


class PersonReviewView:
    def __init__(self, parent, workspace):
        self.window = tk.Toplevel(parent)
        self.window.title("Review people across documents")
        self.window.geometry("1080x620")
        self.window.transient(parent)
        self.workspace = workspace
        self.target = None
        self.scope = None
        self.changed = False
        self.items = {}
        controls = ttk.Frame(self.window, padding=8)
        controls.pack(fill="x")
        ttk.Label(controls, text="Find a name or document").pack(side="left")
        self.query = tk.StringVar()
        field = ttk.Entry(controls, textvariable=self.query, width=30)
        field.pack(side="left", padx=8)
        self.candidates_only = tk.BooleanVar()
        ttk.Checkbutton(controls, text="Candidates only", variable=self.candidates_only,
                        command=self.refresh).pack(side="left")
        ttk.Button(controls, text="Show candidate matches", command=self.show_matches).pack(side="left", padx=6)
        ttk.Button(controls, text="Clear match view", command=self.clear_matches).pack(side="left")
        self.query.trace_add("write", lambda *_: self.refresh())
        ttk.Label(self.window, text="Spelling and inflection matches are suggestions. Check the source context before linking.",
                  padding=(8, 0, 8, 6)).pack(anchor="w")
        frame = ttk.Frame(self.window, padding=(8, 0, 8, 8))
        frame.pack(fill="both", expand=True)
        columns = ("person", "document", "group", "status", "context")
        self.table = ttk.Treeview(frame, columns=columns, show="headings", selectmode="extended")
        for key, label, width in zip(
                columns, ("Person mention", "Document", "Entity ID", "Candidate", "Source context"),
                (170, 160, 95, 160, 427)):
            self.table.heading(key, text=label)
            self.table.column(key, width=width, stretch=key == "context")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.table.pack(side="left", fill="both", expand=True)
        action = ttk.Frame(self.window, padding=8)
        action.pack(fill="x")
        ttk.Button(action, text="Set selected mention as target", command=self.set_target).pack(side="left", padx=(0, 6))
        ttk.Button(action, text="Link selected mentions to target", command=self.link).pack(side="left")
        ttk.Button(action, text="Show entity mentions", command=self.show_entity).pack(side="left", padx=6)
        ttk.Button(action, text="Split selected mentions", command=self.split).pack(side="left")
        ttk.Button(action, text="Close", command=self.window.destroy).pack(side="right")
        self.status = tk.StringVar()
        ttk.Label(self.window, textvariable=self.status, padding=(8, 0, 8, 8)).pack(anchor="w")
        self.refresh()
        field.focus_set()

    def refresh(self):
        selection = self.table.selection()
        self.items = {item.occurrence_id: item for item in person_mentions(self.workspace.documents)}
        self.table.delete(*self.table.get_children())
        keywords = [normalized(piece) for piece in self.query.get().split("|") if piece.strip()]
        visible = 0
        for key, item in self.items.items():
            if self.scope is not None and key not in self.scope:
                continue
            if self.candidates_only.get() and not item.candidate_ids:
                continue
            index_text = normalized(item.value + " " + item.document_name)
            if keywords and not any(term in index_text for term in keywords):
                continue
            reasons = []
            if item.spelling_candidate:
                reasons.append("Same spelling")
            if item.inflection_candidate:
                reasons.append("Possible inflection")
            status = " / ".join(reasons)
            self.table.insert("", "end", iid=key, values=(
                item.value, item.document_name, item.entity_id[:8], status, item.context,
            ))
            if key in selection:
                self.table.selection_add(key)
            visible += 1
        self.update_status(visible)

    def show_matches(self):
        selected = self.table.selection()
        if len(selected) != 1:
            self.status.set("Select one mention to see its candidate matches.")
            return
        item = self.items[selected[0]]
        if not item.candidate_ids:
            self.status.set("No spelling or inflection candidates for the selected mention.")
            return
        self.scope = {item.occurrence_id, *item.candidate_ids}
        self.candidates_only.set(False)
        self.query.set("")

    def clear_matches(self):
        self.scope = None
        self.refresh()

    def show_entity(self):
        selected = self.table.selection()
        if len(selected) != 1:
            self.status.set("Select one mention to view its complete group.")
            return
        entity = self.items[selected[0]].entity_id
        self.scope = {key for key, item in self.items.items() if item.entity_id == entity}
        self.candidates_only.set(False)
        self.query.set("")

    def update_status(self, visible=None):
        count = len(self.table.get_children()) if visible is None else visible
        target = self.items.get(self.target)
        label = f"Target: {target.value} · {target.document_name} · {target.entity_id[:8]}" if target else "Choose a target mention."
        self.status.set(f"{count} mentions shown · {label}")

    def set_target(self):
        selected = self.table.selection()
        if len(selected) != 1:
            self.status.set("Select one mention to set the target.")
            return
        self.target = selected[0]
        self.update_status()

    def link(self):
        selected = self.table.selection()
        target = self.items.get(self.target)
        if target is None or not selected:
            self.status.set("Set a target and select the mentions to link.")
            return
        eligible = [key for key in selected if self.items[key].entity_id != target.entity_id]
        if not eligible:
            self.status.set("The selected mentions already share the target entity ID.")
            return
        if not messagebox.askyesno("Confirm person link",
                                   f"Link {len(eligible)} selected mentions to {target.value} in {target.document_name}?",
                                   parent=self.window):
            return
        try:
            changed = self.workspace.link_people(eligible, self.target)
        except (OSError, ValueError, sqlite3.Error) as error:
            messagebox.showerror("Person links unavailable", str(error), parent=self.window)
            return
        self.changed |= changed > 0
        self.refresh()

    def split(self):
        selected = self.table.selection()
        if not selected:
            self.status.set("Select the mentions that belong to a separate person.")
            return
        if not messagebox.askyesno(
                "Confirm person split",
                f"Move {len(selected)} selected mentions to one new entity ID? "
                "Regenerate exports to share the corrected grouping.",
                parent=self.window):
            return
        try:
            changed = self.workspace.split_people(selected)
        except (OSError, ValueError, sqlite3.Error) as error:
            messagebox.showerror("Could not split person mentions", str(error), parent=self.window)
            return
        self.changed |= changed > 0
        if self.target in selected:
            self.target = None
        self.scope = None
        self.refresh()
