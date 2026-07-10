"""Backward-compatible shim.

Teacher availability now lives in `app/seeds/avinashi_availability.py` and is
also applied automatically by `app/seeds/Avinashi_GGHSS_seed.py`. This wrapper
keeps the old command working for re-applying availability + regenerating.

Prefer:  python -m app.seeds.avinashi_availability
"""
from app.seeds.avinashi_availability import main

if __name__ == "__main__":
    main()
