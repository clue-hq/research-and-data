"""Section harvesting over a persisted site snapshot (clone-fidelity F2).

F0 gave a capture durable custody (`lumen_ingestion.site_snapshot`); F1 made a cloned section a
first-class artifact (`lumen_api.fragments`). This package is the bridge: it reads back what was
captured and says WHERE this page's sections are and WHAT each one is, so minting has something
precise to mint.

Nothing here writes a row, fetches a byte or calls a model — segmentation is a mechanical read
over html + measured evidence, and its output is a plain value. Import the two modules
explicitly (``from .sections.segment import …`` / ``from .sections.bands import …``): ``bands``
is dependency-free so the capture-side seam can carry band records without pulling a parser in,
while ``segment`` needs selectolax.
"""

from __future__ import annotations
