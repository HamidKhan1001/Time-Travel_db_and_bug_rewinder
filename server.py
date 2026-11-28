"""Apex Gear + Time-Travel Mission Control. Run: python3 server.py  ->  http://localhost:8000

The implementation lives in the ``timetravel.web`` package; this file stays as the stable entry point
(Dockerfile, README, CI and muscle memory all call ``python3 server.py``).
"""
from timetravel.web.app import main

if __name__ == "__main__":
    main()
