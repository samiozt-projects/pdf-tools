from __future__ import annotations

import io
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np
import pymupdf
from PIL import Image, ImageOps
from tkinterdnd2 import DND_FILES, TkinterDnD
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


IMAGE_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
PDF_EXTENSIONS = {".pdf"}
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | PDF_EXTENSIONS
CARD_WIDTH_PT = 85.60 / 25.4 * 72
CARD_HEIGHT_PT = 53.98 / 25.4 * 72


@dataclass
class InputFile:
    path: Path
    kind: str
    pages: int | str


class PdfToolApp:
    def __init__(self, root: TkinterDnD.Tk) -> None:
        self.root = root
        self.root.title("PDF Tool")
        self.root.geometry("900x650")
        self.root.minsize(760, 520)

        self.files: list[InputFile] = []
        self.busy = False
        self.output_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Drop images or PDF files here to get started.")
        self.last_default_output_name = "merged.pdf"

        self._configure_style()
        self._build_ui()

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("Subtitle.TLabel", foreground="#5c6670")
        style.configure("Drop.TFrame", background="#eef5ff")
        style.configure("Drop.TLabel", background="#eef5ff", foreground="#1d5fa7", font=("Segoe UI", 13, "bold"))
        style.configure("Status.TLabel", foreground="#5c6670")

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=20)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="PDF Tool", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Merge PDFs and images into one PDF. Files are processed in the order shown below.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(3, 16))

        self.drop_frame = ttk.Frame(outer, style="Drop.TFrame", padding=22)
        self.drop_frame.pack(fill="x", pady=(0, 15))
        self.drop_label = ttk.Label(
            self.drop_frame,
            text="Drag and drop PDF or image files here",
            style="Drop.TLabel",
            anchor="center",
        )
        self.drop_label.pack(fill="x")
        ttk.Label(
            self.drop_frame,
            text="Supported images: JPG, PNG, TIFF, BMP, GIF and WEBP",
            style="Subtitle.TLabel",
            anchor="center",
        ).pack(fill="x", pady=(7, 0))
        for widget in (self.drop_frame, self.drop_label):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)

        list_frame = ttk.Frame(outer)
        list_frame.pack(fill="both", expand=True)

        columns = ("order", "name", "type", "pages")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("order", text="#")
        self.tree.heading("name", text="File")
        self.tree.heading("type", text="Type")
        self.tree.heading("pages", text="Pages")
        self.tree.column("order", width=48, anchor="center", stretch=False)
        self.tree.column("name", width=480, anchor="w")
        self.tree.column("type", width=95, anchor="center", stretch=False)
        self.tree.column("pages", width=75, anchor="center", stretch=False)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        button_row = ttk.Frame(outer)
        button_row.pack(fill="x", pady=(12, 16))
        ttk.Button(button_row, text="Add files", command=self._choose_files).pack(side="left")
        ttk.Button(button_row, text="Remove selected", command=self._remove_selected).pack(side="left", padx=(8, 0))
        ttk.Button(button_row, text="Clear", command=self._clear_files).pack(side="left", padx=(8, 0))
        self.create_card_button = ttk.Button(button_row, text="Create card PDF", command=self._create_card_pdf)
        self.create_card_button.pack(side="left", padx=(18, 0))
        ttk.Button(button_row, text="Move up", command=lambda: self._move_selected(-1)).pack(side="right")
        ttk.Button(button_row, text="Move down", command=lambda: self._move_selected(1)).pack(side="right", padx=(8, 0))

        output_row = ttk.Frame(outer)
        output_row.pack(fill="x")
        ttk.Label(output_row, text="Output PDF:").pack(side="left")
        ttk.Entry(output_row, textvariable=self.output_var).pack(side="left", fill="x", expand=True, padx=(10, 8))
        ttk.Button(output_row, text="Browse...", command=self._choose_output).pack(side="left")
        self.create_button = ttk.Button(output_row, text="Create PDF", command=self._create_pdf)
        self.create_button.pack(side="left", padx=(12, 0))

        ttk.Label(outer, textvariable=self.status_var, style="Status.TLabel").pack(anchor="w", pady=(12, 0))

    def _prepare_output_mode(self, default_name: str) -> None:
        current = self.output_var.get().strip()
        if current and Path(current).name.lower() == self.last_default_output_name.lower():
            self.output_var.set(str(Path(current).with_name(default_name)))
        self.last_default_output_name = default_name

    def _on_drop(self, event: tk.Event) -> None:
        self._add_paths(self.root.tk.splitlist(event.data))

    def _choose_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Choose PDF or image files",
            filetypes=[
                ("PDF and images", " ".join(f"*{suffix}" for suffix in sorted(SUPPORTED_EXTENSIONS))),
                ("PDF files", "*.pdf"),
                ("Image files", "*.jpg *.jpeg *.png *.tif *.tiff *.bmp *.gif *.webp"),
                ("All files", "*.*"),
            ],
        )
        self._add_paths(paths)

    def _add_paths(self, raw_paths: Iterable[str]) -> None:
        added = 0
        skipped = 0
        for raw_path in raw_paths:
            path = Path(raw_path).expanduser()
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                skipped += 1
                continue
            if any(existing.path.resolve() == path.resolve() for existing in self.files):
                skipped += 1
                continue

            kind = "PDF" if path.suffix.lower() in PDF_EXTENSIONS else "Image"
            pages: int | str = "1"
            if kind == "PDF":
                try:
                    with pymupdf.open(path) as document:
                        pages = document.page_count
                except Exception:
                    pages = "?"
            self.files.append(InputFile(path=path, kind=kind, pages=pages))
            added += 1

        self._refresh_tree()
        if self.files and not self.output_var.get():
            self.output_var.set(str(self.files[0].path.with_name("merged.pdf")))

        if added and skipped:
            self.status_var.set(f"Added {added} file(s); skipped {skipped} unsupported or duplicate file(s).")
        elif added:
            self.status_var.set(f"Added {added} file(s). Reorder them if needed, then choose Create PDF.")
        elif skipped:
            self.status_var.set("No new supported files were added.")

    def _refresh_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for index, item in enumerate(self.files, start=1):
            self.tree.insert("", "end", iid=str(index - 1), values=(index, item.path.name, item.kind, item.pages))

    def _remove_selected(self) -> None:
        selected = sorted((int(item) for item in self.tree.selection()), reverse=True)
        for index in selected:
            del self.files[index]
        self._refresh_tree()
        if selected:
            self.status_var.set(f"Removed {len(selected)} file(s).")

    def _clear_files(self) -> None:
        if not self.files:
            return
        self.files.clear()
        self._refresh_tree()
        self.status_var.set("Input list cleared.")

    def _move_selected(self, direction: int) -> None:
        selected = self.tree.selection()
        if len(selected) != 1:
            self.status_var.set("Select one file to move it.")
            return
        index = int(selected[0])
        new_index = index + direction
        if not 0 <= new_index < len(self.files):
            return
        self.files[index], self.files[new_index] = self.files[new_index], self.files[index]
        self._refresh_tree()
        self.tree.selection_set(str(new_index))
        self.tree.focus(str(new_index))

    def _choose_output(self) -> None:
        initial_dir = str(Path(self.output_var.get()).parent) if self.output_var.get() else None
        path = filedialog.asksaveasfilename(
            title="Save PDF",
            initialdir=initial_dir,
            initialfile=Path(self.output_var.get()).name if self.output_var.get() else self.last_default_output_name,
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
        )
        if path:
            self.output_var.set(path)

    def _create_pdf(self) -> None:
        if self.busy:
            return
        self._prepare_output_mode("merged.pdf")
        if not self.files:
            messagebox.showinfo("No input files", "Add at least one PDF or image file first.")
            return

        output = Path(self.output_var.get().strip()).expanduser()
        if not output.name:
            messagebox.showerror("Output file missing", "Choose a name for the output PDF.")
            return
        if output.suffix.lower() != ".pdf":
            output = output.with_suffix(".pdf")
            self.output_var.set(str(output))

        try:
            output = output.resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            messagebox.showerror("Invalid output path", str(error))
            return

        requested_output = output
        output = self._next_available_output(output)
        if output != requested_output:
            self.status_var.set(f"{requested_output.name} already exists; using {output.name}.")

        input_paths = {item.path.resolve() for item in self.files}
        if output in input_paths:
            messagebox.showerror("Invalid output path", "The output PDF must be different from the input files.")
            return

        self.busy = True
        self.create_button.configure(state="disabled")
        self.create_card_button.configure(state="disabled")
        self.status_var.set("Creating PDF...")
        threading.Thread(target=self._create_pdf_worker, args=(output,), daemon=True).start()

    @staticmethod
    def _next_available_output(output: Path) -> Path:
        """Return output, or the next numbered filename when output already exists."""
        if not output.exists():
            return output

        suffix = output.suffix or ".pdf"
        stem = output.stem
        counter = 1
        while True:
            candidate = output.with_name(f"{stem} ({counter}){suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    def _create_pdf_worker(self, output: Path) -> None:
        temp_path: Path | None = None
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix="pdf-tool-", suffix=".pdf", dir=output.parent, delete=False) as handle:
                temp_path = Path(handle.name)

            merged = pymupdf.open()
            try:
                for item in self.files:
                    if item.kind == "PDF":
                        with pymupdf.open(item.path) as source:
                            merged.insert_pdf(source)
                    else:
                        self._append_image(merged, item.path)
                merged.save(temp_path, garbage=4, deflate=True)
            finally:
                merged.close()

            os.replace(temp_path, output)
            temp_path = None
            self.root.after(0, self._creation_finished, output, None)
        except Exception as error:
            if temp_path:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            self.root.after(0, self._creation_finished, output, error)

    @staticmethod
    def _append_image(document: pymupdf.Document, path: Path) -> None:
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source)
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            image_bytes = io.BytesIO()
            image.save(image_bytes, format="PNG", optimize=True)
            width, height = image.size

        if width >= height:
            page_width, page_height = 842, 595
        else:
            page_width, page_height = 595, 842
        margin = 24
        scale = min((page_width - margin * 2) / width, (page_height - margin * 2) / height)
        displayed_width = width * scale
        displayed_height = height * scale
        left = (page_width - displayed_width) / 2
        top = (page_height - displayed_height) / 2
        page = document.new_page(width=page_width, height=page_height)
        page.insert_image(pymupdf.Rect(left, top, left + displayed_width, top + displayed_height), stream=image_bytes.getvalue())

    def _creation_finished(self, output: Path, error: Exception | None) -> None:
        self.busy = False
        self.create_button.configure(state="normal")
        self.create_card_button.configure(state="normal")
        if error:
            self.status_var.set("PDF creation failed.")
            messagebox.showerror("Could not create PDF", str(error))
        else:
            self.status_var.set(f"Created {output.name} with {self._total_page_count()} page(s).")
            messagebox.showinfo("PDF created", f"Saved PDF to:\n{output}")

    def _total_page_count(self) -> int:
        total = 0
        for item in self.files:
            if isinstance(item.pages, int):
                total += item.pages
            else:
                total += 1
        return total

    def _card_page_count(self) -> int:
        total = 0
        for item in self.files:
            if item.kind == "PDF":
                with pymupdf.open(item.path) as document:
                    total += document.page_count
            else:
                total += 1
        return total

    def _create_card_pdf(self) -> None:
        if self.busy:
            return
        self._prepare_output_mode("card.pdf")
        if not self.files:
            messagebox.showinfo("No card files", "Add one or two PDF/image files first.")
            return

        try:
            page_count = self._card_page_count()
        except Exception as error:
            messagebox.showerror("Could not read card files", str(error))
            return
        if page_count > 2:
            messagebox.showerror(
                "Too many pages",
                f"Card mode accepts a maximum of 2 pages, but {page_count} pages are selected.",
            )
            return
        if page_count == 0:
            messagebox.showerror("No card pages", "The selected files do not contain a readable page.")
            return

        output = Path(self.output_var.get().strip()).expanduser()
        if not output.name:
            messagebox.showerror("Output file missing", "Choose a name for the output PDF.")
            return
        if output.suffix.lower() != ".pdf":
            output = output.with_suffix(".pdf")
            self.output_var.set(str(output))
        try:
            output = output.resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            messagebox.showerror("Invalid output path", str(error))
            return

        requested_output = output
        output = self._next_available_output(output)
        if output != requested_output:
            self.status_var.set(f"{requested_output.name} already exists; using {output.name}.")

        input_paths = {item.path.resolve() for item in self.files}
        if output in input_paths:
            messagebox.showerror("Invalid output path", "The output PDF must be different from the input files.")
            return

        self.busy = True
        self.create_button.configure(state="disabled")
        self.create_card_button.configure(state="disabled")
        self.status_var.set("Detecting card sides and creating PDF...")
        sources = [item.path for item in self.files]
        threading.Thread(target=self._create_card_pdf_worker, args=(sources, output), daemon=True).start()

    def _create_card_pdf_worker(self, sources: list[Path], output: Path) -> None:
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(prefix="card-pdf-tool-", suffix=".pdf", dir=output.parent, delete=False) as handle:
                temp_path = Path(handle.name)

            sides = CardPdfWindow._extract_sides(sources)
            if not sides:
                raise ValueError("No readable card side was found.")
            if len(sides) > 2:
                raise ValueError("Card mode supports a maximum of two pages.")

            document = pymupdf.open()
            try:
                page = document.new_page(width=595, height=842)
                left = 36
                first_top = 36
                gap = 24
                for index, side in enumerate(sides):
                    card = CardPdfWindow._detect_and_crop_card(side)
                    image_bytes = io.BytesIO()
                    card.save(image_bytes, format="PNG", optimize=True)
                    top = first_top + index * (CARD_HEIGHT_PT + gap)
                    page.insert_image(
                        pymupdf.Rect(left, top, left + CARD_WIDTH_PT, top + CARD_HEIGHT_PT),
                        stream=image_bytes.getvalue(),
                    )
                document.save(temp_path, garbage=4, deflate=True)
            finally:
                document.close()

            os.replace(temp_path, output)
            temp_path = None
            self.root.after(0, self._card_creation_finished, output, None, len(sides))
        except Exception as error:
            if temp_path:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            self.root.after(0, self._card_creation_finished, output, error, 0)

    def _card_creation_finished(self, output: Path, error: Exception | None, side_count: int) -> None:
        self.busy = False
        self.create_button.configure(state="normal")
        self.create_card_button.configure(state="normal")
        if error:
            self.status_var.set("Card PDF creation failed.")
            messagebox.showerror("Could not create card PDF", str(error))
        else:
            self.status_var.set(f"Created {output.name} with {side_count} normalized side(s).")
            messagebox.showinfo("Card PDF created", f"Saved PDF to:\n{output}")


