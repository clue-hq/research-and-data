// zod 4 compiles fast parsers with `new Function` when a probe says eval works. None of our pages
// allows eval (the editor, the published page and the design API's render page all leave out
// 'unsafe-eval'), and the probe cannot be trusted to say so: the render page's bundle runs through
// Playwright's add_script_tag, and Chromium lets eval through while that call runs, so zod heard
// "yes" and failed later, after an agent section's import (live 2026-10-19). jitless turns the
// compiling off. Every entry imports this module FIRST: zod decides when a schema is built.
import { z } from "zod";

z.config({ jitless: true });
