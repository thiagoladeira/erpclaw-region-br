"""SEFAZ WebService Client — SOAP communication with Brazilian tax authorities

Lightweight SOAP 1.2 client for NF-e webservices.
No external SOAP library needed — builds envelopes manually.

Supported services:
  - NFeAutorizacao (authorize NF-e)
  - NFeRetAutorizacao (check authorization by receipt)
  - NFeStatusServico (service status check)
  - NFeInutilizacao (invalidate number range)
  - NFeRecepcaoEvento (event reception: cancelamento, CC-e)
  - NFeConsultaCadastro (taxpayer registration check)

Library module: no direct ACTIONS — used by nfe_emission.py.
"""
from __future__ import annotations

import base64
import os
import ssl
import sys
import time
from datetime import datetime
from http.client import HTTPSConnection
from urllib.parse import urlparse

# ── Optional lxml ─────────────────────────────────────────────────────
try:
    from lxml import etree
    HAS_LXML = True
except ImportError:
    HAS_LXML = False

# ── SEFAZ WebService URLs ─────────────────────────────────────────────
# Official URLs per UF for NF-e 4.00.
# Sources: NT 2024.001 / Portal Nacional da NF-e

_SEFAZ_HOMOLOGACAO = {
    # Autorização
    "NFeAutorizacao": {
        "AC": "https://hom1.nfe.fazenda.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "AL": "https://hom1.nfe.fazenda.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "AM": "https://homnfe.sefaz.am.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "AP": "https://hom1.nfe.fazenda.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "BA": "https://hnfe.sefaz.ba.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "CE": "https://nfeh.sefaz.ce.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "DF": "https://hom1.nfe.fazenda.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "ES": "https://hom1.nfe.fazenda.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "GO": "https://homolog.sefaz.go.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "MA": "https://homnfew.sefaz.ma.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "MG": "https://hom1.nfe.fazenda.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "MS": "https://hom.nfe.sefaz.ms.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "MT": "https://homologacao.sefaz.mt.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "PA": "https://homnfe.sefa.pa.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "PB": "https://hom1.nfe.fazenda.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "PE": "https://nfehomolog.sefaz.pe.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "PI": "https://hom1.nfe.fazenda.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "PR": "https://homologacao.nfe.sefa.pr.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "RJ": "https://hom1.nfe.fazenda.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "RN": "https://hom1.nfe.fazenda.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "RO": "https://hom1.nfe.fazenda.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "RR": "https://hom1.nfe.fazenda.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "RS": "https://hom1.nfe.fazenda.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "SC": "https://hom1.nfe.fazenda.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "SE": "https://hom1.nfe.fazenda.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "SP": "https://homologacao.nfe.fazenda.sp.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "TO": "https://hom1.nfe.fazenda.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
    },
    # Retorno Autorização
    "NFeRetAutorizacao": {
        "AC": "https://hom1.nfe.fazenda.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "AL": "https://hom1.nfe.fazenda.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "AM": "https://homnfe.sefaz.am.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "AP": "https://hom1.nfe.fazenda.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "BA": "https://hnfe.sefaz.ba.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "CE": "https://nfeh.sefaz.ce.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "DF": "https://hom1.nfe.fazenda.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "ES": "https://hom1.nfe.fazenda.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "GO": "https://homolog.sefaz.go.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "MA": "https://homnfew.sefaz.ma.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "MG": "https://hom1.nfe.fazenda.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "MS": "https://hom.nfe.sefaz.ms.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "MT": "https://homologacao.sefaz.mt.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "PA": "https://homnfe.sefa.pa.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "PB": "https://hom1.nfe.fazenda.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "PE": "https://nfehomolog.sefaz.pe.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "PI": "https://hom1.nfe.fazenda.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "PR": "https://homologacao.nfe.sefa.pr.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "RJ": "https://hom1.nfe.fazenda.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "RN": "https://hom1.nfe.fazenda.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "RO": "https://hom1.nfe.fazenda.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "RR": "https://hom1.nfe.fazenda.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "RS": "https://hom1.nfe.fazenda.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "SC": "https://hom1.nfe.fazenda.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "SE": "https://hom1.nfe.fazenda.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "SP": "https://homologacao.nfe.fazenda.sp.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "TO": "https://hom1.nfe.fazenda.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
    },
    # Status Serviço
    "NFeStatusServico": {
        "AC": "https://hom1.nfe.fazenda.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "AL": "https://hom1.nfe.fazenda.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "AM": "https://homnfe.sefaz.am.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "AP": "https://hom1.nfe.fazenda.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "BA": "https://hnfe.sefaz.ba.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "CE": "https://nfeh.sefaz.ce.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "DF": "https://hom1.nfe.fazenda.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "ES": "https://hom1.nfe.fazenda.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "GO": "https://homolog.sefaz.go.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "MA": "https://homnfew.sefaz.ma.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "MG": "https://hom1.nfe.fazenda.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "MS": "https://hom.nfe.sefaz.ms.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "MT": "https://homologacao.sefaz.mt.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "PA": "https://homnfe.sefa.pa.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "PB": "https://hom1.nfe.fazenda.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "PE": "https://nfehomolog.sefaz.pe.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "PI": "https://hom1.nfe.fazenda.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "PR": "https://homologacao.nfe.sefa.pr.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "RJ": "https://hom1.nfe.fazenda.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "RN": "https://hom1.nfe.fazenda.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "RO": "https://hom1.nfe.fazenda.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "RR": "https://hom1.nfe.fazenda.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "RS": "https://hom1.nfe.fazenda.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "SC": "https://hom1.nfe.fazenda.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "SE": "https://hom1.nfe.fazenda.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "SP": "https://homologacao.nfe.fazenda.sp.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "TO": "https://hom1.nfe.fazenda.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
    },
    # Eventos
    "NFeRecepcaoEvento": {
        "AC": "https://hom1.nfe.fazenda.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "AL": "https://hom1.nfe.fazenda.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "AP": "https://hom1.nfe.fazenda.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "AM": "https://homnfe.sefaz.am.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "BA": "https://hnfe.sefaz.ba.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "CE": "https://nfeh.sefaz.ce.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "DF": "https://hom1.nfe.fazenda.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "ES": "https://hom1.nfe.fazenda.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "GO": "https://homolog.sefaz.go.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "MA": "https://homnfew.sefaz.ma.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "MG": "https://hom1.nfe.fazenda.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "MS": "https://hom.nfe.sefaz.ms.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "MT": "https://homologacao.sefaz.mt.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "PA": "https://homnfe.sefa.pa.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "PB": "https://hom1.nfe.fazenda.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "PE": "https://nfehomolog.sefaz.pe.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "PI": "https://hom1.nfe.fazenda.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "PR": "https://homologacao.nfe.sefa.pr.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "RJ": "https://hom1.nfe.fazenda.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "RN": "https://hom1.nfe.fazenda.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "RO": "https://hom1.nfe.fazenda.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "RR": "https://hom1.nfe.fazenda.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "RS": "https://hom1.nfe.fazenda.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "SC": "https://hom1.nfe.fazenda.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "SE": "https://hom1.nfe.fazenda.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "SP": "https://homologacao.nfe.fazenda.sp.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "TO": "https://hom1.nfe.fazenda.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
    },
    # Inutilização
    "NFeInutilizacao": {
        "AC": "https://hom1.nfe.fazenda.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "AL": "https://hom1.nfe.fazenda.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "AP": "https://hom1.nfe.fazenda.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "AM": "https://homnfe.sefaz.am.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "BA": "https://hnfe.sefaz.ba.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "CE": "https://nfeh.sefaz.ce.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "DF": "https://hom1.nfe.fazenda.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "ES": "https://hom1.nfe.fazenda.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "GO": "https://homolog.sefaz.go.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "MA": "https://homnfew.sefaz.ma.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "MG": "https://hom1.nfe.fazenda.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "MS": "https://hom.nfe.sefaz.ms.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "MT": "https://homologacao.sefaz.mt.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "PA": "https://homnfe.sefa.pa.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "PB": "https://hom1.nfe.fazenda.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "PE": "https://nfehomolog.sefaz.pe.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "PI": "https://hom1.nfe.fazenda.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "PR": "https://homologacao.nfe.sefa.pr.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "RJ": "https://hom1.nfe.fazenda.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "RN": "https://hom1.nfe.fazenda.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "RO": "https://hom1.nfe.fazenda.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "RR": "https://hom1.nfe.fazenda.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "RS": "https://hom1.nfe.fazenda.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "SC": "https://hom1.nfe.fazenda.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "SE": "https://hom1.nfe.fazenda.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "SP": "https://homologacao.nfe.fazenda.sp.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "TO": "https://hom1.nfe.fazenda.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
    },
    # Consulta Cadastro
    "NFeConsultaCadastro": {
        "AC": "https://hom1.nfe.fazenda.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "AL": "https://hom1.nfe.fazenda.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "AP": "https://hom1.nfe.fazenda.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "AM": "https://homnfe.sefaz.am.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "BA": "https://hnfe.sefaz.ba.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "CE": "https://nfeh.sefaz.ce.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "DF": "https://hom1.nfe.fazenda.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "ES": "https://hom1.nfe.fazenda.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "GO": "https://homolog.sefaz.go.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "MA": "https://homnfew.sefaz.ma.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "MG": "https://hom1.nfe.fazenda.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "MS": "https://hom.nfe.sefaz.ms.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "MT": "https://homologacao.sefaz.mt.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "PA": "https://homnfe.sefa.pa.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "PB": "https://hom1.nfe.fazenda.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "PE": "https://nfehomolog.sefaz.pe.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "PI": "https://hom1.nfe.fazenda.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "PR": "https://homologacao.nfe.sefa.pr.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "RJ": "https://hom1.nfe.fazenda.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "RN": "https://hom1.nfe.fazenda.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "RO": "https://hom1.nfe.fazenda.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "RR": "https://hom1.nfe.fazenda.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "RS": "https://hom1.nfe.fazenda.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "SC": "https://hom1.nfe.fazenda.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "SE": "https://hom1.nfe.fazenda.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "SP": "https://homologacao.nfe.fazenda.sp.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "TO": "https://hom1.nfe.fazenda.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
    },
    # Distribuição DFe
    "NFeDistribuicaoDFe": {
        "SP": "https://homologacao.nfe.fazenda.sp.gov.br/NFE_DISTRIBUICAO_DFE/NFeDistribuicaoDFe.asmx",
    },
}

