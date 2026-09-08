#!/bin/zsh
# usage: ./run.sh request-probook-claims-mode.json   (writes response-<same>.json beside it)
set -a; source .env; set +a
f="$1"; o="${f%.json}.response.json"
curl -s https://api.exa.ai/search -H "x-api-key: $CLUE_EXA_API_KEY" -H "content-type: application/json" --data-binary @"$f" -o "$o" -w "http %{http_code}  %{time_total}s\n"
python3 -c "import json,sys; b=json.load(open('$o')); o=b.get('output') or {}; c=o.get('content'); print('cost', b.get('costDollars'), '| results', len(b.get('results',[])), '| output keys', list(o.keys()), '| content type', type(c).__name__, '| rows' if isinstance(c,dict) else '| chars', len(c.get('claims',[])) if isinstance(c,dict) else len(c or ''))"
