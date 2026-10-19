"""Shared pytest fixtures."""

import sys
from pathlib import Path

# Ensure src/ is always on the path
sys.path.insert(0, str(Path(__file__).parent / "src"))
