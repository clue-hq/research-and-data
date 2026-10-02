"""Re-export shim: the provider-caller seam lives in ``clue_spend`` since lane 3 slice 5.

The wrapper raises these, so they moved with it. The names and the classes are identical — an
``except ProviderHalted`` written against either import path catches the same object.
"""

from clue_spend.errors import *  # noqa: F401,F403
from clue_spend.errors import __all__  # noqa: F401
