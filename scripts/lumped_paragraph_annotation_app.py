#!/usr/bin/env python3
"""Entry point — Flask lumped-paragraph gold UI (trifecta gold_labeller pattern).

Prefer:
    uv run lumped-paragraph-gold-ui

This script remains as a thin alias.
"""

from lumped_paragraph_labeller.app import main

if __name__ == "__main__":
    main()