# Production URLs — identical structure, different hostnames
_SEFAZ_PRODUCAO = {
    "NFeAutorizacao": {
        "AC": "https://nfe.sefaznet.ac.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "AL": "https://nfe.sefaz.al.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "AM": "https://nfe.sefaz.am.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "AP": "https://nfe.sefaz.ap.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "BA": "https://nfe.sefaz.ba.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "CE": "https://nfe.sefaz.ce.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "DF": "https://nfe.fazenda.df.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "ES": "https://nfe.sefaz.es.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "GO": "https://nfe.sefaz.go.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "MA": "https://nfe.sefaz.ma.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "MG": "https://nfe.fazenda.mg.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "MS": "https://nfe.sefaz.ms.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "MT": "https://nfe.sefaz.mt.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "PA": "https://nfe.sefa.pa.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "PB": "https://nfe.sefaz.pb.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "PE": "https://nfe.sefaz.pe.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "PI": "https://nfe.sefaz.pi.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "PR": "https://nfe.sefa.pr.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "RJ": "https://nfe.fazenda.rj.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "RN": "https://nfe.sefaz.rn.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "RO": "https://nfe.sefaz.ro.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "RR": "https://nfe.sefaz.rr.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "RS": "https://nfe.sefaz.rs.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "SC": "https://nfe.sef.sc.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "SE": "https://nfe.sefaz.se.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "SP": "https://nfe.fazenda.sp.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
        "TO": "https://nfe.sefaz.to.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
    },
    "NFeRetAutorizacao": {
        "AC": "https://nfe.sefaznet.ac.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "AL": "https://nfe.sefaz.al.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "AM": "https://nfe.sefaz.am.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "AP": "https://nfe.sefaz.ap.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "BA": "https://nfe.sefaz.ba.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "CE": "https://nfe.sefaz.ce.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "DF": "https://nfe.fazenda.df.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "ES": "https://nfe.sefaz.es.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "GO": "https://nfe.sefaz.go.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "MA": "https://nfe.sefaz.ma.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "MG": "https://nfe.fazenda.mg.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "MS": "https://nfe.sefaz.ms.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "MT": "https://nfe.sefaz.mt.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "PA": "https://nfe.sefa.pa.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "PB": "https://nfe.sefaz.pb.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "PE": "https://nfe.sefaz.pe.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "PI": "https://nfe.sefaz.pi.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "PR": "https://nfe.sefa.pr.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "RJ": "https://nfe.fazenda.rj.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "RN": "https://nfe.sefaz.rn.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "RO": "https://nfe.sefaz.ro.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "RR": "https://nfe.sefaz.rr.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "RS": "https://nfe.sefaz.rs.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "SC": "https://nfe.sef.sc.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "SE": "https://nfe.sefaz.se.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "SP": "https://nfe.fazenda.sp.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
        "TO": "https://nfe.sefaz.to.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
    },
    "NFeStatusServico": {
        "AC": "https://nfe.sefaznet.ac.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "AL": "https://nfe.sefaz.al.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "AM": "https://nfe.sefaz.am.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "AP": "https://nfe.sefaz.ap.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "BA": "https://nfe.sefaz.ba.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "CE": "https://nfe.sefaz.ce.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "DF": "https://nfe.fazenda.df.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "ES": "https://nfe.sefaz.es.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "GO": "https://nfe.sefaz.go.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "MA": "https://nfe.sefaz.ma.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "MG": "https://nfe.fazenda.mg.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "MS": "https://nfe.sefaz.ms.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "MT": "https://nfe.sefaz.mt.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "PA": "https://nfe.sefa.pa.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "PB": "https://nfe.sefaz.pb.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "PE": "https://nfe.sefaz.pe.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "PI": "https://nfe.sefaz.pi.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "PR": "https://nfe.sefa.pr.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "RJ": "https://nfe.fazenda.rj.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "RN": "https://nfe.sefaz.rn.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "RO": "https://nfe.sefaz.ro.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "RR": "https://nfe.sefaz.rr.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "RS": "https://nfe.sefaz.rs.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "SC": "https://nfe.sef.sc.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "SE": "https://nfe.sefaz.se.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "SP": "https://nfe.fazenda.sp.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
        "TO": "https://nfe.sefaz.to.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
    },
    "NFeRecepcaoEvento": {
        "AC": "https://nfe.sefaznet.ac.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "AL": "https://nfe.sefaz.al.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "AP": "https://nfe.sefaz.ap.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "AM": "https://nfe.sefaz.am.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "BA": "https://nfe.sefaz.ba.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "CE": "https://nfe.sefaz.ce.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "DF": "https://nfe.fazenda.df.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "ES": "https://nfe.sefaz.es.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "GO": "https://nfe.sefaz.go.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "MA": "https://nfe.sefaz.ma.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "MG": "https://nfe.fazenda.mg.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "MS": "https://nfe.sefaz.ms.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "MT": "https://nfe.sefaz.mt.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "PA": "https://nfe.sefa.pa.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "PB": "https://nfe.sefaz.pb.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "PE": "https://nfe.sefaz.pe.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "PI": "https://nfe.sefaz.pi.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "PR": "https://nfe.sefa.pr.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "RJ": "https://nfe.fazenda.rj.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "RN": "https://nfe.sefaz.rn.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "RO": "https://nfe.sefaz.ro.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "RR": "https://nfe.sefaz.rr.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "RS": "https://nfe.sefaz.rs.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "SC": "https://nfe.sef.sc.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "SE": "https://nfe.sefaz.se.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "SP": "https://nfe.fazenda.sp.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
        "TO": "https://nfe.sefaz.to.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
    },
    "NFeInutilizacao": {
        "AC": "https://nfe.sefaznet.ac.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "AL": "https://nfe.sefaz.al.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "AP": "https://nfe.sefaz.ap.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "AM": "https://nfe.sefaz.am.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "BA": "https://nfe.sefaz.ba.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "CE": "https://nfe.sefaz.ce.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "DF": "https://nfe.fazenda.df.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "ES": "https://nfe.sefaz.es.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "GO": "https://nfe.sefaz.go.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "MA": "https://nfe.sefaz.ma.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "MG": "https://nfe.fazenda.mg.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "MS": "https://nfe.sefaz.ms.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "MT": "https://nfe.sefaz.mt.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "PA": "https://nfe.sefa.pa.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "PB": "https://nfe.sefaz.pb.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "PE": "https://nfe.sefaz.pe.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "PI": "https://nfe.sefaz.pi.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "PR": "https://nfe.sefa.pr.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "RJ": "https://nfe.fazenda.rj.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "RN": "https://nfe.sefaz.rn.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "RO": "https://nfe.sefaz.ro.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "RR": "https://nfe.sefaz.rr.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "RS": "https://nfe.sefaz.rs.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "SC": "https://nfe.sef.sc.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "SE": "https://nfe.sefaz.se.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "SP": "https://nfe.fazenda.sp.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
        "TO": "https://nfe.sefaz.to.gov.br/NFeInutilizacao4/NFeInutilizacao4.asmx",
    },
    "NFeConsultaCadastro": {
        "AC": "https://nfe.sefaznet.ac.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "AL": "https://nfe.sefaz.al.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "AP": "https://nfe.sefaz.ap.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "AM": "https://nfe.sefaz.am.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "BA": "https://nfe.sefaz.ba.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "CE": "https://nfe.sefaz.ce.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "DF": "https://nfe.fazenda.df.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "ES": "https://nfe.sefaz.es.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "GO": "https://nfe.sefaz.go.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "MA": "https://nfe.sefaz.ma.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "MG": "https://nfe.fazenda.mg.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "MS": "https://nfe.sefaz.ms.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "MT": "https://nfe.sefaz.mt.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "PA": "https://nfe.sefa.pa.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "PB": "https://nfe.sefaz.pb.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "PE": "https://nfe.sefaz.pe.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "PI": "https://nfe.sefaz.pi.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "PR": "https://nfe.sefa.pr.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "RJ": "https://nfe.fazenda.rj.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "RN": "https://nfe.sefaz.rn.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "RO": "https://nfe.sefaz.ro.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "RR": "https://nfe.sefaz.rr.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "RS": "https://nfe.sefaz.rs.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "SC": "https://nfe.sef.sc.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "SE": "https://nfe.sefaz.se.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "SP": "https://nfe.fazenda.sp.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
        "TO": "https://nfe.sefaz.to.gov.br/CadConsultaCadastro4/CadConsultaCadastro4.asmx",
    },
    "NFeDistribuicaoDFe": {
        "SP": "https://nfe.fazenda.sp.gov.br/NFE_DISTRIBUICAO_DFE/NFeDistribuicaoDFe.asmx",
    },
}

