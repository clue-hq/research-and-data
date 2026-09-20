# `clue-agent-sandbox` — the image the agent's Python runs in

The Head-of-ABM agent's `run_python@1` tool does not run scripts on the serving host. Every call
starts one throwaway container from this image, hands it the script on stdin, and throws the
container away when the script is done. This directory is that image.

Spec: `docs/superpowers/specs/2026-09-19-agent-code-execution-and-document-attachments-design.md`
§3.4. The container flags (no network, read-only root, unprivileged user, cpu/memory/pids ceilings)
live in `platform/api/clue_api/sandbox/docker_runner.py`, not here — this file is only the
filesystem the script gets to stand on.

## Build it

```bash
make sandbox-image
```

That is `docker build -t $CLUE_SANDBOX_IMAGE docker/agent-sandbox`, defaulting the tag to
`clue-agent-sandbox:latest`. If you point `CLUE_SANDBOX_IMAGE` at a different tag, build with the
same variable set, so the image the runner looks for is the image you built. A cold build is a
couple of minutes (apt plus a large wheel set) and there is nothing incremental about it, so
rebuild whenever this Dockerfile changes.

Size of the image built here (arm64, macOS Docker Desktop): **612 MB** —
`docker image inspect clue-agent-sandbox:latest --format '{{.Size}}'` → `611816512`. A cold build
took about 95 seconds on that host.

## The switch

`CLUE_SANDBOX_ENABLED` is `true` by default (founder ruling 2026-09-20); set it `false` to turn the tool off. The other
`CLUE_SANDBOX_*` settings — image tag, timeout, cpus, memory, runs per turn, output cap — are the
per-run ceilings, and are documented next to their defaults in `.env.example`.

Enabling the flag is not enough on its own: the image has to exist on the box that runs the
turns. When it does not, `run_python@1` refuses with `sandbox_unavailable` and the message names
the fix — *"The sandbox image `clue-agent-sandbox:latest` is not built on this host; run `make
sandbox-image`."* The refusal is loud rather than silent because of what it costs: **without the
image, a binary attachment is unreadable to the agent.** A PDF, a .docx, a .xlsx, an image — the
agent has no other way to open one. It can see that the file is there and it cannot look inside.

## What is in it, and why

Base: `python:3.12-slim`.

apt:

| package | why |
| --- | --- |
| `tesseract-ocr` | the OCR engine `pytesseract` shells out to — a scanned PDF or a screenshot is unreadable without it |
| `libglib2.0-0` | shared library the imaging/PDF wheels load at import time |

pip (pinned to a series, not a patch, so a rebuild picks up fixes without moving a major):

| package | why |
| --- | --- |
| `pymupdf` (`fitz`) | fast PDF text and image extraction; the default PDF reader |
| `pypdf` | PDF page/metadata work and the fallback when PyMuPDF dislikes a file |
| `pdfplumber` | table and layout extraction from PDFs, which the other two do not do well |
| `python-docx` | Word documents |
| `python-pptx` | PowerPoint decks |
| `openpyxl` | Excel workbooks (and the engine pandas uses for `.xlsx`) |
| `pandas` | CSV/Excel analysis — the actual point of most spreadsheet attachments |
| `matplotlib` | charts written into the run's scratch folder |
| `pillow` | image decoding, for both image attachments and OCR pre-processing |
| `pytesseract` | the Python binding onto `tesseract-ocr` |

Two environment variables are baked in, and the runner sets the same two on every run so the
behaviour does not depend on the image alone:

- `PYTHONDONTWRITEBYTECODE=1` — the root filesystem is read-only; nothing should try to write
  `__pycache__`.
- `MPLCONFIGDIR=/tmp` — matplotlib wants a cache directory on import. `/tmp` is the container's
  only writable non-mount path (a `noexec,nosuid` tmpfs), so it goes there; otherwise matplotlib
  writes a warning to stderr on every single run, and on a read-only root it has nowhere else.

## Pinning deviations

All ten direct pins are the specified ones and all ten resolved on PyPI for Python 3.12. One pin
was **added**:

- `cryptography==46.*` — a transitive dependency (`pdfplumber` → `pdfminer.six`; `pypdf` uses it
  for encrypted PDFs when it is importable), not a new library.

The reason is a host bug, not a resolution failure. On the machine this image was first built on
(Docker Desktop server 20.10.22, an aarch64 `linuxkit` 5.15.49 VM), importing
`cryptography.hazmat.bindings._rust` from **any** release ≥ 47.0.0 kills the interpreter with
SIGILL — exit 132, empty stderr, no traceback. Because `pypdf` imports it at package import time,
both `import pypdf` and `import pdfplumber` died silently; the agent would have seen an empty
crash instead of a parsed PDF. Bisected on a stock `python:3.12-slim`, so it is upstream of
anything here: 43.0.3 / 44.0.3 / 45.0.7 / **46.0.3 → ok**; 47.0.0 / 48.0.0 / 49.0.0 / 50.0.1 →
illegal instruction. `--privileged` and `--security-opt seccomp=unconfined` do not help, so it is
not a seccomp filter; `OPENSSL_armcap=0` does not help either.

A newer Docker Desktop (a newer VM kernel) is very likely to run the current series fine. **Drop
this pin once every host that runs turns has one** — it is a floor held down by the oldest box,
and holding a crypto library back is not free.

## There is no network inside

The container runs with `--network none`. A script cannot `pip install` anything at run time, and
cannot fetch a URL. Everything the agent's code needs must be in this image — so when a script
fails on `ModuleNotFoundError`, the fix is a line in this Dockerfile and a rebuild, never a
`subprocess` call to pip. That is deliberate: the sandbox exists to run untrusted, model-written
code over a customer's uploaded files, and a container that can reach the internet can exfiltrate
them.

The image is never pulled at run time either. `docker_runner.docker_available` only inspects the
local image; a missing image is an operator's one-command build, not a silent download.

## File ownership and private defaults

The runner passes the fleet worker's numeric UID/GID to Docker (`--user`), so the worker and
Python can read and write the same private workspace files on Linux and Docker Desktop. Run
the worker as a non-root account; a root worker receives `sandbox_unavailable` with that fix.
The image's `nobody` user remains a fallback for standalone image commands, not workspace runs.
This assumes a local Docker daemon with matching bind-mount ownership; remote daemons and
user-namespace remapping need their own matching filesystem/identity setup.

A fixed startup command sets `umask 077` in the container and then replaces itself with
`python -I -`. The script still arrives only on stdin. Ordinary files are created as `0600`
and directories as `0700`, including those created by subprocesses. The worker's own umask
is never changed, and no image rebuild or extra setting is required for this runner change.

The post-run sweep keeps the existing link, extension and quota checks. It repairs permissions
only when a script explicitly changes them or copies different modes; ordinary output needs
no permission repair before the workspace snapshots it.
