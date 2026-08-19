"""Compatibility import alias for :mod:`backend.decision.entry_card`."""
import sys

from backend.decision import entry_card as _implementation

if __name__ != "__main__":
    sys.modules[__name__] = _implementation
    sys.modules[__package__].__dict__["m59_entry_card"] = _implementation

if __name__ == "__main__":
    from backend.decision.entry_card import main

    main()
    raise SystemExit(0)
