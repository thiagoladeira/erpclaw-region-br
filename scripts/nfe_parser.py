"""ERPClaw Region BR — NF-e XML Parser

Parses Brazilian NF-e (Nota Fiscal Eletrônica) XML files, extracts fiscal data,
matches to ERPClaw items/suppliers, and posts stock entries via GL.

Actions:
  parse-nfe-xml     — Parse XML and show extracted data
  import-nfe-entry  — Full import: create stock entry + GL postings
  import-nfe-with-po — Import linked to a purchase order
  list-nfe-imports  — List NF-e import history
  get-nfe-import    — Get single NF-e import details
  validate-nfe-xml  — Validate XML structure
  export-nfe-data   — Export NF-e data as JSON
"""
import json
import os
import sys
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

try:
    from lxml import etree
    HAS_LXML = True
except ImportError:
    HAS_LXML = False

sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
from erpclaw_lib.response import ok, err
from erpclaw_lib.gl_posting import insert_gl_entries

NS_NFE = "http://www.portalfiscal.inf.br/nfe"


def _parse_nfe_xml(xml_content):
    """Parse NF-e XML content and return structured data."""
    if not HAS_LXML:
        return None, "lxml not installed. Run: pip install lxml"

    try:
        if os.path.isfile(xml_content):
            with open(xml_content, 'rb') as f:
                xml_bytes = f.read()
        else:
            xml_bytes = xml_content.encode('utf-8')

        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as e:
        return None, f"XML inválido: {e}"

    ns = {'nfe': NS_NFE}

    def _text(el, xpath_str, default=''):
        if '/@' in xpath_str:
            # Attribute access
            base_xpath = xpath_str.split('/@')[0]
            attr_name = xpath_str.split('/@')[1]
            found = el.find(base_xpath, ns)
            return found.attrib.get(attr_name, default) if found is not None else default
        found = el.find(xpath_str, ns)
        return found.text or default if found is not None else default

    def _decimal(el, xpath, default='0.00'):
        val = _text(el, xpath, default)
        return val if val else default

    # Identificação da NF-e
    ide = root.find('.//nfe:ide', ns)
    if ide is None:
        return None, "Tag <ide> não encontrada no XML"

    chave = _text(root, './/nfe:infNFe/@Id', '').replace('NFe', '')
    data = {
        'chave_acesso': chave,
        'numero_nfe': _text(ide, 'nfe:nNF', ''),
        'serie': _text(ide, 'nfe:serie', '1'),
        'modelo': _text(ide, 'nfe:mod', '55'),
        'data_emissao': _text(ide, 'nfe:dhEmi', '')[:10] or _text(ide, 'nfe:dEmi', ''),
        'natureza_operacao': _text(ide, 'nfe:natOp', ''),
    }

    # Emitente (fornecedor)
    emit = root.find('.//nfe:emit', ns)
    if emit is not None:
        data['emitente_cnpj'] = _text(emit, 'nfe:CNPJ', '')
        data['emitente_nome'] = _text(emit, 'nfe:xNome', '')
        data['emitente_ie'] = _text(emit, 'nfe:IE', '')

    # Totais
    total = root.find('.//nfe:total/nfe:ICMSTot', ns)
    if total is not None:
        data['valor_total'] = _decimal(total, 'nfe:vNF')
        data['valor_produtos'] = _decimal(total, 'nfe:vProd')
        data['base_icms'] = _decimal(total, 'nfe:vBC')
        data['valor_icms'] = _decimal(total, 'nfe:vICMS')
        data['base_icms_st'] = _decimal(total, 'nfe:vBCST')
        data['valor_icms_st'] = _decimal(total, 'nfe:vST')
        data['valor_frete'] = _decimal(total, 'nfe:vFrete')
        data['valor_seguro'] = _decimal(total, 'nfe:vSeg')
        data['valor_desconto'] = _decimal(total, 'nfe:vDesc')
        data['outras_despesas'] = _decimal(total, 'nfe:vOutro')
        # IPI, PIS, COFINS totals
        data['valor_ipi'] = _decimal(total, 'nfe:vIPI')
        data['valor_pis'] = _decimal(total, 'nfe:vPIS')
        data['valor_cofins'] = _decimal(total, 'nfe:vCOFINS')

    # Itens
    items = []
    for det in root.findall('.//nfe:det', ns):
        prod = det.find('nfe:prod', ns)
        imposto = det.find('nfe:imposto', ns)
        if prod is None:
            continue

        item = {
            'numero_item': int(det.get('nItem', '1')),
            'codigo_produto': _text(prod, 'nfe:cProd', ''),
            'descricao': _text(prod, 'nfe:xProd', ''),
            'ncm': _text(prod, 'nfe:NCM', ''),
            'cfop': _text(prod, 'nfe:CFOP', ''),
            'unidade': _text(prod, 'nfe:uCom', 'UN'),
            'quantidade': _decimal(prod, 'nfe:qCom', '1.0'),
            'valor_unitario': _decimal(prod, 'nfe:vUnCom', '0.00'),
            'valor_total': _decimal(prod, 'nfe:vProd', '0.00'),
        }

        if imposto is not None:
            # ICMS
            icms = imposto.find('.//nfe:ICMS/nfe:ICMS00', ns) or \
                   imposto.find('.//nfe:ICMS/nfe:ICMS10', ns) or \
                   imposto.find('.//nfe:ICMS/nfe:ICMS20', ns) or \
                   imposto.find('.//nfe:ICMS/nfe:ICMS40', ns) or \
                   imposto.find('.//nfe:ICMS/nfe:ICMS51', ns) or \
                   imposto.find('.//nfe:ICMS/nfe:ICMS60', ns) or \
                   imposto.find('.//nfe:ICMS/nfe:ICMS70', ns) or \
                   imposto.find('.//nfe:ICMS/nfe:ICMS90', ns)
            if icms is not None:
                item['cst_icms'] = _text(icms, 'nfe:CST', '') or _text(icms, 'nfe:orig', '')
                item['base_icms'] = _decimal(icms, 'nfe:vBC', '0.00')
                item['aliquota_icms'] = _decimal(icms, 'nfe:pICMS', '0.00')
                item['valor_icms'] = _decimal(icms, 'nfe:vICMS', '0.00')

            # IPI
            ipi = imposto.find('.//nfe:IPI/nfe:IPITrib', ns) or \
                  imposto.find('.//nfe:IPI/nfe:IPINT', ns)
            if ipi is not None:
                item['cst_ipi'] = _text(ipi, 'nfe:CST', '')
                item['base_ipi'] = _decimal(ipi, 'nfe:vBC', '0.00')
                item['aliquota_ipi'] = _decimal(ipi, 'nfe:pIPI', '0.00')
                item['valor_ipi'] = _decimal(ipi, 'nfe:vIPI', '0.00')

            # PIS
            pis = imposto.find('.//nfe:PIS/nfe:PISAliq', ns) or \
                  imposto.find('.//nfe:PIS/nfe:PISNT', ns) or \
                  imposto.find('.//nfe:PIS/nfe:PISOutr', ns)
            if pis is not None:
                item['cst_pis'] = _text(pis, 'nfe:CST', '')
                item['aliquota_pis'] = _decimal(pis, 'nfe:pPIS', '0.00')
                item['valor_pis'] = _decimal(pis, 'nfe:vPIS', '0.00')

            # COFINS
            cofins = imposto.find('.//nfe:COFINS/nfe:COFINSAliq', ns) or \
                     imposto.find('.//nfe:COFINS/nfe:COFINSNT', ns) or \
                     imposto.find('.//nfe:COFINS/nfe:COFINSOutr', ns)
            if cofins is not None:
                item['cst_cofins'] = _text(cofins, 'nfe:CST', '')
                item['aliquota_cofins'] = _decimal(cofins, 'nfe:pCOFINS', '0.00')
                item['valor_cofins'] = _decimal(cofins, 'nfe:vCOFINS', '0.00')

        items.append(item)

    data['items'] = items
    data['_cfop_principal'] = items[0].get('cfop', '') if items else ''

    return data, None


