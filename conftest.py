"""Ensure the project root is importable so `from tools import ...` works in tests."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