# National SVC fallback URLs — when state SEFAZ is unavailable
_SVC_FALLBACK_HOMOLOGACAO = {
    "NFeAutorizacao": "https://hom.svc.fazenda.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
    "NFeRetAutorizacao": "https://hom.svc.fazenda.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
    "NFeStatusServico": "https://hom.svc.fazenda.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
    "NFeRecepcaoEvento": "https://hom.svc.fazenda.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
}

_SVC_FALLBACK_PRODUCAO = {
    "NFeAutorizacao": "https://www.svc.fazenda.gov.br/NFeAutorizacao4/NFeAutorizacao4.asmx",
    "NFeRetAutorizacao": "https://www.svc.fazenda.gov.br/NFeRetAutorizacao4/NFeRetAutorizacao4.asmx",
    "NFeStatusServico": "https://www.svc.fazenda.gov.br/NFeStatusServico4/NFeStatusServico4.asmx",
    "NFeRecepcaoEvento": "https://www.svc.fazenda.gov.br/RecepcaoEvento4/RecepcaoEvento4.asmx",
}

# SOAP actions mapped to services
SOAP_ACTIONS = {
    "NFeAutorizacao": "http://www.portalfiscal.inf.br/nfe/wsdl/NFeAutorizacao4/nfeAutorizacaoLote",
    "NFeRetAutorizacao": "http://www.portalfiscal.inf.br/nfe/wsdl/NFeRetAutorizacao4/nfeRetAutorizacaoLote",
    "NFeStatusServico": "http://www.portalfiscal.inf.br/nfe/wsdl/NFeStatusServico4/nfeStatusServicoNF",
    "NFeRecepcaoEvento": "http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4/nfeRecepcaoEvento",
    "NFeInutilizacao": "http://www.portalfiscal.inf.br/nfe/wsdl/NFeInutilizacao4/nfeInutilizacaoNF",
    "NFeConsultaCadastro": "http://www.portalfiscal.inf.br/nfe/wsdl/CadConsultaCadastro4/consultaCadastro",
    "NFeDistribuicaoDFe": "http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe/nfeDistDFeInteresse",
}