class CardPdfWindow:
    """Create one PDF page containing one or two normalized card sides."""

    def __init__(self, parent: tk.Misc) -> None:
        self.window = tk.Toplevel(parent)
        self.window.title("Card / ID page")
        self.window.geometry("760x570")
        self.window.minsize(650, 470)
        self.window.transient(parent)

        self.sources: list[Path] = []
        self.busy = False
        self.output_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(
            value="Drop one two-page PDF, one image, or two PDF/image files here."
        )

        self._build_ui()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.window, padding=20)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Card / ID page", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="The card is detected, cropped, corrected, and placed at standard card size.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(3, 16))

        drop_frame = ttk.Frame(outer, style="Drop.TFrame", padding=20)
        drop_frame.pack(fill="x", pady=(0, 14))
        drop_label = ttk.Label(
            drop_frame,
            text="Drag and drop up to two card files here",
            style="Drop.TLabel",
            anchor="center",
        )
        drop_label.pack(fill="x")
        ttk.Label(
            drop_frame,
            text="One two-page PDF is also supported. The sides will be stacked on one A4 page.",
            style="Subtitle.TLabel",
            anchor="center",
        ).pack(fill="x", pady=(7, 0))
        for widget in (drop_frame, drop_label):
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)

        list_frame = ttk.Frame(outer)
        list_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(list_frame, columns=("side", "name", "type"), show="headings")
        self.tree.heading("side", text="Side")
        self.tree.heading("name", text="File")
        self.tree.heading("type", text="Type")
        self.tree.column("side", width=70, anchor="center", stretch=False)
        self.tree.column("name", width=460, anchor="w")
        self.tree.column("type", width=100, anchor="center", stretch=False)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        button_row = ttk.Frame(outer)
        button_row.pack(fill="x", pady=(12, 16))
        ttk.Button(button_row, text="Add files", command=self._choose_files).pack(side="left")
        ttk.Button(button_row, text="Remove selected", command=self._remove_selected).pack(side="left", padx=(8, 0))
        ttk.Button(button_row, text="Clear", command=self._clear_files).pack(side="left", padx=(8, 0))

        output_row = ttk.Frame(outer)
        output_row.pack(fill="x")
        ttk.Label(output_row, text="Output PDF:").pack(side="left")
        ttk.Entry(output_row, textvariable=self.output_var).pack(side="left", fill="x", expand=True, padx=(10, 8))
        ttk.Button(output_row, text="Browse...", command=self._choose_output).pack(side="left")
        self.create_button = ttk.Button(output_row, text="Create card PDF", command=self._create_pdf)
        self.create_button.pack(side="left", padx=(12, 0))
        ttk.Label(outer, textvariable=self.status_var, style="Status.TLabel").pack(anchor="w", pady=(12, 0))

    def _on_drop(self, event: tk.Event) -> None:
        self._add_paths(self.window.tk.splitlist(event.data))

    def _choose_files(self) -> None:
        paths = filedialog.askopenfilenames(
            parent=self.window,
            title="Choose card files",
            filetypes=[
                ("PDF and images", " ".join(f"*{suffix}" for suffix in sorted(SUPPORTED_EXTENSIONS))),
                ("PDF files", "*.pdf"),
                ("Image files", "*.jpg *.jpeg *.png *.tif *.tiff *.bmp *.gif *.webp"),
            ],
        )
        self._add_paths(paths)

    def _add_paths(self, raw_paths: Iterable[str]) -> None:
        added = 0
        for raw_path in raw_paths:
            if len(self.sources) >= 2:
                break
            path = Path(raw_path).expanduser()
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            if any(existing.resolve() == path.resolve() for existing in self.sources):
                continue
            self.sources.append(path)
            added += 1

        self._refresh_tree()
        if self.sources and not self.output_var.get():
            self.output_var.set(str(self.sources[0].with_name("card.pdf")))
        if added:
            self.status_var.set(f"Added {added} card file(s).")
        elif len(self.sources) >= 2:
            self.status_var.set("Two card files are already selected.")

    def _refresh_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for index, path in enumerate(self.sources):
            kind = "PDF" if path.suffix.lower() in PDF_EXTENSIONS else "Image"
            side = "Front" if index == 0 else "Back"
            self.tree.insert("", "end", iid=str(index), values=(side, path.name, kind))

    def _remove_selected(self) -> None:
        selected = sorted((int(item) for item in self.tree.selection()), reverse=True)
        for index in selected:
            del self.sources[index]
        self._refresh_tree()
        if selected:
            self.status_var.set("Removed selected card file(s).")

    def _clear_files(self) -> None:
        self.sources.clear()
        self._refresh_tree()
        self.status_var.set("Card file list cleared.")

    def _choose_output(self) -> None:
        initial_dir = str(Path(self.output_var.get()).parent) if self.output_var.get() else None
        path = filedialog.asksaveasfilename(
            parent=self.window,
            title="Save card PDF",
            initialdir=initial_dir,
            initialfile=Path(self.output_var.get()).name if self.output_var.get() else "card.pdf",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
        )
        if path:
            self.output_var.set(path)

    def _create_pdf(self) -> None:
        if self.busy:
            return
        if not self.sources:
            messagebox.showinfo("No card files", "Add one or two PDF/image files first.", parent=self.window)
            return

        output = Path(self.output_var.get().strip()).expanduser()
        if not output.name:
            messagebox.showerror("Output file missing", "Choose a name for the output PDF.", parent=self.window)
            return
        if output.suffix.lower() != ".pdf":
            output = output.with_suffix(".pdf")
            self.output_var.set(str(output))
        try:
            output = output.resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            messagebox.showerror("Invalid output path", str(error), parent=self.window)
            return

        requested_output = output
        output = PdfToolApp._next_available_output(output)
        if output != requested_output:
            self.output_var.set(str(output))
            self.status_var.set(f"{requested_output.name} already exists; using {output.name}.")

        self.busy = True
        self.create_button.configure(state="disabled")
        self.status_var.set("Detecting card sides and creating PDF...")
        sources = list(self.sources)
        threading.Thread(target=self._create_pdf_worker, args=(sources, output), daemon=True).start()

    def _create_pdf_worker(self, sources: list[Path], output: Path) -> None:
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(prefix="card-pdf-tool-", suffix=".pdf", dir=output.parent, delete=False) as handle:
                temp_path = Path(handle.name)

            sides = self._extract_sides(sources)
            if not sides:
                raise ValueError("No readable card side was found.")
            if len(sides) > 2:
                raise ValueError("The card workflow supports a maximum of two sides.")

            document = pymupdf.open()
            try:
                page_width, page_height = 595, 842
                page = document.new_page(width=page_width, height=page_height)
                gap = 24
                first_top = 36
                left = 36
                for index, side in enumerate(sides):
                    card = self._detect_and_crop_card(side)
                    image_bytes = io.BytesIO()
                    card.save(image_bytes, format="PNG", optimize=True)
                    top = first_top + index * (CARD_HEIGHT_PT + gap)
                    page.insert_image(
                        pymupdf.Rect(left, top, left + CARD_WIDTH_PT, top + CARD_HEIGHT_PT),
                        stream=image_bytes.getvalue(),
                    )
                document.save(temp_path, garbage=4, deflate=True)
            finally:
                document.close()

            os.replace(temp_path, output)
            temp_path = None
            self.window.after(0, self._finished, output, None)
        except Exception as error:
            if temp_path:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            self.window.after(0, self._finished, output, error)

    @staticmethod
    def _extract_sides(sources: list[Path]) -> list[Image.Image]:
        sides: list[Image.Image] = []
        for path in sources:
            if path.suffix.lower() in PDF_EXTENSIONS:
                with pymupdf.open(path) as document:
                    page_indexes = range(min(2, document.page_count)) if len(sources) == 1 else range(min(1, document.page_count))
                    for page_index in page_indexes:
                        pixmap = document[page_index].get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                        image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
                        sides.append(image)
            else:
                with Image.open(path) as source:
                    sides.append(ImageOps.exif_transpose(source).convert("RGB").copy())
            if len(sides) >= 2:
                break
        return sides[:2]

    @classmethod
    def _detect_and_crop_card(cls, image: Image.Image) -> Image.Image:
        rgb = np.asarray(image.convert("RGB"))
        original_height, original_width = rgb.shape[:2]
        scale = min(1.0, 1800 / max(original_width, original_height))
        if scale < 1:
            small = cv2.resize(rgb, (round(original_width * scale), round(original_height * scale)), interpolation=cv2.INTER_AREA)
        else:
            small = rgb

        gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edge_map = cv2.Canny(blurred, 40, 140)
        soft_edge_map = cv2.Canny(blurred, 15, 35)
        soft_edge_map = cv2.morphologyEx(
            soft_edge_map,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15)),
        )
        threshold_map = cv2.threshold(blurred, 245, 255, cv2.THRESH_BINARY_INV)[1]
        adaptive_map = cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 7
        )
        contours: list[np.ndarray] = []
        for mask in (edge_map, soft_edge_map, threshold_map, adaptive_map):
            found, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            contours.extend(found)

        image_area = small.shape[0] * small.shape[1]
        best_quad: np.ndarray | None = None
        best_score = 0.0
        for contour in contours:
            contour_area = cv2.contourArea(contour)
            if contour_area == 0:
                continue
            rectangle = cv2.minAreaRect(contour)
            rectangle_width, rectangle_height = rectangle[1]
            rectangle_area = rectangle_width * rectangle_height
            if rectangle_area == 0:
                continue
            rectangle_ratio = rectangle_area / image_area
            if rectangle_ratio < 0.05 or rectangle_ratio > 0.75:
                continue
            points = cv2.boxPoints(rectangle).astype(np.float32)
            bounds_left = points[:, 0].min()
            bounds_top = points[:, 1].min()
            bounds_right = points[:, 0].max()
            bounds_bottom = points[:, 1].max()
            edge_margin = min(small.shape[:2]) * 0.015
            if rectangle_ratio > 0.35 and (
                bounds_left <= edge_margin
                or bounds_top <= edge_margin
                or bounds_right >= small.shape[1] - edge_margin
                or bounds_bottom >= small.shape[0] - edge_margin
            ):
                continue
            fill_ratio = contour_area / rectangle_area
            if fill_ratio < 0.30:
                continue
            aspect = max(rectangle_width, rectangle_height) / min(rectangle_width, rectangle_height)
            if not 1.15 <= aspect <= 2.35:
                continue
            aspect_score = max(0.0, 1.0 - abs(aspect - 1.586) / 1.586)
            score = (aspect_score**3) * (rectangle_ratio**0.7) * min(1.0, fill_ratio)
            if score > best_score:
                best_score = score
                best_quad = points

        if best_quad is None:
            return cls._fallback_crop(Image.fromarray(rgb))

        ordered = cls._order_points(best_quad / scale)
        top_left, top_right, bottom_right, bottom_left = ordered
        width = int(max(np.linalg.norm(bottom_right - bottom_left), np.linalg.norm(top_right - top_left)))
        height = int(max(np.linalg.norm(top_right - bottom_right), np.linalg.norm(top_left - bottom_left)))
        width = max(width, 100)
        height = max(height, 60)
        destination = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32)
        transform = cv2.getPerspectiveTransform(ordered.astype(np.float32), destination)
        warped = cv2.warpPerspective(rgb, transform, (width, height))
        if warped.shape[0] > warped.shape[1]:
            warped = cv2.rotate(warped, cv2.ROTATE_90_CLOCKWISE)
        return Image.fromarray(warped)

    @staticmethod
    def _order_points(points: np.ndarray) -> np.ndarray:
        ordered = np.zeros((4, 2), dtype=np.float32)
        sums = points.sum(axis=1)
        differences = np.diff(points, axis=1).reshape(-1)
        ordered[0] = points[np.argmin(sums)]
        ordered[2] = points[np.argmax(sums)]
        ordered[1] = points[np.argmin(differences)]
        ordered[3] = points[np.argmax(differences)]
        return ordered

    @staticmethod
    def _fallback_crop(image: Image.Image) -> Image.Image:
        rgb = np.asarray(image.convert("RGB"))
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        mask = cv2.threshold(gray, 245, 255, cv2.THRESH_BINARY_INV)[1]
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        image_area = rgb.shape[0] * rgb.shape[1]
        candidates = []
        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            area = width * height
            aspect = max(width, height) / max(1, min(width, height))
            if image_area * 0.05 <= area <= image_area * 0.75 and 1.15 <= aspect <= 2.35:
                if x > rgb.shape[1] * 0.015 and y > rgb.shape[0] * 0.015:
                    candidates.append((area, x, y, width, height))
        if not candidates:
            return image.convert("RGB")
        _, x, y, width, height = max(candidates)
        return image.convert("RGB").crop((x, y, x + width, y + height))

    def _finished(self, output: Path, error: Exception | None) -> None:
        self.busy = False
        self.create_button.configure(state="normal")
        if error:
            self.status_var.set("Card PDF creation failed.")
            messagebox.showerror("Could not create card PDF", str(error), parent=self.window)
        else:
            self.status_var.set(f"Created {output.name} with normalized card side(s).")
            messagebox.showinfo("Card PDF created", f"Saved PDF to:\n{output}", parent=self.window)


def main() -> None:
    root = TkinterDnD.Tk()
    PdfToolApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
