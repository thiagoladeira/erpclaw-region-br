"""ERPClaw Region BR — Setup & Status

Brazilian localization setup: COA import, tax templates, REPETRO, DIFAL config.
"""
import json
import sys, os
from uuid import uuid4
from datetime import datetime

sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
from erpclaw_lib.response import ok, err

# Path to COA template
MODULE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BR_GAAP_PATH = os.path.join(MODULE_DIR, "assets", "charts", "br_gaap.json")


def br_status(conn, args):
    """Status completo da localização brasileira."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")

    # Company
    company = conn.execute("SELECT name, country, default_currency FROM company WHERE id = ?", (company_id,)).fetchone()

    # COA
    coa_count = conn.execute("SELECT COUNT(*) FROM account WHERE company_id = ?", (company_id,)).fetchone()[0]

    # Tax templates
    tax_count = conn.execute("SELECT COUNT(*) FROM tax_template WHERE company_id = ?", (company_id,)).fetchone()[0]

    # NF-e imports
    nfe_count = conn.execute("SELECT COUNT(*) FROM nfe_import WHERE company_id = ?", (company_id,)).fetchone()[0]

    # Tax periods
    period_count = conn.execute("SELECT COUNT(*) FROM tax_period_br WHERE company_id = ?", (company_id,)).fetchone()[0]

    # REPETRO status
    repetro_accounts = 0
    if coa_count > 200:
        repetro_accounts = conn.execute(
            "SELECT COUNT(*) FROM account WHERE company_id = ? AND name LIKE '%REPETRO%'",
            (company_id,)
        ).fetchone()[0]

    return ok({
        "module": "erpclaw-region-br",
        "version": "1.5.0",
        "company": {
            "name": company[0] if company else "N/A",
            "country": company[1] if company else "N/A",
            "currency": company[2] if company else "N/A",
        },
        "localization_status": {
            "chart_of_accounts": f"{coa_count} contas (template BR GAAP)" if coa_count > 200 else f"{coa_count} contas (padrão US GAAP)",
            "tax_templates": f"{tax_count} configurados",
            "nfe_imports": f"{nfe_count} NF-es importadas",
            "tax_periods": f"{period_count} períodos",
            "repetro": f"{repetro_accounts} contas REPETRO" if repetro_accounts > 0 else "não configurado",
        },
        "sped_capabilities": {
            "efd_icms_ipi": "Blocos 0, C, H, K implementados",
            "efd_contrib": "Bloco 0 implementado (demais em desenvolvimento)",
            "ecd": "a implementar",
            "ecf": "a implementar",
            "reinf": "a implementar",
        },
        "nfe_capabilities": {
            "parse_xml": "✓ implementado",
            "import_entry": "✓ implementado",
            "generate_danfe": "\u2713 implementado",
        },
    })


def br_setup(conn, args):
    """Full BR setup: COA import + REPETRO accounts + DIFAL defaults."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")

    steps = []

    # 1. Import BR GAAP COA if not already imported
    coa_count = conn.execute(
        "SELECT COUNT(*) FROM account WHERE company_id = ?", (company_id,)
    ).fetchone()[0]

    if coa_count < 100:
        if os.path.exists(BR_GAAP_PATH):
            with open(BR_GAAP_PATH) as f:
                chart = json.load(f)

            from erpclaw_lib.gl_posting import create_account
            for account in chart:
                acc_id = str(uuid4())
                try:
                    conn.execute("""
                        INSERT INTO account (id, name, account_number, parent_id, root_type, 
                            account_type, is_group, balance_direction, company_id)
                        VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?)
                    """, (acc_id, account['name'], account['account_number'],
                          account['root_type'], account.get('account_type'),
                          account.get('is_group', 0), account.get('balance_direction', 'debit_normal'),
                          company_id))
                except Exception:
                    pass  # Skip duplicates

            conn.commit()
            # Fix parent relationships
            for account in chart:
                if account.get('parent_number'):
                    conn.execute("""
                        UPDATE account SET parent_id = (
                            SELECT a2.id FROM account a2 
                            WHERE a2.account_number = ? AND a2.company_id = ?
                        )
                        WHERE account_number = ? AND company_id = ?
                    """, (account['parent_number'], company_id, account['account_number'], company_id))
            conn.commit()

            new_count = conn.execute(
                "SELECT COUNT(*) FROM account WHERE company_id = ?", (company_id,)
            ).fetchone()[0]
            steps.append(f"COA importado: {new_count} contas BR GAAP")
        else:
            steps.append(f"Template BR GAAP não encontrado em {BR_GAAP_PATH}")
    else:
        steps.append(f"COA BR já configurado: {coa_count} contas")

    # 2. Update company settings
    conn.execute("""
        UPDATE company SET country = 'Brazil', default_currency = 'BRL' WHERE id = ?
    """, (company_id,))
    conn.commit()
    steps.append("Empresa atualizada: Brasil/BRL")

    # 3. Seed tax periods for current year
    year = datetime.now().year
    existing = conn.execute(
        "SELECT COUNT(*) FROM tax_period_br WHERE company_id = ? AND ano = ?",
        (company_id, year)
    ).fetchone()[0]

    if existing == 0:
        for mes in range(1, 13):
            period_id = str(uuid4())
            conn.execute("""
                INSERT INTO tax_period_br (id, ano, mes, data_inicio, data_fim, regime, status, company_id)
                VALUES (?, ?, ?, ?, ?, 'lucro_real', 'aberto', ?)
            """, (period_id, year, mes, f"{year}-{mes:02d}-01", f"{year}-{mes:02d}-28", company_id))
        conn.commit()
        steps.append(f"12 períodos fiscais criados para {year}")

    # 4. Seed DIFAL defaults
    difal_count = conn.execute(
        "SELECT COUNT(*) FROM difal_config WHERE company_id = ?", (company_id,)
    ).fetchone()[0]

    if difal_count == 0:
        ufs = {
            "SP": 18.0, "MG": 18.0, "ES": 17.0, "PR": 18.0, "SC": 17.0,
            "RS": 18.0, "BA": 18.0, "PE": 18.0, "CE": 18.0, "DF": 18.0,
            "GO": 17.0, "MT": 17.0, "MS": 17.0, "AM": 18.0, "PA": 17.0,
        }
        for uf, aliq_interna in ufs.items():
            difal_id = str(uuid4())
            conn.execute("""
                INSERT INTO difal_config (id, uf_origem, uf_destino, aliquota_interestadual, 
                    aliquota_interna_destino, ano_vigencia, company_id)
                VALUES (?, 'RJ', ?, '12.00', ?, ?, ?)
            """, (difal_id, uf, f"{aliq_interna:.2f}", year, company_id))
        conn.commit()
        steps.append(f"DIFAL configurado para {len(ufs)} UFs (origem RJ)")

    return ok({
        "status": "ok",
        "company_id": company_id,
        "steps": steps,
    })


