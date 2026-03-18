#!/usr/bin/env python3
"""PDF Gear - A standalone PDF manipulation tool."""

import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, ImageTk
from pypdf import PdfReader, PdfWriter

THUMB_W = 120
THUMB_H = 160


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def render_thumbnails(pdf_path, width=THUMB_W, height=THUMB_H, rotations=None):
    """Render all pages of a PDF as PIL thumbnail images."""
    doc = fitz.open(pdf_path)
    thumbs = []
    for i in range(len(doc)):
        page = doc[i]
        zx = width / page.rect.width
        zy = height / page.rect.height
        zoom = min(zx, zy)
        mat = fitz.Matrix(zoom, zoom)
        if rotations and rotations.get(i):
            mat = mat.prerotate(rotations[i])
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        thumbs.append(img)
    doc.close()
    return thumbs


# ---------------------------------------------------------------------------
# Scrollable thumbnail panel (used by Delete & Rotate tabs)
# ---------------------------------------------------------------------------

class ThumbnailPanel(tk.Frame):
    """Scrollable grid of page thumbnails with optional multi-select."""

    def __init__(self, parent, selectable=True, **kw):
        super().__init__(parent, **kw)
        self._selectable = selectable
        self._thumbs = []       # PIL images
        self._tk_imgs = []      # prevent GC
        self._frames = []       # per-page frames
        self.selected: set[int] = set()
        self.page_count = 0

        self.canvas = tk.Canvas(self, bg="#f0f0f0", highlightthickness=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg="#f0f0f0")

        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda _: self._layout())

        # mousewheel – only when pointer is over this panel
        self.bind("<Enter>", self._bind_wheel)
        self.bind("<Leave>", self._unbind_wheel)

    # -- mousewheel --------------------------------------------------------

    def _bind_wheel(self, _event):
        if sys.platform == "darwin":
            self.canvas.bind_all("<MouseWheel>", self._on_wheel_mac)
        else:
            self.canvas.bind_all("<MouseWheel>", self._on_wheel_other)
            self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"))
            self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))

    def _unbind_wheel(self, _event):
        self.canvas.unbind_all("<MouseWheel>")
        if sys.platform != "darwin":
            self.canvas.unbind_all("<Button-4>")
            self.canvas.unbind_all("<Button-5>")

    def _on_wheel_mac(self, event):
        self.canvas.yview_scroll(-event.delta, "units")

    def _on_wheel_other(self, event):
        self.canvas.yview_scroll(-event.delta // 120, "units")

    # -- public API --------------------------------------------------------

    def load(self, thumbnails: list[Image.Image], labels: list[str] | None = None):
        self.clear()
        self._thumbs = thumbnails
        self.page_count = len(thumbnails)

        for i, img in enumerate(thumbnails):
            tk_img = ImageTk.PhotoImage(img)
            self._tk_imgs.append(tk_img)

            frame = tk.Frame(self.inner, bd=2, relief="flat", bg="#f0f0f0", padx=4, pady=4)
            lbl = tk.Label(frame, image=tk_img, bg="white", bd=1, relief="solid")
            lbl.pack()
            label_text = labels[i] if labels else f"Page {i + 1}"
            txt = tk.Label(frame, text=label_text, bg="#f0f0f0", font=("Arial", 9))
            txt.pack()

            if self._selectable:
                for w in (frame, lbl, txt):
                    w.bind("<Button-1>", lambda _e, idx=i: self._toggle(idx))

            self._frames.append(frame)
        self._layout()

    def clear(self):
        for f in self._frames:
            f.destroy()
        self._frames.clear()
        self._tk_imgs.clear()
        self._thumbs.clear()
        self.selected.clear()
        self.page_count = 0

    def get_selected(self) -> list[int]:
        return sorted(self.selected)

    def select_all(self):
        for i in range(self.page_count):
            self.selected.add(i)
            self._frames[i].configure(relief="solid", bg="#4a90d9")

    def deselect_all(self):
        for i in list(self.selected):
            self._frames[i].configure(relief="flat", bg="#f0f0f0")
        self.selected.clear()

    # -- internals ---------------------------------------------------------

    def _toggle(self, idx):
        if idx in self.selected:
            self.selected.discard(idx)
            self._frames[idx].configure(relief="flat", bg="#f0f0f0")
        else:
            self.selected.add(idx)
            self._frames[idx].configure(relief="solid", bg="#4a90d9")

    def _layout(self):
        if not self._frames:
            return
        cw = self.canvas.winfo_width()
        if cw <= 1:
            cw = 600
        cols = max(1, cw // (THUMB_W + 24))
        for i, f in enumerate(self._frames):
            f.grid(row=i // cols, column=i % cols, padx=4, pady=4)


# ===================================================================
# MERGE TAB
# ===================================================================

class MergeTab(tk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self.files: list[str] = []
        self._file_thumbs: dict[str, list[Image.Image]] = {}

        # top / bottom split
        paned = ttk.PanedWindow(self, orient="vertical")
        paned.pack(fill="both", expand=True, padx=10, pady=10)

        # --- top: file list + buttons ---
        top = tk.Frame(paned)
        paned.add(top, weight=1)

        tk.Label(top, text="PDF Files to Merge", font=("Arial", 12, "bold")).pack(anchor="w")

        controls = tk.Frame(top)
        controls.pack(fill="both", expand=True, pady=(5, 0))

        lf = tk.Frame(controls)
        lf.pack(side="left", fill="both", expand=True)
        self.listbox = tk.Listbox(lf, selectmode="single", font=("Arial", 10))
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        bf = tk.Frame(controls)
        bf.pack(side="right", fill="y", padx=(5, 0))
        for text, cmd in [
            ("Add Files", self._add),
            ("Remove", self._remove),
            ("Move Up", self._up),
            ("Move Down", self._down),
            ("Clear All", self._clear),
        ]:
            ttk.Button(bf, text=text, command=cmd, width=15).pack(pady=3)
        ttk.Separator(bf, orient="horizontal").pack(fill="x", pady=10)
        ttk.Button(bf, text="Merge & Save", command=self._merge, width=15).pack(pady=3)

        # --- bottom: page preview ---
        bottom = tk.Frame(paned)
        paned.add(bottom, weight=2)

        tk.Label(bottom, text="Page Preview", font=("Arial", 10, "bold")).pack(anchor="w")
        self.panel = ThumbnailPanel(bottom, selectable=False)
        self.panel.pack(fill="both", expand=True)

    # -- actions -----------------------------------------------------------

    def _add(self):
        paths = filedialog.askopenfilenames(title="Select PDF files", filetypes=[("PDF files", "*.pdf")])
        for p in paths:
            try:
                n = len(PdfReader(p).pages)
            except Exception:
                n = "?"
            self.files.append(p)
            self.listbox.insert("end", f"{Path(p).name}  ({n} pages)")
            if p not in self._file_thumbs:
                self._file_thumbs[p] = render_thumbnails(p)
        if paths:
            self._refresh_preview()

    def _remove(self):
        sel = self.listbox.curselection()
        if sel:
            path = self.files.pop(sel[0])
            self.listbox.delete(sel[0])
            if path not in self.files:
                self._file_thumbs.pop(path, None)
            self._refresh_preview()

    def _up(self):
        sel = self.listbox.curselection()
        if sel and sel[0] > 0:
            i = sel[0]
            self.files[i], self.files[i - 1] = self.files[i - 1], self.files[i]
            txt = self.listbox.get(i)
            self.listbox.delete(i)
            self.listbox.insert(i - 1, txt)
            self.listbox.selection_set(i - 1)
            self._refresh_preview()

    def _down(self):
        sel = self.listbox.curselection()
        if sel and sel[0] < len(self.files) - 1:
            i = sel[0]
            self.files[i], self.files[i + 1] = self.files[i + 1], self.files[i]
            txt = self.listbox.get(i)
            self.listbox.delete(i)
            self.listbox.insert(i + 1, txt)
            self.listbox.selection_set(i + 1)
            self._refresh_preview()

    def _clear(self):
        self.files.clear()
        self._file_thumbs.clear()
        self.listbox.delete(0, "end")
        self.panel.clear()

    def _refresh_preview(self):
        all_thumbs: list[Image.Image] = []
        all_labels: list[str] = []
        for path in self.files:
            thumbs = self._file_thumbs.get(path, [])
            name = Path(path).name
            for i, t in enumerate(thumbs):
                all_thumbs.append(t)
                all_labels.append(f"{name}\nPage {i + 1}")
        self.panel.load(all_thumbs, labels=all_labels)

    def _merge(self):
        if len(self.files) < 2:
            messagebox.showwarning("Merge", "Add at least 2 PDF files.")
            return
        out = filedialog.asksaveasfilename(
            title="Save Merged PDF", defaultextension=".pdf", filetypes=[("PDF", "*.pdf")]
        )
        if not out:
            return
        try:
            writer = PdfWriter()
            for path in self.files:
                for page in PdfReader(path).pages:
                    writer.add_page(page)
            with open(out, "wb") as f:
                writer.write(f)
            messagebox.showinfo("Merge", f"Merged {len(self.files)} files.\n{out}")
        except Exception as e:
            messagebox.showerror("Merge Error", str(e))


# ===================================================================
# DELETE PAGES TAB
# ===================================================================

class DeleteTab(tk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self.pdf_path = None
        self.page_count = 0

        top = tk.Frame(self)
        top.pack(fill="x", padx=10, pady=(10, 5))
        ttk.Button(top, text="Open PDF", command=self._open).pack(side="left")
        self.file_lbl = tk.Label(top, text="No file loaded", font=("Arial", 10))
        self.file_lbl.pack(side="left", padx=10)

        self.panel = ThumbnailPanel(self)
        self.panel.pack(fill="both", expand=True, padx=10, pady=5)

        bot = tk.Frame(self)
        bot.pack(fill="x", padx=10, pady=(5, 10))
        ttk.Button(bot, text="Select All", command=self.panel.select_all).pack(side="left", padx=3)
        ttk.Button(bot, text="Deselect All", command=self.panel.deselect_all).pack(side="left", padx=3)
        ttk.Button(bot, text="Delete Selected & Save", command=self._delete).pack(side="right", padx=3)

    def _open(self):
        path = filedialog.askopenfilename(title="Open PDF", filetypes=[("PDF", "*.pdf")])
        if not path:
            return
        self.pdf_path = path
        self.page_count = len(PdfReader(path).pages)
        self.file_lbl.config(text=f"{Path(path).name} ({self.page_count} pages)")
        self.panel.load(render_thumbnails(path))

    def _delete(self):
        if not self.pdf_path:
            messagebox.showwarning("Delete", "Open a PDF first.")
            return
        sel = self.panel.get_selected()
        if not sel:
            messagebox.showwarning("Delete", "Select pages to delete.")
            return
        if len(sel) >= self.page_count:
            messagebox.showwarning("Delete", "Cannot delete all pages.")
            return

        out = filedialog.asksaveasfilename(
            title="Save PDF", defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
            initialfile=f"{Path(self.pdf_path).stem}_deleted.pdf",
        )
        if not out:
            return
        try:
            reader = PdfReader(self.pdf_path)
            writer = PdfWriter()
            remove = set(sel)
            for i, page in enumerate(reader.pages):
                if i not in remove:
                    writer.add_page(page)
            with open(out, "wb") as f:
                writer.write(f)
            kept = self.page_count - len(sel)
            messagebox.showinfo("Delete", f"Saved {kept} pages.\n{out}")
        except Exception as e:
            messagebox.showerror("Delete Error", str(e))


# ===================================================================
# REORDER TAB
# ===================================================================

class ReorderTab(tk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self.pdf_path = None
        self.order: list[int] = []
        self._tk_imgs: list[ImageTk.PhotoImage] = []

        # top bar
        top = tk.Frame(self)
        top.pack(fill="x", padx=10, pady=(10, 5))
        ttk.Button(top, text="Open PDF", command=self._open).pack(side="left")
        self.file_lbl = tk.Label(top, text="No file loaded", font=("Arial", 10))
        self.file_lbl.pack(side="left", padx=10)

        # main area
        main = tk.Frame(self)
        main.pack(fill="both", expand=True, padx=10, pady=5)

        # page list
        lf = tk.Frame(main)
        lf.pack(side="left", fill="both", expand=True)
        self.listbox = tk.Listbox(lf, selectmode="single", font=("Arial", 11), width=30)
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        # preview
        pf = tk.Frame(main, width=200)
        pf.pack(side="left", fill="y", padx=(10, 0))
        pf.pack_propagate(False)
        tk.Label(pf, text="Preview", font=("Arial", 10, "bold")).pack()
        self.preview = tk.Label(pf, bg="#e0e0e0", relief="sunken")
        self.preview.pack(fill="both", expand=True, pady=5)

        # buttons
        bf = tk.Frame(main)
        bf.pack(side="right", fill="y", padx=(10, 0))
        for text, cmd in [
            ("Move Up", self._up),
            ("Move Down", self._down),
            ("Move to Top", self._top),
            ("Move to Bottom", self._bottom),
            ("Reverse All", self._reverse),
        ]:
            ttk.Button(bf, text=text, command=cmd, width=15).pack(pady=3)

        # bottom
        bot = tk.Frame(self)
        bot.pack(fill="x", padx=10, pady=(5, 10))
        ttk.Button(bot, text="Reset Order", command=self._reset).pack(side="left")
        ttk.Button(bot, text="Save Reordered PDF", command=self._save).pack(side="right")

    def _open(self):
        path = filedialog.askopenfilename(title="Open PDF", filetypes=[("PDF", "*.pdf")])
        if not path:
            return
        self.pdf_path = path
        n = len(PdfReader(path).pages)
        self.order = list(range(n))
        self.file_lbl.config(text=f"{Path(path).name} ({n} pages)")
        thumbs = render_thumbnails(path, width=180, height=240)
        self._tk_imgs = [ImageTk.PhotoImage(t) for t in thumbs]
        self._refresh()

    def _refresh(self):
        self.listbox.delete(0, "end")
        for pos, orig in enumerate(self.order):
            self.listbox.insert("end", f"  {pos + 1}.  Page {orig + 1} (original)")

    def _on_select(self, _event):
        sel = self.listbox.curselection()
        if sel:
            orig = self.order[sel[0]]
            if orig < len(self._tk_imgs):
                self.preview.config(image=self._tk_imgs[orig])

    def _swap(self, delta):
        sel = self.listbox.curselection()
        if not sel:
            return
        i = sel[0]
        j = i + delta
        if 0 <= j < len(self.order):
            self.order[i], self.order[j] = self.order[j], self.order[i]
            self._refresh()
            self.listbox.selection_set(j)
            self._on_select(None)

    def _up(self):
        self._swap(-1)

    def _down(self):
        self._swap(1)

    def _top(self):
        sel = self.listbox.curselection()
        if sel and sel[0] > 0:
            item = self.order.pop(sel[0])
            self.order.insert(0, item)
            self._refresh()
            self.listbox.selection_set(0)
            self._on_select(None)

    def _bottom(self):
        sel = self.listbox.curselection()
        if sel and sel[0] < len(self.order) - 1:
            item = self.order.pop(sel[0])
            self.order.append(item)
            self._refresh()
            self.listbox.selection_set(len(self.order) - 1)
            self._on_select(None)

    def _reverse(self):
        self.order.reverse()
        self._refresh()

    def _reset(self):
        self.order = list(range(len(self.order)))
        self._refresh()

    def _save(self):
        if not self.pdf_path:
            messagebox.showwarning("Reorder", "Open a PDF first.")
            return
        out = filedialog.asksaveasfilename(
            title="Save Reordered PDF", defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
            initialfile=f"{Path(self.pdf_path).stem}_reordered.pdf",
        )
        if not out:
            return
        try:
            reader = PdfReader(self.pdf_path)
            writer = PdfWriter()
            for orig in self.order:
                writer.add_page(reader.pages[orig])
            with open(out, "wb") as f:
                writer.write(f)
            messagebox.showinfo("Reorder", f"Saved reordered PDF.\n{out}")
        except Exception as e:
            messagebox.showerror("Reorder Error", str(e))


# ===================================================================
# ROTATE TAB
# ===================================================================

class RotateTab(tk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self.pdf_path = None
        self.page_count = 0
        self.rotations: dict[int, int] = {}

        top = tk.Frame(self)
        top.pack(fill="x", padx=10, pady=(10, 5))
        ttk.Button(top, text="Open PDF", command=self._open).pack(side="left")
        self.file_lbl = tk.Label(top, text="No file loaded", font=("Arial", 10))
        self.file_lbl.pack(side="left", padx=10)

        self.panel = ThumbnailPanel(self)
        self.panel.pack(fill="both", expand=True, padx=10, pady=5)

        bot = tk.Frame(self)
        bot.pack(fill="x", padx=10, pady=(5, 10))
        ttk.Button(bot, text="Select All", command=self.panel.select_all).pack(side="left", padx=3)
        ttk.Button(bot, text="Deselect All", command=self.panel.deselect_all).pack(side="left", padx=3)

        rf = tk.Frame(bot)
        rf.pack(side="left", padx=20)
        tk.Label(rf, text="Rotate:").pack(side="left")
        ttk.Button(rf, text="90\u00b0 CW", command=lambda: self._rotate(90)).pack(side="left", padx=3)
        ttk.Button(rf, text="90\u00b0 CCW", command=lambda: self._rotate(270)).pack(side="left", padx=3)
        ttk.Button(rf, text="180\u00b0", command=lambda: self._rotate(180)).pack(side="left", padx=3)

        ttk.Button(bot, text="Save Rotated PDF", command=self._save).pack(side="right", padx=3)

    def _open(self):
        path = filedialog.askopenfilename(title="Open PDF", filetypes=[("PDF", "*.pdf")])
        if not path:
            return
        self.pdf_path = path
        self.page_count = len(PdfReader(path).pages)
        self.rotations = {i: 0 for i in range(self.page_count)}
        self.file_lbl.config(text=f"{Path(path).name} ({self.page_count} pages)")
        self.panel.load(render_thumbnails(path))

    def _rotate(self, degrees):
        sel = self.panel.get_selected()
        if not sel:
            messagebox.showwarning("Rotate", "Select pages to rotate.")
            return
        for idx in sel:
            self.rotations[idx] = (self.rotations[idx] + degrees) % 360

        # re-render thumbnails with current rotations
        old_sel = set(sel)
        thumbs = render_thumbnails(self.pdf_path, rotations=self.rotations)
        self.panel.load(thumbs)
        for idx in old_sel:
            self.panel._toggle(idx)

    def _save(self):
        if not self.pdf_path:
            messagebox.showwarning("Rotate", "Open a PDF first.")
            return
        if not any(self.rotations.values()):
            messagebox.showwarning("Rotate", "No rotations applied.")
            return

        out = filedialog.asksaveasfilename(
            title="Save Rotated PDF", defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
            initialfile=f"{Path(self.pdf_path).stem}_rotated.pdf",
        )
        if not out:
            return
        try:
            reader = PdfReader(self.pdf_path)
            writer = PdfWriter()
            for i, page in enumerate(reader.pages):
                r = self.rotations.get(i, 0)
                if r:
                    page.rotate(r)
                writer.add_page(page)
            with open(out, "wb") as f:
                writer.write(f)
            count = sum(1 for v in self.rotations.values() if v)
            messagebox.showinfo("Rotate", f"Saved PDF with {count} rotated page(s).\n{out}")
        except Exception as e:
            messagebox.showerror("Rotate Error", str(e))


# ===================================================================
# SPLIT TAB
# ===================================================================

class SplitTab(tk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self.pdf_path = None
        self.page_count = 0

        # top bar
        top = tk.Frame(self)
        top.pack(fill="x", padx=10, pady=(10, 5))
        ttk.Button(top, text="Open PDF", command=self._open).pack(side="left")
        self.file_lbl = tk.Label(top, text="No file loaded", font=("Arial", 10))
        self.file_lbl.pack(side="left", padx=10)

        # left / right split
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=10, pady=5)

        # --- left: controls ---
        left = tk.Frame(paned)
        paned.add(left, weight=1)

        # split mode selection
        mode_frame = tk.LabelFrame(left, text="Split Mode", padx=10, pady=10)
        mode_frame.pack(fill="x", pady=(0, 5))

        self.mode = tk.StringVar(value="all")

        tk.Radiobutton(
            mode_frame, text="Split every page into a separate PDF",
            variable=self.mode, value="all", command=self._on_mode_change,
        ).pack(anchor="w")

        fixed_frame = tk.Frame(mode_frame)
        fixed_frame.pack(anchor="w", pady=(5, 0))
        tk.Radiobutton(
            fixed_frame, text="Split every",
            variable=self.mode, value="fixed", command=self._on_mode_change,
        ).pack(side="left")
        self.fixed_var = tk.StringVar(value="5")
        self.fixed_entry = tk.Entry(fixed_frame, textvariable=self.fixed_var, width=5)
        self.fixed_entry.pack(side="left", padx=3)
        tk.Label(fixed_frame, text="pages").pack(side="left")

        tk.Radiobutton(
            mode_frame, text="Split by custom page ranges:",
            variable=self.mode, value="ranges", command=self._on_mode_change,
        ).pack(anchor="w", pady=(5, 0))

        range_frame = tk.Frame(mode_frame)
        range_frame.pack(fill="x", pady=(2, 0))
        self.range_entry = tk.Entry(range_frame, font=("Arial", 10))
        self.range_entry.pack(side="left", fill="x", expand=True)
        self.range_hint = tk.Label(
            range_frame, text='e.g. "1-3, 4-6, 7-10"', font=("Arial", 9), fg="gray",
        )
        self.range_hint.pack(side="left", padx=(5, 0))

        # output preview list
        preview_frame = tk.LabelFrame(left, text="Output Preview", padx=10, pady=10)
        preview_frame.pack(fill="both", expand=True, pady=(5, 0))

        lf = tk.Frame(preview_frame)
        lf.pack(fill="both", expand=True)
        self.preview_listbox = tk.Listbox(lf, font=("Arial", 10))
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.preview_listbox.yview)
        self.preview_listbox.configure(yscrollcommand=sb.set)
        self.preview_listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        ttk.Button(preview_frame, text="Refresh Preview", command=self._refresh_preview).pack(pady=(5, 0))

        # --- right: page thumbnails ---
        right = tk.Frame(paned)
        paned.add(right, weight=1)

        tk.Label(right, text="Page Preview", font=("Arial", 10, "bold")).pack(anchor="w")
        self.panel = ThumbnailPanel(right, selectable=False)
        self.panel.pack(fill="both", expand=True)

        # bottom
        bot = tk.Frame(self)
        bot.pack(fill="x", padx=10, pady=(5, 10))
        ttk.Button(bot, text="Split & Save", command=self._split).pack(side="right")

    def _open(self):
        path = filedialog.askopenfilename(title="Open PDF", filetypes=[("PDF", "*.pdf")])
        if not path:
            return
        self.pdf_path = path
        self.page_count = len(PdfReader(path).pages)
        self.file_lbl.config(text=f"{Path(path).name} ({self.page_count} pages)")
        self.panel.load(render_thumbnails(path))
        self._refresh_preview()

    def _on_mode_change(self):
        self._refresh_preview()

    def _parse_ranges(self) -> list[tuple[int, int]] | None:
        """Parse the range entry text. Returns list of (start, end) 0-indexed tuples, or None on error."""
        text = self.range_entry.get().strip()
        if not text:
            return None
        ranges = []
        for part in text.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                tokens = part.split("-", 1)
                try:
                    a, b = int(tokens[0].strip()), int(tokens[1].strip())
                except ValueError:
                    return None
                if a < 1 or b < a or b > self.page_count:
                    return None
                ranges.append((a - 1, b - 1))  # convert to 0-indexed
            else:
                try:
                    p = int(part)
                except ValueError:
                    return None
                if p < 1 or p > self.page_count:
                    return None
                ranges.append((p - 1, p - 1))
        return ranges if ranges else None

    def _compute_chunks(self) -> list[tuple[int, int]] | None:
        """Return list of (start, end) 0-indexed inclusive page ranges for current mode."""
        if not self.pdf_path:
            return None
        mode = self.mode.get()
        if mode == "all":
            return [(i, i) for i in range(self.page_count)]
        elif mode == "fixed":
            try:
                n = int(self.fixed_var.get())
            except ValueError:
                return None
            if n < 1:
                return None
            chunks = []
            for start in range(0, self.page_count, n):
                end = min(start + n - 1, self.page_count - 1)
                chunks.append((start, end))
            return chunks
        elif mode == "ranges":
            return self._parse_ranges()
        return None

    def _refresh_preview(self):
        self.preview_listbox.delete(0, "end")
        if not self.pdf_path:
            return
        chunks = self._compute_chunks()
        if chunks is None:
            self.preview_listbox.insert("end", "  (invalid input)")
            return
        stem = Path(self.pdf_path).stem
        for i, (start, end) in enumerate(chunks, 1):
            npages = end - start + 1
            if start == end:
                desc = f"page {start + 1}"
            else:
                desc = f"pages {start + 1}-{end + 1}"
            self.preview_listbox.insert("end", f"  {stem}_part{i}.pdf  ({desc}, {npages} pg)")

    def _split(self):
        if not self.pdf_path:
            messagebox.showwarning("Split", "Open a PDF first.")
            return
        chunks = self._compute_chunks()
        if not chunks:
            messagebox.showwarning("Split", "Invalid split configuration.")
            return

        out_dir = filedialog.askdirectory(title="Select Output Folder")
        if not out_dir:
            return

        try:
            reader = PdfReader(self.pdf_path)
            stem = Path(self.pdf_path).stem
            for i, (start, end) in enumerate(chunks, 1):
                writer = PdfWriter()
                for p in range(start, end + 1):
                    writer.add_page(reader.pages[p])
                out_path = os.path.join(out_dir, f"{stem}_part{i}.pdf")
                with open(out_path, "wb") as f:
                    writer.write(f)
            messagebox.showinfo("Split", f"Created {len(chunks)} PDF file(s) in:\n{out_dir}")
        except Exception as e:
            messagebox.showerror("Split Error", str(e))


# ===================================================================
# MAIN APPLICATION
# ===================================================================

class PDFGearApp:

    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("PDF Gear")
        root.geometry("950x700")
        root.minsize(750, 500)

        # bring window to front on macOS
        if sys.platform == "darwin":
            root.lift()
            root.attributes("-topmost", True)
            root.after(100, lambda: root.attributes("-topmost", False))

        style = ttk.Style()
        style.configure("TButton", padding=5)
        style.configure("TNotebook.Tab", padding=[15, 5])

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        nb.add(MergeTab(nb), text="  Merge  ")
        nb.add(SplitTab(nb), text="  Split  ")
        nb.add(DeleteTab(nb), text="  Delete Pages  ")
        nb.add(ReorderTab(nb), text="  Reorder  ")
        nb.add(RotateTab(nb), text="  Rotate  ")


def main():
    root = tk.Tk()
    PDFGearApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
