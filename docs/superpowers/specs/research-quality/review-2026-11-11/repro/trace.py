import sys, builtins, traceback
orig = builtins.__import__
seen=False
def imp(name, globals=None, locals=None, fromlist=(), level=0):
    global seen
    if not seen and name.startswith("clue_api.arv2"):
        seen=True
        traceback.print_stack(limit=25)
    return orig(name, globals, locals, fromlist, level)
builtins.__import__ = imp
import importlib
importlib.import_module(sys.argv[1])
print("arv2 loaded:", any(m.startswith("clue_api.arv2") for m in sys.modules))