def configure_repetro(conn, args):
    """Configure REPETRO regime for a company — register DIs and track equipment.

    REPETRO is the special customs regime for O&G equipment under temporary admission:
    - Suspends II (import tax), IPI, PIS/COFINS on temporary import
    - Equipment must be exported after the contract period
    - Requires DI (Declaração de Importação) and RE (Registro de Exportação)

    Args:
        --company-id: Company registering for REPETRO
        --di-numero: DI number (format: NN/NNNNNNN-N)
        --di-data: DI date (YYYY-MM-DD)
        --di-vencimento: DI expiry date (YYYY-MM-DD)
        --cnpj-beneficiario: CNPJ of the beneficiary (defaults to company CNPJ)
        --uf-despacho: UF where goods are dispatched
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")

    di_numero = args.di_numero or ""
    di_data = getattr(args, 'di_data', None) or datetime.now().isoformat()[:10]
    data_venc = args.data_vencimento_di or args.di_vencimento or ""
    uf_despacho = args.uf_despacho or args.uf or ""

    # Get CNPJ from company fiscal data
    fiscal = conn.execute(
        "SELECT cnpj FROM company_fiscal WHERE company_id = ?",
        (company_id,)
    ).fetchone()

    cnpj_benef = args.cnpj_beneficiario or (fiscal[0] if fiscal else "")
    cnpj_benef = cnpj_benef.replace(".", "").replace("/", "").replace("-", "")[:14]

    # Validate DI format (NN/NNNNNNN-N)
    import re
    di_valid = re.match(r'^\d{2}/\d{7}-\d$', di_numero) if di_numero else False

    # Register DI
    di_id = str(uuid4())
    try:
        conn.execute("""
            INSERT INTO repetro_di (id, di_numero, di_data, di_vencimento, cnpj_beneficiario,
                                     uf_despacho, status, observacoes, company_id)
            VALUES (?, ?, ?, ?, ?, ?, 'ativo', ?, ?)
        """, (di_id, di_numero, di_data, data_venc, cnpj_benef, uf_despacho,
               f"Regime REPETRO — {di_data}" if di_numero else "", company_id))
        conn.commit()
    except Exception as e:
        return err(f"Erro ao registrar DI: {e}")

    return ok({
        "repetro": "configurado",
        "di_id": di_id,
        "di_numero": di_numero,
        "di_data": di_data,
        "di_vencimento": data_venc,
        "cnpj_beneficiario": cnpj_benef,
        "uf_despacho": uf_despacho,
        "formato_di_valido": di_valid if di_numero else None,
        "alertas": [
            "Verificar prazo de exportação conforme contrato",
            "Manter inventário de equipamentos atualizado",
        ] if di_numero else [],
        "contas": [
            "1.1.6 - Estoques sob REPETRO",
            "1.1.4.09 - ICMS REPETRO a Recuperar",
            "1.1.4.10 - IPI REPETRO a Recuperar",
            "1.1.4.11 - PIS REPETRO a Recuperar",
            "1.1.4.12 - COFINS REPETRO a Recuperar",
            "1.1.4.13 - II REPETRO a Recuperar",
            "2.1.3.15 - ICMS REPETRO a Recolher",
        ],
        "templates": [
            "Importação REPETRO (Suspensão Total)",
            "Exportação REPETRO (Suspensão Total)",
        ],
    })


def repetro_status(conn, args):
    """Check REPETRO status — list all DIs with expiry dates and equipment count.

    Returns all DIs, their expiry dates, equipment count under regime,
    and flags any DI about to expire (< 90 days).

    Args:
        --company-id: Company to check
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")

    today = datetime.now().date()

    # Get all DIs
    dis = conn.execute("""
        SELECT id, di_numero, di_data, di_vencimento, cnpj_beneficiario,
               uf_despacho, status, observacoes
        FROM repetro_di
        WHERE company_id = ?
        ORDER BY di_data DESC
    """, (company_id,)).fetchall()

    dis_list = []
    alertas = []
    equipamento_count = 0
    dis_proximas_vencer = 0

    for di in dis:
        di_id = di[0]
        di_venc_str = di[3] or ""

        # Count equipment for this DI
        eq_count = conn.execute(
            "SELECT COUNT(*) FROM repetro_equipment WHERE repetro_di_id = ?",
            (di_id,)
        ).fetchone()[0]
        equipamento_count += eq_count

        # Calculate days remaining
        dias_restantes = None
        if di_venc_str:
            try:
                dt_venc = datetime.strptime(di_venc_str, "%Y-%m-%d").date()
                dias_restantes = (dt_venc - today).days
                if dias_restantes < 0:
                    dias_restantes = dias_restantes  # negative = expired
            except ValueError:
                pass

        # Flag DIs about to expire
        if dias_restantes is not None and 0 <= dias_restantes < 90:
            dis_proximas_vencer += 1
            alertas.append({
                "di_numero": di[1],
                "di_vencimento": di_venc_str,
                "dias_restantes": dias_restantes,
                "alerta": f"Vence em {dias_restantes} dias!",
            })

        dis_list.append({
            "di_id": di_id,
            "di_numero": di[1],
            "di_data": di[2],
            "di_vencimento": di_venc_str,
            "cnpj_beneficiario": di[4],
            "uf_despacho": di[5],
            "status": di[6],
            "equipamentos": eq_count,
            "dias_restantes": dias_restantes if dias_restantes is not None else "N/A",
        })

    # Get all equipment under active regime
    equipment = conn.execute("""
        SELECT re.id, re.descricao, re.ncm, re.quantidade, re.valor_unitario,
               re.data_entrada, re.data_saida, re.status,
               rd.di_numero
        FROM repetro_equipment re
        JOIN repetro_di rd ON re.repetro_di_id = rd.id
        WHERE re.company_id = ?
        ORDER BY re.data_entrada DESC
        LIMIT 100
    """, (company_id,)).fetchall()

    eq_list = []
    for eq in equipment:
        eq_list.append({
            "equipment_id": eq[0],
            "descricao": eq[1],
            "ncm": eq[2],
            "quantidade": eq[3],
            "valor_unitario": eq[4],
            "data_entrada": eq[5],
            "data_saida": eq[6],
            "status": eq[7],
            "di_numero": eq[8],
        })

    return ok({
        "repetro_ativo": len(dis_list) > 0,
        "total_dis": len(dis_list),
        "total_equipamentos": equipamento_count,
        "equipamentos_ativos": sum(1 for e in eq_list if e["status"] == "ativo"),
        "dis_proximas_vencer": dis_proximas_vencer,
        "dis": dis_list,
        "equipamentos": eq_list,
        "alertas": alertas if alertas else "Nenhum vencimento próximo (< 90 dias)",
        "message": ("ALERTA: Existem DIs prestes a vencer!" if alertas
                    else "Todos os DIs estão em situação regular."),
    })


