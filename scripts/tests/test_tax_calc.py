"""Tests for tax_calc_br.py — tax calculation logic."""
import argparse
import pytest


def test_calculate_icms_basic(db, company_fiscal):
    """ICMS calculation with no sales data."""
    from tax_calc_br import calculate_icms

    args = argparse.Namespace(
        company_id=company_fiscal, uf='RJ',
        ano=2026, mes=1
    )
    with pytest.raises(SystemExit):
        calculate_icms(db, args)


def test_calculate_pis_cofins_basic(db, company_fiscal):
    """PIS/COFINS calculation with no revenue."""
    from tax_calc_br import calculate_pis_cofins

    args = argparse.Namespace(
        company_id=company_fiscal,
        ano=2026, mes=1
    )
    with pytest.raises(SystemExit):
        calculate_pis_cofins(db, args)


def test_calculate_difal(db, company_fiscal):
    """DIFAL calculation."""
    from tax_calc_br import calculate_difal

    args = argparse.Namespace(
        company_id=company_fiscal,
        uf_origem='RJ', uf_destino='SP',
        aliquota_interestadual='12', aliquota_interna_destino='18',
        ano=2026, mes=1
    )
    with pytest.raises(SystemExit):
        calculate_difal(db, args)


def test_calculate_simples_nacional(db, company_fiscal):
    """Simples Nacional calculation."""
    from tax_calc_br import calculate_simples_nacional

    args = argparse.Namespace(
        company_id=company_fiscal,
        ano=2026, mes=1
    )
    with pytest.raises(SystemExit):
        calculate_simples_nacional(db, args)
