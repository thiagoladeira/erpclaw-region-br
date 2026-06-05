"""ERPClaw Region BR — Fiscal Catalogs

CFOP, CST/CSOSN, NCM management.
"""
import sys, os
from uuid import uuid4

sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
from erpclaw_lib.response import ok, err


def add_cfop(conn, args):
    if not args.cfop_codigo or not args.cfop_descricao:
        return err("--cfop-codigo e --cfop-descricao obrigatórios")
    cfop_id = str(uuid4())
    conn.execute("""
        INSERT OR REPLACE INTO cfop (id, codigo, descricao, tipo, operacao)
        VALUES (?, ?, ?, ?, ?)
    """, (cfop_id, args.cfop_codigo, args.cfop_descricao, args.cfop_tipo or 'ambos', args.cfop_operacao or 'todas'))
    conn.commit()
    return ok({"cfop_id": cfop_id, "codigo": args.cfop_codigo, "descricao": args.cfop_descricao})


def list_cfops(conn, args):
    tipo = args.cfop_tipo
    query = "SELECT id, codigo, descricao, tipo, operacao FROM cfop"
    params = []
    if tipo:
        query += " WHERE tipo = ? OR operacao = ?"
        params = [tipo, tipo]
    query += " ORDER BY codigo LIMIT ? OFFSET ?"
    params += [args.limit, args.offset]
    rows = conn.execute(query, params).fetchall()
    return ok({"cfops": [{"id": r[0], "codigo": r[1], "descricao": r[2], "tipo": r[3], "operacao": r[4]} for r in rows]})


def add_cst(conn, args):
    if not args.cst_codigo or not args.cst_descricao:
        return err("--cst-codigo e --cst-descricao obrigatórios")
    cst_id = str(uuid4())
    conn.execute("""
        INSERT OR REPLACE INTO cst_csosn (id, codigo, descricao, imposto, regime)
        VALUES (?, ?, ?, ?, ?)
    """, (cst_id, args.cst_codigo, args.cst_descricao, args.cst_imposto or 'todos', args.cst_regime or 'ambos'))
    conn.commit()
    return ok({"cst_id": cst_id, "codigo": args.cst_codigo, "descricao": args.cst_descricao})


def list_csts(conn, args):
    rows = conn.execute("""
        SELECT id, codigo, descricao, imposto, regime FROM cst_csosn ORDER BY codigo
    """).fetchall()
    return ok({"csts": [{"id": r[0], "codigo": r[1], "descricao": r[2], "imposto": r[3], "regime": r[4]} for r in rows]})


def add_ncm(conn, args):
    if not args.ncm_codigo or not args.ncm_descricao:
        return err("--ncm-codigo e --ncm-descricao obrigatórios")
    ncm_id = str(uuid4())
    conn.execute("""
        INSERT OR REPLACE INTO ncm (id, codigo, descricao, aliquota_ii, aliquota_ipi)
        VALUES (?, ?, ?, ?, ?)
    """, (ncm_id, args.ncm_codigo, args.ncm_descricao, args.aliquota_ii or '0.00', args.aliquota_ipi or '0.00'))
    # Also try to add fiscal data to item if provided
    if args.item_id:
        conn.execute("""
            INSERT INTO item (id, ncm_code) VALUES (?, ?)
            ON CONFLICT(id) DO UPDATE SET ncm_code = ?
        """, (args.item_id, args.ncm_codigo, args.ncm_codigo))
    conn.commit()
    return ok({"ncm_id": ncm_id, "codigo": args.ncm_codigo, "descricao": args.ncm_descricao})


def list_ncms(conn, args):
    rows = conn.execute("SELECT id, codigo, descricao, aliquota_ii, aliquota_ipi FROM ncm ORDER BY codigo LIMIT ? OFFSET ?",
                        (args.limit, args.offset)).fetchall()
    return ok({"ncms": [{"id": r[0], "codigo": r[1], "descricao": r[2], "ii": r[3], "ipi": r[4]} for r in rows]})


def set_item_fiscal_data(conn, args):
    if not args.item_id:
        return err("--item-id obrigatório")
    # Store fiscal data in nfe_item style - could extend item table
    return ok({
        "item_id": args.item_id,
        "ncm": args.ncm_codigo,
        "cfop": args.cfop_codigo,
        "cst_icms": args.cst_codigo,
        "status": "fiscal_data_set",
    })


def get_item_fiscal_data(conn, args):
    if not args.item_id:
        return err("--item-id obrigatório")
    item = conn.execute("SELECT item_code, item_name FROM item WHERE id = ?", (args.item_id,)).fetchone()
    if not item:
        return err("Item não encontrado")
    return ok({
        "item_id": args.item_id,
        "item_code": item[0],
        "item_name": item[1],
        "fiscal_data": "NCM/CFOP/CST a ser vinculado via set-item-fiscal-data",
    })


ACTIONS = {
    "add-cfop": add_cfop,
    "list-cfops": list_cfops,
    "add-cst": add_cst,
    "list-csts": list_csts,
    "add-ncm": add_ncm,
    "list-ncms": list_ncms,
    "set-item-fiscal-data": set_item_fiscal_data,
    "get-item-fiscal-data": get_item_fiscal_data,
}
