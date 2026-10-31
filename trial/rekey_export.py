"""Give an exported Pallet context fresh ids for one trial round, so each round's accounts start
with no earlier research on them (account domains are unique per workspace).

    python3 trial/rekey_export.py <export.json> <round-tag> > <round-export.json>

Every workspace, brand, product, project, document and account id is replaced with a
deterministic new id derived from (old id, round tag); document storage keys move to the new
workspace. Document bytes are unchanged, so their digests stay valid.
"""
import hashlib, json, re, sys, uuid

src, tag = sys.argv[1], sys.argv[2]
data = json.load(open(src))
ns = uuid.uuid5(uuid.NAMESPACE_URL, f"clue-research-trial:{tag}")

def new_text_id(old: str) -> str:
    prefix, _, body = old.partition("_")
    return f"{prefix}_{hashlib.md5(f'{tag}:{old}'.encode()).hexdigest()[:len(body)]}"

mapping: dict[str, str] = {}
ws = data["workspace"][0]["workspace_id"]
mapping[ws] = new_text_id(ws)
for t, col in (("brand", "brand_id"), ("product", "product_id"), ("project", "project_id")):
    for r in data[t]:
        mapping[r[col]] = new_text_id(r[col])
for r in data["brand_knowledge_document"]:
    mapping[r["document_id"]] = str(uuid.uuid5(ns, r["document_id"]))
for r in data["account_entity"]:
    mapping[r["id"]] = str(uuid.uuid5(ns, r["id"]))
for r in data["artifact"]:
    mapping.setdefault(r["artifact_id"], str(uuid.uuid5(ns, r["artifact_id"]))) if r.get("artifact_id") else None

import base64
pattern = re.compile("|".join(re.escape(k) for k in sorted(mapping, key=len, reverse=True)))
sub = lambda t: pattern.sub(lambda m: mapping[m.group(0)], t)
blobs = data.pop("__blobs__")
# Documents name their own brand, product and project ids, so their bytes are rewritten too;
# that changes each digest, and with it the content-addressed storage key.
new_blobs, digest, sizes = {}, {}, {}
for key, b64 in blobs.items():
    raw = base64.b64decode(b64)
    try:
        body = sub(raw.decode("utf-8")).encode("utf-8")
    except UnicodeDecodeError:
        body = raw
    old_sha = key.rsplit("/", 1)[1]
    new_sha = hashlib.sha256(body).hexdigest()
    digest[old_sha] = new_sha
    new_blobs[f"{mapping[ws]}/{new_sha}"] = base64.b64encode(body).decode()
    sizes[f"{mapping[ws]}/{new_sha}"] = len(body)
text = sub(json.dumps(data))
sha_pattern = re.compile("|".join(re.escape(k) for k in digest))
text = sha_pattern.sub(lambda m: digest[m.group(0)], text)
out = json.loads(text)
for r in out["artifact"]:
    r["size_bytes"] = sizes[r["storage_key"]]
out["__blobs__"] = new_blobs
out["workspace"][0]["name"] = f"{out['workspace'][0].get('name', 'Pallet')} (trial {tag})"
json.dump(out, sys.stdout)
print(f"{tag}: workspace {mapping[ws]}, project {mapping[data['project'][0]['project_id']]}",
      file=sys.stderr)
for r in data["account_entity"]:
    print(f"  {r['primary_domain']}: {mapping[r['id']]}", file=sys.stderr)