def register_repetro_equipment(conn, args):
    """Register equipment under a REPETRO DI.

    Links items to a specific DI and tracks entrance/exit dates.

    Args:
        --company-id: Company
        --di-id: REPETRO DI ID to link equipment to
        --item-id: Item ID from ERP
        --equipamento-descricao: Equipment description
        --ncm-code: NCM code
        --quantidade: Quantity (text decimal)
        --valor-unitario: Unit value (text decimal)
        --data-entrada: Entry date (YYYY-MM-DD)
        --data-saida: Exit date (YYYY-MM-DD, optional)
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")

    di_id = args.di_id
    if not di_id:
        return err("--di-id obrigatório — ID da DI REPETRO")

    # Validate DI exists
    di = conn.execute(
        "SELECT id, di_numero, status FROM repetro_di WHERE id = ? AND company_id = ?",
        (di_id, company_id)
    ).fetchone()
    if not di:
        return err(f"DI REPETRO não encontrada: {di_id}")

    if di[2] == 'vencido' or di[2] == 'encerrado':
        return err(f"DI {di[1]} está {di[2]} — não é possível registrar equipamentos")

    item_id = args.item_id or ""
    descricao = args.equipamento_descricao or ""
    ncm = args.ncm_code or args.ncm_codigo or ""

    # If item_id is provided, get description from item
    if item_id and not descricao:
        item = conn.execute(
            "SELECT item_name FROM item WHERE id = ?", (item_id,)
        ).fetchone()
        if item:
            descricao = item[0] or ""

    # Get NCM from item_fiscal if not provided
    if item_id and not ncm:
        ifsc = conn.execute(
            "SELECT ncm FROM item_fiscal WHERE item_id = ?", (item_id,)
        ).fetchone()
        if ifsc:
            ncm = ifsc[0] or ""

    quantidade = getattr(args, 'quantidade', '1') or '1'
    valor_unitario = getattr(args, 'valor_unitario', '0.00') or '0.00'
    data_entrada = args.data_entrada or datetime.now().isoformat()[:10]
    data_saida = args.data_saida or None

    status_eq = "exportado" if data_saida else "ativo"

    eq_id = str(uuid4())
    try:
        conn.execute("""
            INSERT INTO repetro_equipment (id, repetro_di_id, item_id, descricao, ncm,
                                            quantidade, valor_unitario, data_entrada,
                                            data_saida, status, company_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (eq_id, di_id, item_id, descricao, ncm, quantidade, valor_unitario,
               data_entrada, data_saida, status_eq, company_id))
        conn.commit()
    except Exception as e:
        return err(f"Erro ao registrar equipamento: {e}")

    return ok({
        "equipment_id": eq_id,
        "repetro_di_id": di_id,
        "di_numero": di[1],
        "item_id": item_id,
        "descricao": descricao,
        "ncm": ncm,
        "quantidade": quantidade,
        "valor_unitario": valor_unitario,
        "data_entrada": data_entrada,
        "data_saida": data_saida,
        "status": status_eq,
    })


