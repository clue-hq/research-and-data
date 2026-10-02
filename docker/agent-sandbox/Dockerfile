# The Head-of-ABM code sandbox (spec 2026-09-19 §3.4). One container per run_python call:
# no network, no secrets, read-only root, an unprivileged user. Rebuild with `make sandbox-image`.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
# `cryptography` is transitive (pdfplumber -> pdfminer.six; pypdf uses it when present) and is
# pinned only because its aarch64 wheels for 47+ die on SIGILL under an older Docker Desktop VM
# (linuxkit 5.15) — taking `import pypdf` and `import pdfplumber` down with no error text at all.
# 46.* is the newest series that runs there. See README.md "Pinning deviations"; drop the pin once
# every host runs a Docker VM new enough for the current series.
RUN pip install --no-cache-dir \
    pymupdf==1.24.* pypdf==5.* pdfplumber==0.11.* python-docx==1.1.* python-pptx==1.0.* \
    openpyxl==3.1.* pandas==2.2.* matplotlib==3.9.* pillow==11.* pytesseract==0.3.* \
    cryptography==46.*
RUN mkdir -p /workspace && chown 65534:65534 /workspace
USER 65534:65534
WORKDIR /workspace
ENV PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp
