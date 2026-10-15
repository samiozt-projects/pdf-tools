from __future__ import annotations

import io
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pymupdf
from PIL import Image, ImageOps
from tkinterdnd2 import DND_FILES, TkinterDnD
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


IMAGE_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
PDF_EXTENSIONS = {".pdf"}
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | PDF_EXTENSIONS


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
            title="Save merged PDF",
            initialdir=initial_dir,
            initialfile=Path(self.output_var.get()).name if self.output_var.get() else "merged.pdf",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
        )
        if path:
            self.output_var.set(path)

    def _create_pdf(self) -> None:
        if self.busy:
            return
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

        input_paths = {item.path.resolve() for item in self.files}
        if output in input_paths:
            messagebox.showerror("Invalid output path", "The output PDF must be different from the input files.")
            return

        self.busy = True
        self.create_button.configure(state="disabled")
        self.status_var.set("Creating PDF...")
        threading.Thread(target=self._create_pdf_worker, args=(output,), daemon=True).start()

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


def main() -> None:
    root = TkinterDnD.Tk()
    PdfToolApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
