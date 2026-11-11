import json
from clue_api.arv2 import account_research_tools as art
src=open(art.__file__).read()
import re
# find _tool calls names
print(sorted(set(re.findall(r'name="([a-z_]+)"', src))))
