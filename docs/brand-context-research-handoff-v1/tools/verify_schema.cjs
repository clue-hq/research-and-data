// Validate the proposed Agent contract offline using dependencies already in this repo.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const pack = path.resolve(__dirname, '..');
const repo = path.resolve(pack, '../..');
const Ajv2020 = require(path.join(repo, 'apps/frontend/node_modules/ajv-formats/node_modules/ajv/dist/2020.js'));
const formats = require(path.join(repo, 'apps/frontend/node_modules/ajv-formats'));
const ajv = new Ajv2020({allErrors: true, strict: true});
formats(ajv);
const read = n => JSON.parse(fs.readFileSync(path.join(pack, n), 'utf8'));
const schema = read('schemas/research-output.schema.json');
const validate = ajv.compile(schema);
const fixture = read('schemas/unknown-example.json');
assert(validate(fixture), JSON.stringify(validate.errors));
for (const [field, value] of [['agent_context', {}], ['status', 'confirmed']]) {
  const bad = structuredClone(fixture);
  bad.documents[0][field] = value;
  assert.equal(validate(bad), false, `Forbidden property accepted: ${field}`);
}
const bad = structuredClone(fixture);
bad.evidence = [{id: 'missing-source-and-quote'}];
assert.equal(validate(bad), false, 'Incomplete evidence accepted');
process.stdout.write('Schema and three negative contract cases passed.\n');