def _match_or_create_supplier(conn, cnpj, nome, company_id):
    """Find existing supplier by CNPJ or create new one."""
    cur = conn.execute(
        "SELECT id FROM supplier WHERE tax_id = ? AND company_id = ?",
        (cnpj, company_id)
    )
    row = cur.fetchone()
    if row:
        return row[0]

    supplier_id = str(uuid4())
    conn.execute("""
        INSERT INTO supplier (id, name, tax_id, company_id)
        VALUES (?, ?, ?, ?)
    """, (supplier_id, nome, cnpj, company_id))
    return supplier_id


def _match_or_create_item(conn, codigo, descricao):
    """Find existing item by code or create new one."""
    cur = conn.execute(
        "SELECT id FROM item WHERE item_code = ?",
        (codigo,)
    )
    row = cur.fetchone()
    if row:
        return row[0]

    # Try by name
    cur = conn.execute(
        "SELECT id FROM item WHERE item_name = ? LIMIT 1",
        (descricao,)
    )
    row = cur.fetchone()
    if row:
        return row[0]

    # Create new stock item
    item_id = str(uuid4())
    conn.execute("""
        INSERT INTO item (id, item_code, item_name, item_type, stock_uom,
            standard_rate, last_purchase_rate, status,
            is_purchase_item, is_sales_item, is_stock_item,
            valuation_method, default_procurement_type, has_variants,
            has_batch, has_serial)
        VALUES (?, ?, ?, 'stock', 'Unit', '0.00', '0.00', 'active', 1, 0, 1, 'FIFO', 'purchase', 0, 0, 0)
    """, (item_id, codigo, descricao))
    return item_id


