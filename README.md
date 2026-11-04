# PDF Tool

A small Windows desktop tool for creating one PDF from a mix of PDF and image files.

## Features

- Drag and drop PDF and image files into the window.
- Add files with the file picker.
- Reorder, remove, or clear inputs.
- Convert images to PDF pages automatically.
- Preserve all pages from input PDFs.
- Save the result wherever you choose.
- Avoid overwriting an existing output by using names such as `merged (1).pdf`.
- Detect a card or ID in one or two PDF/image files and place both sides on one page at standard card size.

Supported image types: JPG, JPEG, PNG, TIFF, BMP, GIF, and WEBP.

## Run

Install the dependencies once:

```powershell
python -m pip install -r requirements.txt
```

Start the app:

```powershell
python app.py
```

Use the `Create card PDF` button for card mode. It checks that the selected files contain at most two total pages, so it accepts one two-page PDF, one image, or two separate PDF/image files. The result is an A4 PDF page with the detected sides stacked vertically near the top left at approximately 85.6 x 54 mm each.