# Cabecalho namespace mapping for each service
NS_CABEC = {
    "NFeAutorizacao": "http://www.portalfiscal.inf.br/nfe/wsdl/NFeAutorizacao4",
    "NFeRetAutorizacao": "http://www.portalfiscal.inf.br/nfe/wsdl/NFeRetAutorizacao4",
    "NFeStatusServico": "http://www.portalfiscal.inf.br/nfe/wsdl/NFeStatusServico4",
    "NFeRecepcaoEvento": "http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4",
    "NFeInutilizacao": "http://www.portalfiscal.inf.br/nfe/wsdl/NFeInutilizacao4",
    "NFeConsultaCadastro": "http://www.portalfiscal.inf.br/nfe/wsdl/CadConsultaCadastro4",
}


# ── Public API ─────────────────────────────────────────────────────────

def get_sefaz_url(uf: str, ambiente: str, servico: str,
                  use_fallback: bool = False) -> str:
    """Return the SEFAZ webservice URL for a given state, environment, and service.

    Args:
        uf: Two-letter state code (SP, RJ, etc.)
        ambiente: 'producao' or 'homologacao'
        servico: Service name (e.g. NFeAutorizacao, NFeRetAutorizacao)
        use_fallback: If True, return national SVC fallback URL

    Returns:
        URL string for the webservice endpoint.
    """
    uf = uf.upper()
    ambiente = ambiente.lower()

    if ambiente == "producao":
        env_map = _SEFAZ_PRODUCAO
        fallback_map = _SVC_FALLBACK_PRODUCAO
    else:
        env_map = _SEFAZ_HOMOLOGACAO
        fallback_map = _SVC_FALLBACK_HOMOLOGACAO

    if servico not in env_map:
        raise ValueError(f"Unknown service: {servico}")

    if use_fallback:
        if servico in fallback_map:
            return fallback_map[servico]
        raise ValueError(f"No fallback URL for service: {servico}")

    url_map = env_map[servico]
    if uf in url_map:
        return url_map[uf]

    # Fall back to SVC if state not configured
    if servico in fallback_map:
        return fallback_map[servico]

    raise ValueError(f"No SEFAZ endpoint for UF={uf}, service={servico}")


