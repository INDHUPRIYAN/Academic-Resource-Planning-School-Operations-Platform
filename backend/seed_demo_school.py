"""Backward-compatible shim.

The authoritative school seed moved to `app/seeds/Avinashi_GGHSS_seed.py` (the
demo school was renamed to Avinashi GGHSS). This wrapper keeps the old command
working; it now also applies teacher availability, so a single run fully
initializes the institution.

Prefer:  python -m app.seeds.Avinashi_GGHSS_seed
"""
from app.seeds.Avinashi_GGHSS_seed import main

if __name__ == "__main__":
    main()
