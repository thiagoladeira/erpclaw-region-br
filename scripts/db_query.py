#!/usr/bin/env python3
"""ERPClaw Region BR -- db_query.py (unified router)

Brazilian fiscal compliance module. NF-e parsing, SPED generation,
tax calculation, fiscal catalogs, and REPETRO management.

Usage: python3 db_query.py --action <action-name> [--flags ...]
Output: JSON to stdout, exit 0 on success, exit 1 on error.
"""
import argparse
import json
import os
import sys

# Add shared lib to path
try:
    sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
    from erpclaw_lib.db import get_connection, ensure_db_exists, DEFAULT_DB_PATH
    from erpclaw_lib.response import ok, err
    from erpclaw_lib.dependencies import check_required_tables
    from erpclaw_lib.args import SafeArgumentParser
except ImportError:
    print(json.dumps({
        "status": "error",
        "error": "ERPClaw foundation not installed. Install erpclaw first.",
        "suggestion": "clawhub install erpclaw"
    }))
    sys.exit(1)

# Add script dir
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nfe_parser import ACTIONS as NFE_ACTIONS
from sped_efd import ACTIONS as SPED_EFD_ACTIONS
from sped_contrib import ACTIONS as SPED_CONTRIB_ACTIONS
from tax_calc_br import ACTIONS as TAX_CALC_ACTIONS
from fiscal_catalog import ACTIONS as FISCAL_CATALOG_ACTIONS
from setup_br import ACTIONS as SETUP_ACTIONS

# ---------------------------------------------------------------------------
SKILL = "erpclaw-region-br"
REQUIRED_TABLES = ["company", "item", "tax_template"]

ACTIONS = {}
ACTIONS.update(NFE_ACTIONS)
ACTIONS.update(SPED_EFD_ACTIONS)
ACTIONS.update(SPED_CONTRIB_ACTIONS)
ACTIONS.update(TAX_CALC_ACTIONS)
ACTIONS.update(FISCAL_CATALOG_ACTIONS)
ACTIONS.update(SETUP_ACTIONS)


def main():
    parser = SafeArgumentParser(description="erpclaw-region-br")
    parser.add_argument("--action", required=True, choices=sorted(ACTIONS.keys()))
    parser.add_argument("--db-path", default=None)

    # Shared
    parser.add_argument("--company-id")
    parser.add_argument("--search")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")

    # NF-e
    parser.add_argument("--xml-path")
    parser.add_argument("--xml-content")
    parser.add_argument("--nfe-import-id")
    parser.add_argument("--chave-acesso")
    parser.add_argument("--supplier-id")
    parser.add_argument("--purchase-order-id")
    parser.add_argument("--warehouse-id")
    parser.add_argument("--post-to-gl", default="false")

    # SPED
    parser.add_argument("--ano", type=int)
    parser.add_argument("--mes", type=int)
    parser.add_argument("--periodo")
    parser.add_argument("--output-dir")
    parser.add_argument("--sped-export-id")
    parser.add_argument("--tipo-sped")

    # Tax calculation
    parser.add_argument("--tributo")
    parser.add_argument("--uf")
    parser.add_argument("--tax-period-id")
    parser.add_argument("--regime")

    # Fiscal catalog
    parser.add_argument("--cfop-id")
    parser.add_argument("--cfop-codigo")
    parser.add_argument("--cfop-descricao")
    parser.add_argument("--cfop-tipo")
    parser.add_argument("--cfop-operacao")
    parser.add_argument("--cst-id")
    parser.add_argument("--cst-codigo")
    parser.add_argument("--cst-descricao")
    parser.add_argument("--cst-imposto")
    parser.add_argument("--cst-regime")
    parser.add_argument("--ncm-id")
    parser.add_argument("--ncm-codigo")
    parser.add_argument("--ncm-descricao")
    parser.add_argument("--item-id")
    parser.add_argument("--aliquota-ii")
    parser.add_argument("--aliquota-ipi")

    # DIFAL
    parser.add_argument("--difal-id")
    parser.add_argument("--uf-origem")
    parser.add_argument("--uf-destino")
    parser.add_argument("--aliquota-interestadual")
    parser.add_argument("--aliquota-interna-destino")

    # REPETRO
    parser.add_argument("--di-numero")
    parser.add_argument("--data-vencimento-di")

    # RBAC
    parser.add_argument("--user-confirmed", default="false")

    args = parser.parse_args()
    action = args.action

    db_path = args.db_path or os.environ.get("ERPCLAW_DB_PATH", DEFAULT_DB_PATH)
    ensure_db_exists(db_path)
    conn = get_connection(db_path) if args.db_path else get_connection()
    check_required_tables(conn, REQUIRED_TABLES)

    handler = ACTIONS[action]
    handler(conn, args)


if __name__ == "__main__":
    main()
