"""Unified native PostgreSQL entry point; all fixtures share payments_analytics."""
import sys

from postgres_phase1 import main


if __name__ == '__main__':
    sys.exit(main())
