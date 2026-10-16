// zod 4 probes `new Function` to decide whether it may compile fast parsers. The editor's policy
// has no 'unsafe-eval', so the probe would raise a violation: jitless turns it off. main.tsx imports
// this module FIRST, before any other module can parse a schema.
import { z } from "zod";

z.config({ jitless: true });
