"""ERPClaw Region BR — SPED EFD Contribuições (PIS/COFINS)

Generates EFD Contribuições files from ERPClaw data.
"""
import sys, os
from uuid import uuid4
from datetime import datetime

sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
from erpclaw_lib.response import ok, err


def generate_efd_contrib(conn, args):
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year
    mes = args.mes or datetime.now().month

    company = conn.execute(
        "SELECT name, tax_id FROM company WHERE id = ?", (company_id,)
    ).fetchone()
    if not company:
        return err("Empresa não encontrada")

    lines = []
    # Bloco 0 - Abertura
    lines.append(f"|0000|006|0|0101{ano}|3101{ano}|{company[0][:60]}|{company[1] or ''}|||0|")
    lines.append(f"|0001|1|")

    total = len(lines)
    sped_id = str(uuid4())
    conn.execute("""
        INSERT INTO sped_export_log (id, tipo, ano, mes, arquivo_path, total_registros, status, company_id)
        VALUES (?, 'efd_contrib', ?, ?, NULL, ?, 'gerado', ?)
    """, (sped_id, ano, mes, total, company_id))
    conn.commit()

    return ok({
        "sped_export_id": sped_id,
        "tipo": "efd_contrib",
        "ano": ano, "mes": mes,
        "registros": total,
        "status": "gerado",
        "preview": "\n".join(lines),
    })


def generate_bloco_a(conn, args):
    return ok({"bloco": "A", "registros": 0, "nota": "Bloco A - Serviços (a implementar)"})

def generate_bloco_m(conn, args):
    return ok({"bloco": "M", "registros": 0, "nota": "Bloco M - Apuração PIS/COFINS (a implementar)"})

def generate_bloco_p(conn, args):
    return ok({"bloco": "P", "registros": 0, "nota": "Bloco P - Apuração por Regime (a implementar)"})


ACTIONS = {
    "generate-efd-contrib": generate_efd_contrib,
    "generate-bloco-a": generate_bloco_a,
    "generate-bloco-m": generate_bloco_m,
    "generate-bloco-p": generate_bloco_p,
}
