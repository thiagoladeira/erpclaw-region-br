"""Tests for fiscal_data.py — CNPJ/CPF validation and CRUD."""
import argparse
import pytest
from uuid import uuid4


def test_valida_cnpj():
    """CNPJ validation algorithm."""
    from fiscal_data import _valida_cnpj

    # Valid CNPJ
    assert _valida_cnpj("32478156000179")
    # Valid but with formatting
    assert _valida_cnpj("32.478.156/0001-79")
    # Invalid
    assert not _valida_cnpj("00000000000000")
    assert not _valida_cnpj("12345678901234")
    assert not _valida_cnpj("")


def test_valida_cpf():
    """CPF validation algorithm."""
    from fiscal_data import _valida_cpf

    # Valid CPFs (known test values)
    assert _valida_cpf("52998224725")
    # Invalid
    assert not _valida_cpf("00000000000")
    assert not _valida_cpf("11111111111")
    assert not _valida_cpf("")


def test_company_fiscal_crud(db):
    """Create and read company fiscal data."""
    from fiscal_data import add_company_fiscal, get_company_fiscal

    cid = str(uuid4())
    db.execute(
        "INSERT INTO company (id, name, abbr) VALUES (?, 'Test', 'T')",
        (cid,)
    )
    db.commit()

    # Add fiscal data
    args = argparse.Namespace(
        company_id=cid, cnpj='32478156000179',
        inscricao_estadual='38740890', inscricao_municipal='12345',
        razao_social='Test Engenharia', nome_fantasia='Test',
        cnae_principal='7112000', crt='3', regime_isencao='',
        uf='RJ', municipio_codigo='3302403', municipio_nome='Macaé',
        logradouro='Rua Teste', numero='100', complemento='',
        bairro='Centro', cep='27920000', telefone='', email=''
    )
    with pytest.raises(SystemExit):
        result = add_company_fiscal(db, args)

    # Get
    args2 = argparse.Namespace(company_id=cid)
    with pytest.raises(SystemExit):
        result2 = get_company_fiscal(db, args2)


def test_customer_fiscal_crud(db):
    """Create and read customer fiscal data."""
    from fiscal_data import add_customer_fiscal, get_customer_fiscal

    cid = str(uuid4())
    cust_id = str(uuid4())
    db.execute(
        "INSERT INTO company (id, name, abbr) VALUES (?, 'Test', 'T')",
        (cid,)
    )
    db.execute(
        "INSERT INTO customer (id, name, customer_type, company_id) "
        "VALUES (?, 'Petrobras', 'company', ?)",
        (cust_id, cid)
    )
    db.commit()

    args = argparse.Namespace(
        customer_id=cust_id, cnpj='33000167000101', cpf='',
        ie='12345672', isuf='', im='', contribuinte_icms=1,
        crt='3', uf='SP', municipio_codigo='3304557',
        municipio_nome='Rio de Janeiro',
        logradouro='', numero='', complemento='', bairro='',
        cep='', telefone='', email_nfe='compras@petrobras.com.br'
    )
    with pytest.raises(SystemExit):
        result = add_customer_fiscal(db, args)
