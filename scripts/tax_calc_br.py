"""ERPClaw Region BR — Tax Calculation

ICMS, ICMS-ST, PIS/COFINS, DIFAL, Simples Nacional, IRPJ/CSLL, CIAP
"""
import sys, os
from uuid import uuid4
from datetime import datetime

sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
from erpclaw_lib.response import ok, err


def calculate_icms(conn, args):
    """Apura ICMS (débito x crédito) por UF e período."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year
    mes = args.mes or (datetime.now().month - 1 if datetime.now().month > 1 else 12)
    uf = args.uf or "RJ"

    # Débito ICMS (vendas) - busca das sales invoices
    debit = conn.execute("""
        SELECT COALESCE(SUM(CAST(total AS REAL) * 0.20), 0)
        FROM sales_invoice
        WHERE company_id = ? 
        AND posting_date LIKE ?
    """, (company_id, f"{ano}-{mes:02d}%")).fetchone()[0]

    # Crédito ICMS (compras) - busca dos nfe_import
    credit = conn.execute("""
        SELECT COALESCE(SUM(CAST(valor_icms AS REAL)), 0)
        FROM nfe_import
        WHERE company_id = ? 
        AND data_emissao LIKE ?
    """, (company_id, f"{ano}-{mes:02d}%")).fetchone()[0]

    saldo = debit - credit
    valor_pagar = max(0, saldo)

    tax_id = str(uuid4())
    conn.execute("""
        INSERT INTO tax_apuration (id, tax_period_br_id, tributo, uf,
            debito, credito, saldo_devedor, saldo_credor, valor_pagar, status, company_id)
        VALUES (?, ?, 'icms', ?,
            ?, ?, ?, ?, ?, 'pendente', ?)
    """, (tax_id, 'periodo-base', uf,
          f"{debit:.2f}", f"{credit:.2f}", f"{saldo:.2f}" if saldo >= 0 else "0.00",
          f"{-saldo:.2f}" if saldo < 0 else "0.00", f"{valor_pagar:.2f}",
          company_id))
    conn.commit()

    return ok({
        "tributo": "ICMS",
        "uf": uf,
        "ano": ano, "mes": mes,
        "debito": f"{debit:.2f}",
        "credito": f"{credit:.2f}",
        "saldo": f"{saldo:.2f}",
        "valor_pagar": f"{valor_pagar:.2f}",
        "tax_apuration_id": tax_id,
    })


def calculate_pis_cofins(conn, args):
    """Apura PIS/COFINS não-cumulativo."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year
    mes = args.mes or (datetime.now().month - 1 if datetime.now().month > 1 else 12)

    revenue = conn.execute("""
        SELECT COALESCE(SUM(CAST(total AS REAL)), 0)
        FROM sales_invoice
        WHERE company_id = ? AND posting_date LIKE ?
    """, (company_id, f"{ano}-{mes:02d}%")).fetchone()[0]

    # Créditos de compras
    purchases = conn.execute("""
        SELECT COALESCE(SUM(CAST(valor_produtos AS REAL)), 0)
        FROM nfe_import
        WHERE company_id = ? AND data_emissao LIKE ?
    """, (company_id, f"{ano}-{mes:02d}%")).fetchone()[0]

    pis_debit = revenue * 0.0165
    cofins_debit = revenue * 0.076
    pis_credit = purchases * 0.0165
    cofins_credit = purchases * 0.076

    pis_pagar = max(0, pis_debit - pis_credit)
    cofins_pagar = max(0, cofins_debit - cofins_credit)

    return ok({
        "periodo": f"{mes:02d}/{ano}",
        "receita_bruta": f"{revenue:.2f}",
        "compras": f"{purchases:.2f}",
        "pis": {
            "debito": f"{pis_debit:.2f}",
            "credito": f"{pis_credit:.2f}",
            "pagar": f"{pis_pagar:.2f}",
        },
        "cofins": {
            "debito": f"{cofins_debit:.2f}",
            "credito": f"{cofins_credit:.2f}",
            "pagar": f"{cofins_pagar:.2f}",
        },
    })


def calculate_difal(conn, args):
    """Calcula DIFAL interestadual."""
    uf_origem = args.uf_origem
    uf_destino = args.uf_destino
    if not uf_origem or not uf_destino:
        return err("--uf-origem e --uf-destino obrigatórios")

    aliq_inter = float(args.aliquota_interestadual or 12)
    aliq_interna = float(args.aliquota_interna_destino or 20)
    difal = aliq_interna - aliq_inter

    return ok({
        "uf_origem": uf_origem,
        "uf_destino": uf_destino,
        "aliquota_interestadual": aliq_inter,
        "aliquota_interna_destino": aliq_interna,
        "difal_percentual": difal,
        "explicacao": f"DIFAL de {difal}% a ser recolhido para {uf_destino}",
    })


def calculate_ciap(conn, args):
    """Controla CIAP (1/48 avos ICMS Ativo Permanente)."""
    return ok({
        "metodo": "1/48 avos",
        "periodo_apropriacao": "48 meses",
        "nota": "CIAP - a cada ativo fixo adquirido, 1/48 do ICMS é creditado mensalmente",
    })


def list_tax_periods(conn, args):
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    rows = conn.execute("""
        SELECT id, ano, mes, regime, status FROM tax_period_br
        WHERE company_id = ? ORDER BY ano DESC, mes DESC LIMIT ?
    """, (company_id, args.limit)).fetchall()
    return ok({
        "periods": [{"id": r[0], "ano": r[1], "mes": r[2], "regime": r[3], "status": r[4]} for r in rows]
    })


def close_tax_period(conn, args):
    tax_id = args.tax_period_id
    if not tax_id:
        return err("--tax-period-id obrigatório")
    conn.execute("UPDATE tax_period_br SET status = 'fechado', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (tax_id,))
    conn.commit()
    return ok({"tax_period_id": tax_id, "status": "fechado"})


ACTIONS = {
    "calculate-icms": calculate_icms,
    "calculate-icms-st": lambda c,a: ok({"nota": "ICMS ST - a implementar com base nos acordos de ST por produto/UF"}),
    "calculate-pis-cofins": calculate_pis_cofins,
    "calculate-difal": calculate_difal,
    "calculate-simples-nacional": lambda c,a: ok({"nota": "Simples Nacional - a implementar tabelas progressivas por anexo"}),
    "calculate-irpj-csll": lambda c,a: ok({"nota": "IRPJ/CSLL - a implementar apuração Lucro Real/Presumido"}),
    "calculate-ciap": calculate_ciap,
    "reconcile-tax-accounts": lambda c,a: ok({"nota": "Conciliação de contas de impostos - a implementar"}),
    "generate-darf": lambda c,a: ok({"nota": "Geração de DARF - a implementar"}),
    "generate-gnre": lambda c,a: ok({"nota": "Geração de GNRE - a implementar"}),
    "list-tax-periods": list_tax_periods,
    "close-tax-period": close_tax_period,
}
