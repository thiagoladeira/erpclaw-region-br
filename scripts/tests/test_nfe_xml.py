"""Tests for nfe_xml_gen.py — XML generation."""
import argparse


def test_compute_chave_acesso():
    """Access key computation."""
    from nfe_xml_gen import _compute_chave_acesso, _clean_cnpj

    # Test with minimal data dict
    nfe_data = {
        'uf': 'RJ', 'cnpj_emitente': '32478156000179',
        'modelo': '55', 'serie': '1',
        'numero': 1, 'tipo_emissao': '1',
        'codigo_numerico': '12345678'
    }
    # Just verify it runs without error
    result = _compute_chave_acesso(nfe_data)
    assert len(result) == 44


def test_clean_cnpj():
    """CNPJ cleaning."""
    from nfe_xml_gen import _clean_cnpj

    assert _clean_cnpj('32.478.156/0001-79') == '32478156000179'
    assert _clean_cnpj('32478156000179') == '32478156000179'
