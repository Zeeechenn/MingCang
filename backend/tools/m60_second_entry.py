"""Compatibility import alias for :mod:`backend.research.second_entry`."""
import sys

from backend.research import second_entry as _implementation

if __name__ != "__main__":
    sys.modules[__name__] = _implementation
    sys.modules[__package__].__dict__["m60_second_entry"] = _implementation

if __name__ == "__main__":
    from backend.research.second_entry import main

    main()
