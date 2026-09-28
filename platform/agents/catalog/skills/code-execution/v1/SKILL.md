---
schema_version: "1"
kind: skill
name: code-execution
version: v1
summary: "Run a short Python script in the sandbox over your workspace to read an attached PDF, Word, PowerPoint, spreadsheet, CSV or JSON file, compute over it, or produce a derived file."
roles:
  - head_of_abm
readiness_requirements: []
tools:
  - name: run_python
    version: "1"
    input_schema_sha256: c3c261b3cb0dbd182dbbd14921a2228b29fcd5e3a626a387a7d4eee50db334d4
    output_schema_sha256: f4fe91bacc68b4a45c7bcda24c72548481dc562b31312426db47f415b8a07c85
framework: deepagents
framework_version: ">=0.6,<0.7"
---
# Run a script to open a file your file tools cannot read

`run_python` runs one short Python script in a locked-down container over this turn's own
workspace. It is how you open a PDF, a Word file, a deck or a spreadsheet, how you compute a
number instead of eyeballing it, and how you produce a file the file tools cannot write.

Nothing in the platform turns an attached file into a summary for you. The file is the file. If
you have not opened it, you have not read it.

## 1. When to run code, when not to

Every file anyone has attached in this project sits at `attachments/<name>`, under the name the
person uploaded it with. The turn's message names each attachment, gives that path, and says
which tool opens it.

Open a text file with `read_file`: a `.md` or `.txt`, and a small `.csv` or `.json` — those two
arrive labelled as documents, but they are plain text and `read_file` reads them. Two things send
you to `run_python` instead: `read_file` refuses a file larger than 1,048,576 bytes with
`quota_exceeded`, and refuses anything that is not UTF-8 text with `permission_denied`
(enforced).

Run a script when:

- the file is a PDF, a Word file, a PowerPoint deck or an Excel workbook — bytes `read_file` has
  no way to decode
- the file is an image and you want its size, or you want to read the words in it
- the file is text but larger than `read_file` will serve
- you want a number computed rather than read: a total, a share, a count, a join across two files
- you want a table filtered, sorted or reshaped before you talk about it
- you want to produce a file: a CSV, a chart, a workbook, a document

Do not run a script to answer a question this conversation or a file you have already read
answers (asked of you). Do not run one to look at a text file you could open with `read_file`
(asked of you).

A turn gets a small number of runs — ten on a default deployment. Every result reports
`runs_remaining`; when it reaches zero the next call is refused `run_budget_exhausted` and the
rest of the work waits for the next turn (enforced). So write the whole script before you call:
one script that opens the file, computes what you need and prints it, rather than three that
each discover one thing.

A run is not a launch. It starts no research, spends no research budget, and changes nothing
outside the container and your own workspace.

The call takes three things. `code` is the whole script, as source; it runs with no arguments, so
anything it needs it reads from the workspace. `note` is one line saying what this run is for,
kept beside the code in the turn's record. `timeout_s` asks for *less* wall-clock time than the
operator allows, which is worth setting for a probe you expect to be instant; it cannot buy more
than the ceiling (enforced).

## 2. Where things are inside the container

The script's working directory is `/workspace`, and the folders in it are the same folders your
file tools use. A relative path means the same thing in a script as it does in `read_file`, so
`attachments/report.pdf` is the file the turn's message named.

| Path | In a script | What it holds |
| --- | --- | --- |
| `attachments/` | read | every file attached in this project, under its own filename |
| `project/` | read | this project's library, the same tree `read_file` serves |
| `brand/` | read | the brand library |
| `inputs/` | read | this turn's message and its refs |
| `context/` | read | the cards the turn composed |
| `reads/` | read | spilled output, including this tool's own spilled stdout |
| `scratch/` | read and write | your notebook, kept across the turns of this chat |
| `work/` | read and write | scratch inside this one turn |
| `outputs/` | read and write | the turn's durable product |

Four things about that container are worth knowing before you write a line:

- There is no network. Nothing downloads, and `pip install` fails (enforced).
- These libraries are installed and nothing else is: PyMuPDF (imported as `fitz`), `pypdf`,
  `pdfplumber`, `python-docx`, `python-pptx`, `openpyxl`, `pandas`, `matplotlib`, `Pillow`,
  `pytesseract` with tesseract itself (enforced).
- `.deepagent/` is not mounted, so a script cannot read your own profile, prompt or skills
  (enforced).
- When the run ends the platform re-applies the workspace's file policy to everything the script
  left behind. A file whose extension is outside `.json`, `.md`, `.txt`, `.yaml`, `.csv`,
  `.xlsx`, `.docx`, `.pptx`, `.pdf` and `.png` is deleted, and so is one over the per-file
  ceiling or one that pushes the workspace over its quota (enforced). The result's
  `files_written` lists what survived and `files_removed` says why anything went.

## 3. Reading recipes

Each of these prints. Printing is how you read: what the script prints comes back to you in
`stdout`, and nothing else does.

### A spreadsheet takes two passes

One pass gives you formulas, the other gives you the values those formulas last computed. No
single load gives you both.

```python
from openpyxl import load_workbook

formulas = load_workbook("attachments/model.xlsx", data_only=False)
print(formulas["Sheet1"]["B10"].value)   # '=SUM(B2:B9)'

values = load_workbook("attachments/model.xlsx", data_only=True)
print(values["Sheet1"]["B10"].value)     # 1234.5, or None
```

`data_only=True` reads the value Excel cached the last time the file was recalculated. A cell
that was never recalculated reads `None`. Report `None` as not computed in the file; do not read
it as zero (asked of you).

