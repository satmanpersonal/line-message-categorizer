"""Tk desktop browser for local LINE exports."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from categorizer import Store
from configuration import DATABASE, IMPORTS, ROOT, save_settings, settings
from line_import import import_file


class CategorizerApp:
    def __init__(self, root):
        self.root = root
        self.config = settings()
        IMPORTS.mkdir(parents=True, exist_ok=True)
        self.store = Store(DATABASE)
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.pending = None
        self.seen = {}
        self.candidates = {}
        self.rows = {}
        self.page = 0
        self.page_size = 200
        self.category = tk.StringVar(value="All categories")
        self.chat = tk.StringVar(value="All chats")
        self.watching = tk.BooleanVar(value=True)
        self.summary = tk.StringVar()
        self.activity = tk.StringVar(value="Ready. Import LINE chat exports to begin.")
        self.build()
        self.refresh()
        self.root.after(300, self.tick)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def build(self):
        root = self.root
        root.title("LINE message categorizer")
        root.geometry("1120x780")
        root.minsize(880, 650)
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Treeview", rowheight=27)
        outer = ttk.Frame(root, padding=16)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="LINE message categorizer", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(outer, text="All your exported chats, organized locally. Update exports to bring in newer messages.").pack(anchor="w", pady=(4, 12))
        toolbar = ttk.Frame(outer)
        toolbar.pack(fill="x")
        self.import_button = ttk.Button(toolbar, text="Import chat files…", command=self.choose_files)
        self.import_button.pack(side="left")
        ttk.Button(toolbar, text="Open import folder", command=lambda: os.startfile(IMPORTS)).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Category rules…", command=self.edit_rules).pack(side="left")
        ttk.Button(toolbar, text="Assign chat category…", command=self.assign_chat).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Export CSV", command=self.export).pack(side="left")
        ttk.Label(outer, textvariable=self.summary, font=("Segoe UI", 11), wraplength=1050, justify="left").pack(anchor="w", pady=(12, 4))
        filters = ttk.Frame(outer)
        filters.pack(fill="x", pady=6)
        ttk.Label(filters, text="Category").pack(side="left")
        self.category_box = ttk.Combobox(filters, textvariable=self.category, state="readonly", width=31)
        self.category_box.pack(side="left", padx=(6, 14))
        self.category_box.bind("<<ComboboxSelected>>", lambda event: self.refresh())
        ttk.Label(filters, text="Chat").pack(side="left")
        self.chat_box = ttk.Combobox(filters, textvariable=self.chat, state="readonly", width=27)
        self.chat_box.pack(side="left", padx=6)
        self.chat_box.bind("<<ComboboxSelected>>", lambda event: self.refresh())
        ttk.Checkbutton(filters, text="Watch import folder", variable=self.watching).pack(side="right")
        table_frame = ttk.Frame(outer)
        table_frame.pack(fill="both", expand=True, pady=6)
        columns = ("category", "chat", "sent", "sender", "message")
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse", height=11)
        for name, title, width in (("category", "Category", 200), ("chat", "Chat", 160),
                                   ("sent", "Sent (export local time)", 155), ("sender", "Sender", 120), ("message", "Message", 370)):
            self.table.heading(name, text=title)
            self.table.column(name, width=width, minwidth=70)
        vertical = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.table.bind("<<TreeviewSelect>>", self.show_message)
        pager = ttk.Frame(outer)
        pager.pack(fill="x", pady=3)
        self.previous_button = ttk.Button(pager, text="Previous", command=lambda: self.change_page(-1))
        self.previous_button.pack(side="left")
        self.next_button = ttk.Button(pager, text="Next", command=lambda: self.change_page(1))
        self.next_button.pack(side="left", padx=6)
        self.page_label = ttk.Label(pager)
        self.page_label.pack(side="left")
        ttk.Label(outer, text="Selected message / matched keywords").pack(anchor="w")
        self.details = scrolledtext.ScrolledText(outer, height=5, wrap="word", font=("Segoe UI", 10))
        self.details.pack(fill="x", pady=4)
        self.set_details("No messages yet. In LINE: open a chat → menu → Save chat.\nSave its .txt file in the import folder, or use Import chat files.\nYou can import multiple chats. Chat assignments help with short or ambiguous messages.")
        ttk.Label(outer, textvariable=self.activity, wraplength=1050).pack(anchor="w", pady=4)
        self.log = scrolledtext.ScrolledText(outer, height=4, wrap="word", state="disabled", font=("Segoe UI", 9))
        self.log.pack(fill="x")

    def set_details(self, text):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("end", text)
        self.details.configure(state="disabled")

    def report(self, text):
        self.activity.set(text)
        self.log.configure(state="normal")
        self.log.insert("end", f"{datetime.now():%H:%M:%S}  {text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def refresh(self, reset_page=True):
        if reset_page:
            self.page = 0
        counts = self.store.counts()
        chats = self.store.chats()
        self.summary.set(f"{sum(counts.values()):,} messages  ·  {len(chats)} chats  ·  " + "  |  ".join(
            f"{name}: {count}" for name, count in counts.items()))
        categories = ["All categories", *self.config["categories"], "Needs review", "Uncategorized"]
        self.category_box["values"] = categories
        self.chat_box["values"] = ["All chats", *chats]
        if self.category.get() not in categories:
            self.category.set("All categories")
        if self.chat.get() not in ["All chats", *chats]:
            self.chat.set("All chats")
        selected = self.table.selection()
        self.table.delete(*self.table.get_children())
        self.rows = {}
        category_filter = None if self.category.get() == "All categories" else self.category.get()
        chat_filter = None if self.chat.get() == "All chats" else self.chat.get()
        count = self.store.entry_count(category_filter, chat_filter)
        self.page = min(self.page, max(0, (count - 1) // self.page_size))
        offset = self.page * self.page_size
        self.previous_button.configure(state="normal" if self.page else "disabled")
        self.next_button.configure(state="normal" if offset + self.page_size < count else "disabled")
        self.page_label.configure(text=f"{offset + 1 if count else 0}-{min(offset+self.page_size, count)} of {count:,} matching messages")
        for row in self.store.entries(category_filter, chat_filter, self.page_size, offset):
            entry_id, chat, sent_at, sender, text, category, keywords = row
            key = str(entry_id)
            self.rows[key] = row
            self.table.insert("", "end", iid=key, values=(category, chat, (sent_at or "").replace("T", " "),
                                                          sender or "", text.replace("\n", "  ")[:240]))
        if selected and selected[0] in self.rows:
            self.table.selection_set(selected[0])
        elif self.rows:
            self.table.selection_set(next(iter(self.rows)))
        self.show_message()

    def change_page(self, direction):
        self.page = max(0, self.page + direction)
        self.refresh(reset_page=False)

    def show_message(self, event=None):
        selection = self.table.selection()
        if not selection or selection[0] not in self.rows:
            self.set_details("No messages match this view. Import LINE chat exports to begin, or change the category/chat filter.")
            return
        _, chat, sent, sender, text, category, keywords = self.rows[selection[0]]
        words = ", ".join(json.loads(keywords)) or "Chat assignment / no matching keywords"
        self.set_details(f"{chat} · {sender or 'Unknown sender'} · {sent or 'Observed only'}\n{category} · {words}\n\n{text}")

    def choose_files(self):
        paths = filedialog.askopenfilenames(parent=self.root, title="Select LINE Save chat text exports",
                                            initialdir=IMPORTS, filetypes=[("LINE text exports", "*.txt")])
        if paths:
            self.submit([Path(path) for path in paths])

    def submit(self, paths):
        if self.pending:
            self.report("An import is already running. Please try again when it finishes.")
            return
        config = json.loads(json.dumps(self.config))
        def work():
            results = []
            store = Store(DATABASE)
            try:
                for path in paths:
                    try:
                        chat, total, added, unresolved = import_file(store, path, config)
                        results.append(f"{path.name}: {chat}: {added} added, {total-added} already saved.")
                        if unresolved:
                            results.append(f"{chat}: {unresolved} sender names unresolved. Full lines preserved; add sender_names in Category rules and reimport.")
                    except Exception as error:
                        results.append(f"Could not import {path.name}: {error}")
            finally:
                store.close()
            return results
        self.import_button.configure(state="disabled")
        self.pending = self.executor.submit(work)
        self.report(f"Importing {len(paths)} export file(s)…")

    def tick(self):
        if self.pending and self.pending.done():
            try:
                for result in self.pending.result():
                    self.report(result)
            except Exception as error:
                self.report(f"Import failed: {error}")
            self.pending = None
            self.import_button.configure(state="normal")
            self.refresh()
        if self.watching.get() and not self.pending:
            ready = []
            for path in IMPORTS.glob("*.txt"):
                try:
                    stat = path.stat()
                    signature = (stat.st_mtime_ns, stat.st_size)
                    if self.seen.get(path) != signature:
                        if self.candidates.get(path) == signature:
                            ready.append(path)
                            self.seen[path] = signature
                        self.candidates[path] = signature
                except OSError:
                    continue
            if ready:
                self.submit(ready)
        self.root.after(int(self.config["poll_seconds"] * 1000), self.tick)

    def edit_rules(self):
        window = tk.Toplevel(self.root)
        window.title("Category rules and chat assignments")
        window.geometry("800x650")
        ttk.Label(window, text="Edit keyword rules and optional exact chat-name assignments. Work specialties override general Work.\n"
                  "Ties → Needs review. No match → Uncategorized. date_order: MDY or DMY for non-year-first dates.",
                  wraplength=760).pack(anchor="w", padx=12, pady=12)
        editor = scrolledtext.ScrolledText(window, wrap="word", font=("Consolas", 11))
        editor.pack(fill="both", expand=True, padx=12)
        editor.insert("end", json.dumps({key: self.config.get(key, [] if key == "sender_names" else {}) for key in
                                        ("categories", "chat_categories", "date_order", "sender_names")}, ensure_ascii=False, indent=2))
        def save():
            try:
                updated = dict(self.config)
                updated.update(json.loads(editor.get("1.0", "end")))
                if self.pending:
                    raise ValueError("Wait until the current import finishes before changing rules")
                save_settings(updated)
                self.config = updated
                self.seen.clear()
                self.candidates.clear()
                count = self.store.reclassify(updated["categories"], updated.get("chat_categories"))
                self.refresh()
                self.report(f"Rules saved. Recategorized {count} messages.")
                window.destroy()
            except Exception as error:
                messagebox.showerror("Could not save rules", str(error), parent=window)
        ttk.Button(window, text="Save and recategorize saved messages", command=save).pack(pady=12)

    def assign_chat(self):
        chats = self.store.chats()
        if not chats:
            messagebox.showinfo("Import a chat first", "Import a LINE text export, then assign that chat to a category.", parent=self.root)
            return
        window = tk.Toplevel(self.root)
        window.title("Assign chat category")
        window.geometry("520x230")
        ttk.Label(window, text="A chat assignment overrides keyword matching for every message in that chat.", wraplength=470).pack(padx=16, pady=12)
        chosen_chat = tk.StringVar(value=self.chat.get() if self.chat.get() in chats else chats[0])
        chosen_category = tk.StringVar(value=self.config.get("chat_categories", {}).get(chosen_chat.get(), "Use keywords"))
        ttk.Combobox(window, textvariable=chosen_chat, values=chats, state="readonly", width=54).pack(pady=6)
        ttk.Combobox(window, textvariable=chosen_category, values=["Use keywords", *self.config["categories"]], state="readonly", width=54).pack(pady=6)
        def save():
            if self.pending:
                messagebox.showinfo("Import running", "Wait until the import finishes.", parent=window)
                return
            updated = json.loads(json.dumps(self.config))
            mappings = updated.setdefault("chat_categories", {})
            if chosen_category.get() == "Use keywords":
                mappings.pop(chosen_chat.get(), None)
            else:
                mappings[chosen_chat.get()] = chosen_category.get()
            try:
                save_settings(updated)
                self.config = updated
                self.store.reclassify(updated["categories"], mappings)
                self.refresh()
                self.report("Chat assignment saved; messages recategorized.")
                window.destroy()
            except Exception as error:
                messagebox.showerror("Could not save assignment", str(error), parent=window)
        ttk.Button(window, text="Save assignment", command=save).pack(pady=12)

    def export(self):
        try:
            target = self.store.export_csv()
            self.report(f"CSV saved to {target}")
            messagebox.showinfo("CSV exported", str(target), parent=self.root)
        except Exception as error:
            messagebox.showerror("Export failed", str(error), parent=self.root)

    def close(self):
        # Finish any atomic import before Python exits; source exports are never changed.
        self.executor.shutdown(wait=False)
        self.store.close()
        self.root.destroy()


def launch():
    root = tk.Tk()
    try:
        CategorizerApp(root)
    except Exception as error:
        messagebox.showerror("LINE categorizer could not start", str(error), parent=root)
        root.destroy()
        raise
    root.mainloop()
