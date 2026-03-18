# PDF Gear

A standalone Python desktop application for manipulating PDF files with a user-friendly GUI.

## Features

- **Merge**: Combine multiple PDF files into a single document
- **Delete Pages**: Remove unwanted pages from a PDF
- **Reorder**: Rearrange pages with intuitive move up/down/top/bottom controls
- **Rotate**: Rotate pages by 90°, 180°, or 270 degrees

## Requirements

- Python 3.10+
- uv (package manager)

## Installation

Clone the repository and install dependencies using uv:

```bash
git clone https://github.com/cloudaipro/pdf-gear.git
cd pdf-gear
uv sync
```

## Running the Application

```bash
uv run pdf-gear
```

Or alternatively:

```bash
uv run python -m pdf_gear
```

## Usage

### Merge Tab
1. Click **Add Files** to select multiple PDF files
2. Use **Move Up/Down** to arrange the order
3. Click **Merge & Save** to combine them into one PDF

### Delete Pages Tab
1. Click **Open PDF** to select a file
2. Click on page thumbnails to select pages (multi-select enabled)
3. Use **Select All** / **Deselect All** for quick selection
4. Click **Delete Selected & Save** to create the modified PDF

### Reorder Tab
1. Click **Open PDF** to select a file
2. Select a page in the list to see its preview
3. Use the buttons to rearrange:
   - **Move Up/Down**: Adjacent pages
   - **Move to Top/Bottom**: Specific pages
   - **Reverse All**: Flip the entire page order
4. Click **Save Reordered PDF** when done

### Rotate Tab
1. Click **Open PDF** to select a file
2. Click on page thumbnails to select pages (multi-select enabled)
3. Click a rotation button (**90° CW**, **90° CCW**, **180°**)
4. Watch the thumbnails update in real-time
5. Click **Save Rotated PDF** to save

## Dependencies

- `pypdf` - PDF manipulation
- `pymupdf` - PDF rendering and thumbnails
- `pillow` - Image handling
- `tkinter` - GUI (built-in with Python)

## Project Structure

```
pdf-gear/
├── README.md
├── pyproject.toml
└── pdf_gear/
    ├── __init__.py
    ├── __main__.py
    └── app.py
```

## License

MIT
