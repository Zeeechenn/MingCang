"""Compatibility import alias for :mod:`backend.evidence.news_v2_oos`."""
import sys

from backend.evidence import news_v2_oos as _implementation

if __name__ != "__main__":
    sys.modules[__name__] = _implementation
    sys.modules[__package__].__dict__["m54_news_v2_oos"] = _implementation

if __name__ == "__main__":
    from backend.evidence.news_v2_oos import main

    main()
    raise SystemExit(0)