def repetro_expiry_report(conn, args):
    """Report of DIs about to expire.

    Lists all DIs nearing expiry (within --dias threshold, default 90).

    Args:
        --company-id: Company
        --dias: Days threshold (default 90)
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")

    dias_limite = int(getattr(args, 'dias', '90') or 90)
    today = datetime.now().date()
    cutoff = today + datetime.timedelta(days=dias_limite)

    dis = conn.execute("""
        SELECT id, di_numero, di_data, di_vencimento, cnpj_beneficiario,
               uf_despacho, status
        FROM repetro_di
        WHERE company_id = ?
          AND status IN ('ativo', 'prorrogado')
          AND di_vencimento IS NOT NULL AND di_vencimento != ''
        ORDER BY di_vencimento
    """, (company_id,)).fetchall()

    proximos_venc = []
    vencidos = []

    for di in dis:
        try:
            dt_venc = datetime.strptime(di[3], "%Y-%m-%d").date()
            dias_rest = (dt_venc - today).days
        except ValueError:
            continue

        di_info = {
            "di_id": di[0],
            "di_numero": di[1],
            "di_data": di[2],
            "di_vencimento": di[3],
            "cnpj_beneficiario": di[4],
            "uf_despacho": di[5],
            "status": di[6],
            "dias_restantes": dias_rest,
        }

        if dias_rest < 0:
            vencidos.append(di_info)
        elif dias_rest <= dias_limite:
            proximos_venc.append(di_info)

    # Get equipment for expiring DIs
    for item in proximos_venc + vencidos:
        eqs = conn.execute("""
            SELECT id, descricao, ncm, quantidade, valor_unitario, status
            FROM repetro_equipment
            WHERE repetro_di_id = ? AND status = 'ativo'
        """, (item["di_id"],)).fetchall()
        item["equipamentos_afetados"] = [
            {"id": e[0], "descricao": e[1], "ncm": e[2],
             "quantidade": e[3], "valor": e[4], "status": e[5]}
            for e in eqs
        ]

    return ok({
        "company_id": company_id,
        "threshold_dias": dias_limite,
        "data_referencia": today.isoformat(),
        "dis_vencidas": len(vencidos),
        "dis_proximas_vencer": len(proximos_venc),
        "vencidos": vencidos,
        "proximos_vencer": proximos_venc,
        "alerta": "URGENTE: DIs vencidas requerem ação imediata!" if vencidos
                  else ("ATENÇÃO: DIs próximas do vencimento" if proximos_venc
                        else "Nenhum vencimento próximo."),
    })


def repetro_inventory(conn, args):
    """Current equipment inventory under REPETRO regime.

    Lists all equipment still under the special customs regime,
    grouped by DI, with total values.

    Args:
        --company-id: Company
        --status: Filter by equipment status (ativo, exportado, transferido, baixado)
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")

    status_filter = args.status or None

    where = "WHERE re.company_id = ?"
    params = [company_id]
    if status_filter:
        where += " AND re.status = ?"
        params.append(status_filter)

    equipment = conn.execute(f"""
        SELECT re.id, re.item_id, re.descricao, re.ncm, re.quantidade,
               re.valor_unitario, re.data_entrada, re.data_saida, re.status,
               rd.di_numero, rd.di_vencimento
        FROM repetro_equipment re
        JOIN repetro_di rd ON re.repetro_di_id = rd.id
        {where}
        ORDER BY re.status, re.data_entrada DESC
        LIMIT 200
    """, params).fetchall()

    # Group by DI
    grouped = {}
    total_valor = 0.0
    for eq in equipment:
        di = eq[9]
        if di not in grouped:
            grouped[di] = {
                "di_numero": di,
                "di_vencimento": eq[10],
                "equipamentos": [],
                "subtotal_valor": 0.0,
            }

        val = float(eq[4] or 1) * float(eq[5] or 0)
        eq_data = {
            "equipment_id": eq[0],
            "item_id": eq[1],
            "descricao": eq[2],
            "ncm": eq[3],
            "quantidade": eq[4],
            "valor_unitario": eq[5],
            "data_entrada": eq[6],
            "data_saida": eq[7],
            "status": eq[8],
            "valor_total": f"{val:.2f}",
        }
        grouped[di]["equipamentos"].append(eq_data)
        grouped[di]["subtotal_valor"] += val
        total_valor += val

    return ok({
        "company_id": company_id,
        "total_equipamentos": len(equipment),
        "total_dis": len(grouped),
        "valor_total_em_regime": f"{total_valor:.2f}",
        "por_di": [grouped[k] for k in sorted(grouped.keys())],
    })