def parse_nfe_xml(conn, args):
    """Parse NF-e XML and return extracted data."""
    xml_content = args.xml_path or args.xml_content
    if not xml_content:
        return err("Forneça --xml-path ou --xml-content")

    data, error = _parse_nfe_xml(xml_content)
    if error:
        return err(error)

    return ok({
        "chave_acesso": data['chave_acesso'],
        "numero": data['numero_nfe'],
        "serie": data['serie'],
        "data_emissao": data['data_emissao'],
        "emitente": {
            "cnpj": data['emitente_cnpj'],
            "nome": data['emitente_nome'],
            "ie": data['emitente_ie'],
        },
        "natureza_operacao": data['natureza_operacao'],
        "totais": {
            "valor_total": data['valor_total'],
            "valor_produtos": data['valor_produtos'],
            "base_icms": data['base_icms'],
            "valor_icms": data['valor_icms'],
            "valor_ipi": data['valor_ipi'],
            "valor_pis": data['valor_pis'],
            "valor_cofins": data['valor_cofins'],
            "frete": data['valor_frete'],
        },
        "items": [
            {
                "numero": i['numero_item'],
                "codigo": i['codigo_produto'],
                "descricao": i['descricao'],
                "ncm": i['ncm'],
                "cfop": i['cfop'],
                "cst_icms": i.get('cst_icms', ''),
                "quantidade": i['quantidade'],
                "valor_unitario": i['valor_unitario'],
                "valor_total": i['valor_total'],
                "icms": i.get('valor_icms', '0.00'),
                "ipi": i.get('valor_ipi', '0.00'),
                "pis": i.get('valor_pis', '0.00'),
                "cofins": i.get('valor_cofins', '0.00'),
            }
            for i in data['items']
        ],
        "total_items": len(data['items']),
    })