For the whole workbook as tables:

```python
import pandas as pd

sheets = pd.read_excel("attachments/accounts.xlsx", sheet_name=None)   # {name: DataFrame}
for name, frame in sheets.items():
    print(name, frame.shape, list(frame.columns))
    print(frame.head(20).to_string())
```

### A PDF, page by page

```python
import fitz   # PyMuPDF

doc = fitz.open("attachments/report.pdf")
print("pages:", doc.page_count)
for number, page in enumerate(doc, start=1):
    print(f"--- page {number} ---")
    print(page.get_text("text"))
```

Tables on a page come out of `page.find_tables()`, or out of pdfplumber when the layout is
awkward:

```python
import pdfplumber

with pdfplumber.open("attachments/report.pdf") as pdf:
    for number, page in enumerate(pdf.pages, start=1):
        for table in page.extract_tables():
            print(f"--- page {number} table ---")
            for row in table:
                print(row)
```

A page whose text comes back empty is a scan — an image of words, with no text layer. Render it
and read it with OCR:

```python
import fitz, pytesseract
from PIL import Image

page = fitz.open("attachments/scan.pdf")[0]
pixmap = page.get_pixmap(dpi=200)
image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
print(pytesseract.image_to_string(image))
```

OCR misreads characters, especially in numbers. Say that a figure came from a scanned page when
you quote one (asked of you).

### A Word document

```python
from docx import Document

doc = Document("attachments/brief.docx")
for paragraph in doc.paragraphs:
    if paragraph.text.strip():
        print(f"[{paragraph.style.name}] {paragraph.text}")
for index, table in enumerate(doc.tables, start=1):
    print(f"--- table {index} ---")
    for row in table.rows:
        print(" | ".join(cell.text for cell in row.cells))
```

The style name is what tells a heading from body text, which is how you recover the document's
structure. Headers and footers are `doc.sections[0].header` and `.footer`.

### A slide deck

```python
from pptx import Presentation

deck = Presentation("attachments/deck.pptx")
for number, slide in enumerate(deck.slides, start=1):
    print(f"--- slide {number} ---")
    for shape in slide.shapes:
        if shape.has_text_frame and shape.text_frame.text.strip():
            print(shape.text_frame.text)
    if slide.has_notes_slide:
        print("[notes]", slide.notes_slide.notes_text_frame.text)
```

The speaker notes often carry the argument the slide only gestures at, so read them.

### A CSV, a JSON file, an image

```python
import json
import pandas as pd
from PIL import Image

frame = pd.read_csv("attachments/accounts.csv")
print(frame.shape, list(frame.columns))
print(frame.head(20).to_string())

with open("attachments/export.json") as handle:
    payload = json.load(handle)
print(type(payload), len(payload))

image = Image.open("attachments/logo.png")
print(image.size, image.mode, image.format)
```

### Keep the output small enough to read

Anything past 16,384 bytes of `stdout` is written to a file instead of coming back inline, and
the result names it in `stdout_spilled_to`; open that path with `read_file` (enforced). Print a
shape, a head and the exact cells or pages you need rather than the whole file (asked of you).
When an extraction really is long, write it to `work/extract.txt` in the script and read it back
in pages with `read_file`. A separate flag, `stdout_truncated`, means the container itself cut the
stream before the tool saw the end of it — that output is gone, so print less and run again
rather than reasoning from half a page (asked of you).

## 4. What you may then say

- Every number, name and date you state comes from output you actually saw in a result, and you
  say where in the file it came from — the page, the sheet and cell, or the row (asked of you).
- An empty cell, a missing section and a page with no text are findings. Report them as they are
  rather than filling the gap (asked of you).
- When a run fails — a non-zero `exit_code`, or `timed_out` — read `stderr`, fix the script, and
  run again inside the budget (asked of you). A traceback usually names the wrong path or the
  wrong library, and both are one edit.
- When the tool refuses `sandbox_unavailable` or `workspace_unavailable`, tell the human you
  cannot open the file on this deployment right now, and name the file. Do not describe what is
  in a file you could not open (asked of you). A refusal costs no run.
- When the tool refuses `run_budget_exhausted`, say what you have read so far and what is left,
  and do the rest on the next turn (asked of you).
- Your script is capped at 65,536 characters. A script near that size is doing too much; split
  the work across runs instead (asked of you).

## 5. Producing a file

Write what you produce under `outputs/` when the human is meant to keep it, and under `work/`
when it is a step on the way. A script may write `.csv`, `.xlsx`, `.docx`, `.pptx`, `.pdf` and
`.png` as well as the `.json`, `.md`, `.txt` and `.yaml` your own `write_file` allows; anything
else is deleted when the run ends (enforced).

```python
import pandas as pd

frame = pd.read_csv("attachments/accounts.csv")
top = frame.sort_values("employees", ascending=False).head(25)
top.to_csv("outputs/top-accounts.csv", index=False)
print("wrote", len(top), "rows")
```

A chart is a `.png` written with matplotlib. The container has no screen, so build the figure,
save it, and close it rather than calling `show()`:

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

figure, axes = plt.subplots()
axes.barh(top["name"], top["employees"])   # `top` is the frame from the snippet above
figure.tight_layout()
figure.savefig("outputs/top-accounts.png", dpi=150)
plt.close(figure)
```

Check `files_written` in the result before you say a file exists, and say what you wrote and
where (asked of you). Writing a file is not showing it to anyone: nothing under `outputs/`
reaches the human during the turn — the folder is persisted as artifacts when the turn
finalizes — so describe what is in the file in your reply.
