// Prints {site, brand} for the browser harness: the Garner × Syracuse site and brand from
// site-kit's test fixtures, as a Contract 1 site document.
import { garner, site } from "../../../site-kit/test/fixtures/garner";

const stored = site("garner-syracuse");
const document = {
  agent_sections: {},
  id: "doc_probe",
  pages: stored.pages,
  shell: stored.shell,
  theme: {},
  title: "Garner × Syracuse",
};
process.stdout.write(JSON.stringify({ brand: garner(), site: document }));
