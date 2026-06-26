"""Tests for fiscal_catalog.py — CFOP, CST, NCM operations."""
import argparse
import pytest


def test_list_cfops(db):
    """List CFOPs after seeding."""
    from fiscal_catalog import list_cfops
    args = argparse.Namespace(cfop_tipo=None, limit=50, offset=0)
    with pytest.raises(SystemExit):
        list_cfops(db, args)


def test_list_csts(db):
    """List CSTs after seeding."""
    from fiscal_catalog import list_csts
    args = argparse.Namespace()
    with pytest.raises(SystemExit):
        list_csts(db, args)


def test_list_ncms(db):
    """List NCMs after seeding."""
    from fiscal_catalog import list_ncms
    args = argparse.Namespace(limit=50, offset=0)
    with pytest.raises(SystemExit):
        list_ncms(db, args)