ACTIONS = {
    "br-status": br_status,
    "br-setup": br_setup,
    "sync-coa-br": lambda c,a: br_setup(c, a),
    "list-tax-templates-br": lambda c,a: ok({
        "templates": [
            "Compra Nacional - Padrão (RJ)", "Venda Nacional - Padrão (RJ)",
            "ICMS Compras (20%)", "ICMS Vendas (20%)",
            "IPI Entrada (5%)", "IPI Saída (5%)",
            "PIS Compras (1,65%)", "PIS Vendas (1,65%)",
            "COFINS Compras (7,6%)", "COFINS Vendas (7,6%)",
            "FECP Compras (2%)", "FECP Vendas (2%)",
            "ISS Serviços (2%)",
            "Retenção IRRF s/ Serviços (1,5%)",
            "Retenção CSRF (PIS/COFINS/CSLL)",
            "Retenção ISS na Fonte (2%)",
            "Importação REPETRO (Suspensão Total)",
            "Exportação REPETRO (Suspensão Total)",
        ],
    }),
    "configure-repetro": configure_repetro,
    "repetro-status": repetro_status,
    "register-repetro-equipment": register_repetro_equipment,
    "repetro-expiry-report": repetro_expiry_report,
    "repetro-inventory": repetro_inventory,
}
