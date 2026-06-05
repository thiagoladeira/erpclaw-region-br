"""Tests for ERPClaw Region BR module."""
import os
import sys
import pytest

# Add module to path
MODULE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(MODULE_DIR, 'scripts'))