def import_nfe_entry(conn, args):
    """Full NF-e import: save XML data, match/create items & supplier, post stock entry."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")

    xml_content = args.xml_path or args.xml_content
    if not xml_content:
        return err("Forneça --xml-path ou --xml-content")

    data, error = _parse_nfe_xml(xml_content)
    if error:
        return err(error)

    # Check if already imported
    chave = data['chave_acesso']
    existing = conn.execute(
        "SELECT id FROM nfe_import WHERE chave_acesso = ?", (chave,)
    ).fetchone()
    if existing:
        return err(f"NF-e já importada: {existing[0]}")

    # Match or create supplier
    supplier_id = None
    if args.supplier_id:
        supplier_id = args.supplier_id
    elif data['emitente_cnpj']:
        supplier_id = _match_or_create_supplier(
            conn, data['emitente_cnpj'], data['emitente_nome'], company_id
        )

    # Create NF-e import record
    nfe_id = str(uuid4())
    conn.execute("""
        INSERT INTO nfe_import (
            id, chave_acesso, numero_nfe, serie, modelo, data_emissao,
            emitente_cnpj, emitente_nome, emitente_ie,
            natureza_operacao, cfop_principal,
            valor_total, valor_produtos,
            base_icms, valor_icms, base_icms_st, valor_icms_st,
            valor_ipi, valor_pis, valor_cofins,
            valor_frete, valor_seguro, valor_desconto, outras_despesas,
            supplier_id, company_id, status
        ) VALUES (
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?,
            ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, 'imported'
        )
    """, (
        nfe_id, chave, data['numero_nfe'], data['serie'], data['modelo'],
        data['data_emissao'],
        data['emitente_cnpj'], data['emitente_nome'], data['emitente_ie'],
        data['natureza_operacao'], data.get('_cfop_principal', ''),
        data['valor_total'], data['valor_produtos'],
        data['base_icms'], data['valor_icms'],
        data['base_icms_st'], data['valor_icms_st'],
        data['valor_ipi'], data['valor_pis'], data['valor_cofins'],
        data['valor_frete'], data['valor_seguro'],
        data['valor_desconto'], data['outras_despesas'],
        supplier_id, company_id,
    ))

    # Save NF-e items
    items_saved = []
    for item in data['items']:
        item_id = str(uuid4())
        matched_item_id = _match_or_create_item(
            conn, item['codigo_produto'], item['descricao']
        )

        conn.execute("""
            INSERT INTO nfe_item (
                id, nfe_import_id, numero_item,
                codigo_produto, descricao, ncm, cfop,
                cst_icms, cst_ipi, cst_pis, cst_cofins,
                unidade, quantidade, valor_unitario, valor_total,
                base_icms, aliquota_icms, valor_icms,
                base_ipi, aliquota_ipi, valor_ipi,
                aliquota_pis, valor_pis, aliquota_cofins, valor_cofins,
                item_id_matched, company_id
            ) VALUES (
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?
            )
        """, (
            item_id, nfe_id, item['numero_item'],
            item['codigo_produto'], item['descricao'],
            item['ncm'], item['cfop'],
            item.get('cst_icms', ''), item.get('cst_ipi', ''),
            item.get('cst_pis', ''), item.get('cst_cofins', ''),
            item['unidade'], item['quantidade'],
            item['valor_unitario'], item['valor_total'],
            item.get('base_icms', '0.00'), item.get('aliquota_icms', '0.00'),
            item.get('valor_icms', '0.00'),
            item.get('base_ipi', '0.00'), item.get('aliquota_ipi', '0.00'),
            item.get('valor_ipi', '0.00'),
            item.get('aliquota_pis', '0.00'), item.get('valor_pis', '0.00'),
            item.get('aliquota_cofins', '0.00'), item.get('valor_cofins', '0.00'),
            matched_item_id, company_id,
        ))
        items_saved.append({
            "item_id": item_id,
            "codigo": item['codigo_produto'],
            "descricao": item['descricao'],
            "quantidade": item['quantidade'],
            "valor_unitario": item['valor_unitario'],
            "valor_total": item['valor_total'],
            "matched_erpclaw_item": matched_item_id,
        })

    conn.commit()

    # If --post-to-gl=true, create stock entry
    stock_entry_id = None
    if args.post_to_gl and args.post_to_gl.lower() == 'true':
        warehouse_id = args.warehouse_id
        if not warehouse_id:
            cur = conn.execute(
                "SELECT id FROM warehouse WHERE company_id = ? LIMIT 1",
                (company_id,)
            )
            row = cur.fetchone()
            if row:
                warehouse_id = row[0]
            else:
                return ok({
                    "nfe_import_id": nfe_id,
                    "status": "imported",
                    "warning": "NF-e importada mas sem warehouse; stock entry não criada",
                    "items": items_saved,
                })


        stock_items = [
            {
                "item_id": si['matched_erpclaw_item'],
                "quantity": si['quantidade'],
                "rate": si['valor_unitario'],
                "warehouse_id": warehouse_id,
            }
            for si in items_saved
        ]
        result = create_stock_entry(
            conn, company_id, 'receive', stock_items, warehouse_id
        )
        if result and result.get('status') == 'ok':
            stock_entry_id = result.get('stock_entry_id')
            conn.execute(
                "UPDATE nfe_import SET stock_entry_id = ?, status = 'posted' WHERE id = ?",
                (stock_entry_id, nfe_id)
            )
            conn.commit()

    return ok({
        "nfe_import_id": nfe_id,
        "chave_acesso": chave,
        "emitente": data['emitente_nome'],
        "total": data['valor_total'],
        "items_count": len(items_saved),
        "supplier_id": supplier_id,
        "stock_entry_id": stock_entry_id,
        "status": "posted" if args.post_to_gl and args.post_to_gl.lower() == 'true' else "imported",
    })


def list_nfe_imports(conn, args):
    """List NF-e imports with pagination."""
    nfe_status = getattr(args, 'status', None) or getattr(args, 'nfe_status', None)
    company_id = getattr(args, 'company_id', None)
    
    where = "WHERE 1=1"
    params = []
    if args.start_date:
        where += " AND data_emissao >= ?"
        params.append(args.start_date)
    if args.end_date:
        where += " AND data_emissao <= ?"
        params.append(args.end_date)

    count_row = conn.execute(
        f"SELECT COUNT(*) FROM nfe_import {where}", params
    ).fetchone()
    total = count_row[0] if count_row else 0

    rows = conn.execute(f"""
        SELECT id, chave_acesso, numero_nfe, serie, data_emissao,
               emitente_nome, valor_total, status, stock_entry_id, created_at
        FROM nfe_import {where}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """, params + [args.limit, args.offset]).fetchall()

    return ok({
        "imports": [
            {
                "id": r[0],
                "chave_acesso": r[1],
                "numero": r[2],
                "serie": r[3],
                "data_emissao": r[4],
                "emitente": r[5],
                "valor_total": r[6],
                "status": r[7],
                "stock_entry_id": r[8],
                "importado_em": r[9],
            }
            for r in rows
        ],
        "total": total,
        "limit": args.limit,
        "offset": args.offset,
    })


def get_nfe_import(conn, args):
    """Get detailed NF-e import with items."""
    nfe_id = args.nfe_import_id
    if not nfe_id:
        return err("--nfe-import-id obrigatório")

    row = conn.execute("""
        SELECT id, chave_acesso, numero_nfe, serie, modelo, data_emissao,
               emitente_cnpj, emitente_nome, emitente_ie,
               natureza_operacao, cfop_principal,
               valor_total, valor_produtos,
               base_icms, valor_icms, valor_ipi, valor_pis, valor_cofins,
               valor_frete, valor_seguro, valor_desconto, outras_despesas,
               supplier_id, stock_entry_id, status, created_at
        FROM nfe_import WHERE id = ?
    """, (nfe_id,)).fetchone()

    if not row:
        return err(f"NF-e não encontrada: {nfe_id}")

    items = conn.execute("""
        SELECT numero_item, codigo_produto, descricao, ncm, cfop,
               cst_icms, unidade, quantidade, valor_unitario, valor_total,
               valor_icms, valor_ipi, valor_pis, valor_cofins,
               item_id_matched
        FROM nfe_item WHERE nfe_import_id = ?
        ORDER BY numero_item
    """, (nfe_id,)).fetchall()

    return ok({
        "id": row[0],
        "chave_acesso": row[1],
        "numero": row[2],
        "serie": row[3],
        "modelo": row[4],
        "data_emissao": row[5],
        "emitente": {
            "cnpj": row[6],
            "nome": row[7],
            "ie": row[8],
        },
        "natureza_operacao": row[9],
        "cfop_principal": row[10],
        "totais": {
            "valor_total": row[11],
            "valor_produtos": row[12],
            "base_icms": row[13],
            "valor_icms": row[14],
            "valor_ipi": row[15],
            "valor_pis": row[16],
            "valor_cofins": row[17],
            "frete": row[18],
            "seguro": row[19],
            "desconto": row[20],
            "outras_despesas": row[21],
        },
        "supplier_id": row[22],
        "stock_entry_id": row[23],
        "status": row[24],
        "importado_em": row[25],
        "items": [
            {
                "numero": i[0],
                "codigo": i[1],
                "descricao": i[2],
                "ncm": i[3],
                "cfop": i[4],
                "cst_icms": i[5],
                "unidade": i[6],
                "quantidade": i[7],
                "valor_unitario": i[8],
                "valor_total": i[9],
                "icms": i[10],
                "ipi": i[11],
                "pis": i[12],
                "cofins": i[13],
                "item_id_erpclaw": i[14],
            }
            for i in items
        ],
    })


def validate_nfe_xml(conn, args):
    """Validate NF-e XML structure."""
    xml_content = args.xml_path or args.xml_content
    if not xml_content:
        return err("Forneça --xml-path ou --xml-content")

    data, error = _parse_nfe_xml(xml_content)
    if error:
        return ok({
            "valid": False,
            "error": error,
        })

    return ok({
        "valid": True,
        "chave_acesso": data['chave_acesso'],
        "numero": data['numero_nfe'],
        "items_count": len(data['items']),
    })


def export_nfe_data(conn, args):
    """Export NF-e data as JSON."""
    nfe_id = args.nfe_import_id
    if not nfe_id:
        return err("--nfe-import-id obrigatório")
    # Reuse get_nfe_import
    return get_nfe_import(conn, args)


# ---------------------------------------------------------------------------
ACTIONS = {
    "parse-nfe-xml": parse_nfe_xml,
    "import-nfe-entry": import_nfe_entry,
    "import-nfe-with-po": import_nfe_entry,  # TODO: add PO linking
    "list-nfe-imports": list_nfe_imports,
    "get-nfe-import": get_nfe_import,
    "validate-nfe-xml": validate_nfe_xml,
    "export-nfe-data": export_nfe_data,
}