def send_soap_request(url: str, soap_action: str, xml_payload: str,
                      certificado_path: str = None,
                      certificado_password: str = None,
                      timeout: int = 30) -> dict:
    """Send a SOAP 1.2 request to a SEFAZ endpoint.

    Args:
        url: The webservice endpoint URL
        soap_action: SOAPAction header value
        xml_payload: The body XML (without SOAP envelope)
        certificado_path: Path to A1 certificate for HTTPS mutual auth
        certificado_password: Certificate password
        timeout: Connection timeout in seconds

    Returns:
        dict with keys: success (bool), xml_response (str), error (str)
    """
    # Extract UF from the cabecalho-like payload or use SP as default
    cuf = _extract_cuf_from_payload(xml_payload)

    # Build SOAP 1.2 envelope
    # Determine the service name from the SOAP action
    servico = _service_from_action(soap_action)
    ns_body = NS_CABEC.get(servico, "http://www.portalfiscal.inf.br/nfe/wsdl/NFeAutorizacao4")

    # For some services (NFeRecepcaoEvento), the body tag name differs
    body_tag_map = {
        "NFeAutorizacao": "nfeDadosMsg",
        "NFeRetAutorizacao": "nfeDadosMsg",
        "NFeStatusServico": "nfeDadosMsg",
        "NFeRecepcaoEvento": "nfeDadosMsg",
        "NFeInutilizacao": "nfeDadosMsg",
        "NFeConsultaCadastro": "nfeDadosMsg",
        "NFeDistribuicaoDFe": "nfeDistDFeInteresse",
    }
    body_tag = body_tag_map.get(servico, "nfeDadosMsg")

    cabecalho_tag_map = {
        "NFeAutorizacao": "nfeCabecMsg",
        "NFeRetAutorizacao": "nfeCabecMsg",
        "NFeStatusServico": "nfeCabecMsg",
        "NFeRecepcaoEvento": "nfeCabecMsg",
        "NFeInutilizacao": "nfeCabecMsg",
        "NFeConsultaCadastro": "nfeCabecMsg",
    }
    cabecalho_tag = cabecalho_tag_map.get(servico, "nfeCabecMsg")

    soap_envelope = f"""<?xml version="1.0" encoding="UTF-8"?>
<soap12:Envelope xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">
  <soap12:Header>
    <{cabecalho_tag} xmlns="{ns_body}">
      <cUF>{cuf}</cUF>
      <versaoDados>4.00</versaoDados>
    </{cabecalho_tag}>
  </soap12:Header>
  <soap12:Body>
    <{body_tag} xmlns="{ns_body}">
{xml_payload}
    </{body_tag}>
  </soap12:Body>
</soap12:Envelope>"""

    # Parse URL
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or 443
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query

    if not host:
        return {"success": False, "error": f"Invalid URL: {url}"}

    # Create SSL context with optional client certificate
    ssl_context = ssl.create_default_context()

    if certificado_path and os.path.isfile(certificado_path):
        try:
            ssl_context.load_cert_chain(
                certificado_path,
                password=certificado_password
            )
        except ssl.SSLError as e:
            return {"success": False, "error": f"Certificate error: {e}"}
        except Exception as e:
            return {"success": False, "error": f"Failed to load certificate: {e}"}

    # Ignore certificate verification in development (homologacao)
    # In production, this should be removed
    disable_ssl_verify = (
        os.environ.get("SEFAZ_SSL_VERIFY", "1") == "0"
        or "homologacao" in url.lower()
        or "homolog" in url.lower()
    )
    if disable_ssl_verify:
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

    try:
        conn = HTTPSConnection(host, port, timeout=timeout, context=ssl_context)

        headers = {
            "Content-Type": "application/soap+xml; charset=utf-8; action=\"{}\"".format(
                soap_action
            ),
            "Content-Length": str(len(soap_envelope.encode("utf-8"))),
        }

        conn.request("POST", path, body=soap_envelope.encode("utf-8"), headers=headers)
        response = conn.getresponse()
        response_body = response.read().decode("utf-8", errors="replace")

        conn.close()

        if response.status != 200:
            return {
                "success": False,
                "error": f"HTTP {response.status}: {response_body[:500]}"
            }

        return {
            "success": True,
            "xml_response": response_body,
            "http_status": response.status,
        }

    except ConnectionRefusedError:
        return {"success": False, "error": "Connection refused — SEFAZ may be offline"}
    except ConnectionError as e:
        return {"success": False, "error": f"Connection error: {e}"}
    except TimeoutError:
        return {"success": False, "error": f"Request timed out after {timeout}s"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── High-level service functions ───────────────────────────────────────

def autorizar_nfe(xml_signed: str, uf: str, ambiente: str,
                  cert_path: str, cert_pass: str) -> dict:
    """Send NF-e authorization request (lote with single NF-e)."""
    url = get_sefaz_url(uf, ambiente, "NFeAutorizacao")
    soap_action = SOAP_ACTIONS["NFeAutorizacao"]

    # Wrap the signed NFe XML in a lote envelope
    id_lote = f"{datetime.now().strftime('%Y%m%d%H%M%S')}000001"
    lote_xml = f"""<enviNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
  <idLote>{id_lote}</idLote>
  <indSinc>1</indSinc>
  {xml_signed[xml_signed.find('<NFe xmlns'):] if '<NFe xmlns' in xml_signed else xml_signed}
</enviNFe>"""

    result = send_soap_request(url, soap_action, lote_xml, cert_path, cert_pass)
    if not result["success"]:
        return result

    return _parse_autorizacao_response(result["xml_response"])


def consultar_recibo(recibo: str, uf: str, ambiente: str,
                     cert_path: str, cert_pass: str) -> dict:
    """Check authorization status by receipt number."""
    url = get_sefaz_url(uf, ambiente, "NFeRetAutorizacao")
    soap_action = SOAP_ACTIONS["NFeRetAutorizacao"]

    consulta_xml = f"""<consReciNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
  <tpAmb>{_tp_amb(ambiente)}</tpAmb>
  <nRec>{recibo}</nRec>
</consReciNFe>"""

    result = send_soap_request(url, soap_action, consulta_xml, cert_path, cert_pass)
    if not result["success"]:
        return result

    return _parse_retorno_autorizacao_response(result["xml_response"])


def status_servico(uf: str, ambiente: str,
                   cert_path: str, cert_pass: str) -> dict:
    """Check SEFAZ web service status."""
    url = get_sefaz_url(uf, ambiente, "NFeStatusServico")
    soap_action = SOAP_ACTIONS["NFeStatusServico"]

    status_xml = f"""<consStatServ xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
  <tpAmb>{_tp_amb(ambiente)}</tpAmb>
  <cUF>{_codigo_uf(uf)}</cUF>
  <xServ>STATUS</xServ>
</consStatServ>"""

    result = send_soap_request(url, soap_action, status_xml, cert_path, cert_pass)
    if not result["success"]:
        return result

    return _parse_status_response(result["xml_response"])


def cancelar_nfe(xml_evento_signed: str, uf: str, ambiente: str,
                 cert_path: str, cert_pass: str) -> dict:
    """Send NF-e cancellation event to SEFAZ."""
    url = get_sefaz_url(uf, ambiente, "NFeRecepcaoEvento")
    soap_action = SOAP_ACTIONS["NFeRecepcaoEvento"]

    # Extract the evento XML from the signed document
    evento_xml = xml_evento_signed
    if '<evento ' in xml_evento_signed:
        start = xml_evento_signed.find('<evento ')
        evento_xml = xml_evento_signed[start:]

    env_xml = f"""<envEvento xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.00">
  <idLote>1</idLote>
  {evento_xml}
</envEvento>"""

    result = send_soap_request(url, soap_action, env_xml, cert_path, cert_pass)
    if not result["success"]:
        return result

    return _parse_evento_response(result["xml_response"])


def inutilizar_numeracao(xml_inutilizacao_signed: str, uf: str, ambiente: str,
                         cert_path: str, cert_pass: str) -> dict:
    """Send inutilização (number range invalidation) request."""
    url = get_sefaz_url(uf, ambiente, "NFeInutilizacao")
    soap_action = SOAP_ACTIONS["NFeInutilizacao"]

    # Extract the inutNFe XML
    inut_xml = xml_inutilizacao_signed
    if '<inutNFe ' in xml_inutilizacao_signed:
        start = xml_inutilizacao_signed.find('<inutNFe ')
        inut_xml = xml_inutilizacao_signed[start:]

    result = send_soap_request(url, soap_action, inut_xml, cert_path, cert_pass)
    if not result["success"]:
        return result

    return _parse_inutilizacao_response(result["xml_response"])


def consultar_cadastro(uf: str, ambiente: str,
                       cert_path: str, cert_pass: str,
                       cnpj_consulta: str) -> dict:
    """Consult taxpayer registration (CNPJ) at SEFAZ."""
    url = get_sefaz_url(uf, ambiente, "NFeConsultaCadastro")
    soap_action = SOAP_ACTIONS["NFeConsultaCadastro"]

    cnpj_clean = "".join(ch for ch in cnpj_consulta if ch.isdigit())

    consulta_xml = f"""<ConsCad xmlns="http://www.portalfiscal.inf.br/nfe" versao="2.00">
  <infCons>
    <xServ>CONS-CAD</xServ>
    <UF>{uf.upper()}</UF>
    <CNPJ>{cnpj_clean}</CNPJ>
  </infCons>
</ConsCad>"""

    result = send_soap_request(url, soap_action, consulta_xml, cert_path, cert_pass)
    if not result["success"]:
        return result

    return _parse_consulta_cadastro_response(result["xml_response"])


# ── Response parsing ──────────────────────────────────────────────────

def _parse_autorizacao_response(xml_response: str) -> dict:
    """Parse the SOAP response from NFeAutorizacao."""
    body = _extract_soap_body(xml_response)
    if not body:
        return {"success": False, "error": "Failed to parse SOAP response"}

    recibo = _extract_text(body, "nRec")
    status = _extract_text(body, "cStat")
    motivo = _extract_text(body, "xMotivo")

    if recibo:
        return {
            "success": True,
            "recibo": recibo,
            "status_code": status,
            "message": motivo,
            "ambiente": "producao" if _extract_text(body, "tpAmb") == "1" else "homologacao",
        }

    # May be a direct approval (sync mode)
    protocolo = _extract_text(body, "nProt")
    if protocolo:
        return {
            "success": True,
            "protocolo": protocolo,
            "status_code": status,
            "message": motivo,
            "data_autorizacao": _extract_text(body, "dhRecbto") or _extract_text(body, "dRecbto", ""),
        }

    # Error/rejection
    return {
        "success": False,
        "error": motivo or "Unknown SEFAZ response",
        "status_code": status,
        "error_details": motivo,
    }


def _parse_retorno_autorizacao_response(xml_response: str) -> dict:
    """Parse the SOAP response from NFeRetAutorizacao."""
    body = _extract_soap_body(xml_response)
    if not body:
        return {"success": False, "error": "Failed to parse SOAP response"}

    status = _extract_text(body, "cStat")
    motivo = _extract_text(body, "xMotivo")

    protocolo = _extract_text(body, "nProt")
    if protocolo:
        return {
            "success": True,
            "status": "autorizado",
            "protocolo": protocolo,
            "status_code": status,
            "message": motivo,
            "data_autorizacao": _extract_text(body, "dhRecbto", ""),
        }

    # May still be processing
    if status == "105":  # Lote em processamento
        return {
            "success": True,
            "status": "pendente",
            "status_code": status,
            "message": motivo,
        }

    return {
        "success": False,
        "error": motivo,
        "status_code": status,
    }


def _parse_status_response(xml_response: str) -> dict:
    """Parse NFeStatusServico SOAP response."""
    body = _extract_soap_body(xml_response)
    if not body:
        return {"success": False, "error": "Failed to parse SOAP response"}

    status = _extract_text(body, "cStat")
    motivo = _extract_text(body, "xMotivo")
    data = _extract_text(body, "dhRecbto", "")
    t_medio = _extract_text(body, "tMed", "")

    return {
        "success": status == "107",  # 107 = serviço operacional
        "status_code": status,
        "message": motivo,
        "operational": status == "107",
        "response_time": data,
        "avg_response_seconds": t_medio,
    }


def _parse_evento_response(xml_response: str) -> dict:
    """Parse NFeRecepcaoEvento SOAP response."""
    body = _extract_soap_body(xml_response)
    if not body:
        return {"success": False, "error": "Failed to parse SOAP response"}

    status = _extract_text(body, "cStat")
    motivo = _extract_text(body, "xMotivo")
    protocolo = _extract_text(body, "nProt")

    if status in ("135", "136"):  # evento registrado
        return {
            "success": True,
            "status_code": status,
            "message": motivo,
            "protocolo": protocolo,
            "data_processamento": _extract_text(body, "dhRegEvento", ""),
        }

    return {
        "success": False,
        "error": motivo,
        "status_code": status,
    }


def _parse_inutilizacao_response(xml_response: str) -> dict:
    """Parse NFeInutilizacao SOAP response."""
    body = _extract_soap_body(xml_response)
    if not body:
        return {"success": False, "error": "Failed to parse SOAP response"}

    status = _extract_text(body, "cStat")
    motivo = _extract_text(body, "xMotivo")
    protocolo = _extract_text(body, "nProt")

    if status == "102":  # inutilização homologada
        return {
            "success": True,
            "status_code": status,
            "message": motivo,
            "protocolo": protocolo,
            "data_processamento": _extract_text(body, "dhRecbto", ""),
        }

    return {
        "success": False,
        "error": motivo,
        "status_code": status,
    }


def _parse_consulta_cadastro_response(xml_response: str) -> dict:
    """Parse NFeConsultaCadastro SOAP response."""
    body = _extract_soap_body(xml_response)
    if not body:
        return {"success": False, "error": "Failed to parse SOAP response"}

    status = _extract_text(body, "cStat")
    motivo = _extract_text(body, "xMotivo")
    ie = _extract_text(body, "IE")
    cnpj = _extract_text(body, "CNPJ")

    return {
        "success": status == "111" or status == "112",
        "status_code": status,
        "message": motivo,
        "cnpj": cnpj,
        "ie": ie,
        "razao_social": _extract_text(body, "xNome", ""),
        "logradouro": _extract_text(body, "xLgr", ""),
        "municipio": _extract_text(body, "xMun", ""),
        "uf": _extract_text(body, "UF", ""),
    }


# ── SOAP parsing helpers ──────────────────────────────────────────────

def _extract_soap_body(xml_response: str) -> str | None:
    """Extract body content from a SOAP response envelope."""
    # Simple text-based extraction (no lxml dependency required)
    body_start = xml_response.find("<soap12:Body>")
    if body_start < 0:
        body_start = xml_response.find("<soap:Body>")
    if body_start < 0:
        body_start = xml_response.find("<SOAP-ENV:Body>")
    if body_start < 0:
        return xml_response  # fallback: return raw

    body_end_tag = "</soap12:Body>"
    closing_start = xml_response.find(body_end_tag, body_start)
    if closing_start < 0:
        body_end_tag = "</soap:Body>"
        closing_start = xml_response.find(body_end_tag, body_start)
    if closing_start < 0:
        body_end_tag = "</SOAP-ENV:Body>"
        closing_start = xml_response.find(body_end_tag, body_start)

    body_start = xml_response.find(">", body_start) + 1

    if closing_start > body_start:
        return xml_response[body_start:closing_start]

    return xml_response[body_start:]


def _extract_text(xml_text: str, tag: str, default: str = "") -> str:
    """Extract text content from an XML tag using text search (no lxml needed)."""
    # Try with namespace shortcuts used in NF-e
    for prefix in ["", "ns2:", "ns3:", "ns4:", "nf:", "nfe:"]:
        open_tag = f"<{prefix}{tag}>"
        close_tag = f"</{prefix}{tag}>"
        start = xml_text.find(open_tag)
        if start >= 0:
            start += len(open_tag)
            end = xml_text.find(close_tag, start)
            if end >= 0:
                return xml_text[start:end].strip()
    return default


def _extract_cuf_from_payload(xml_payload: str) -> str:
    """Try to extract cUF from the payload, default to SP (35)."""
    cuf = _extract_text(xml_payload, "cUF")
    return cuf or "35"


def _service_from_action(soap_action: str) -> str:
    """Map SOAP action to service name."""
    for servico, action in SOAP_ACTIONS.items():
        if action in soap_action:
            return servico
    # Try heuristic
    for keyword in ["Autorizacao", "StatusServico", "RetAutorizacao",
                    "RecepcaoEvento", "Inutilizacao", "ConsultaCadastro"]:
        if keyword in soap_action:
            return f"NFe{keyword}"
    return "NFeAutorizacao"


def _tp_amb(ambiente: str) -> str:
    """Return tpAmb code: 1=producao, 2=homologacao."""
    return "1" if ambiente.lower() == "producao" else "2"


def _codigo_uf(uf: str) -> str:
    """Return IBGE state code for a UF abbreviation."""
    uf_codes = {
        "AC": "12", "AL": "27", "AP": "16", "AM": "13", "BA": "29",
        "CE": "23", "DF": "53", "ES": "32", "GO": "52", "MA": "21",
        "MT": "51", "MS": "50", "MG": "31", "PA": "15", "PB": "25",
        "PR": "41", "PE": "26", "PI": "22", "RJ": "33", "RN": "24",
        "RS": "43", "RO": "11", "RR": "14", "SC": "42", "SP": "35",
        "SE": "28", "TO": "17",
    }
    return uf_codes.get(uf.upper(), "35")


# ── ACTIONS ────────────────────────────────────────────────────────────

ACTIONS: dict = {}
