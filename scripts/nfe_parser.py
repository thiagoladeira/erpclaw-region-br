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
            icms = imposto.find('.//nfe:ICMS/nfe:ICMS00', ns)
            if icms is None:
                icms = imposto.find('.//nfe:ICMS/nfe:ICMS10', ns)
            if icms is None:
                icms = imposto.find('.//nfe:ICMS/nfe:ICMS20', ns)
            if icms is None:
                icms = imposto.find('.//nfe:ICMS/nfe:ICMS40', ns)
            if icms is None:
                icms = imposto.find('.//nfe:ICMS/nfe:ICMS51', ns)
            if icms is None:
                icms = imposto.find('.//nfe:ICMS/nfe:ICMS60', ns)
            if icms is None:
                icms = imposto.find('.//nfe:ICMS/nfe:ICMS70', ns)
            if icms is None:
                icms = imposto.find('.//nfe:ICMS/nfe:ICMS90', ns)
            if icms is not None:
                item['cst_icms'] = _text(icms, 'nfe:CST', '') or _text(icms, 'nfe:orig', '')
                item['base_icms'] = _decimal(icms, 'nfe:vBC', '0.00')
                item['aliquota_icms'] = _decimal(icms, 'nfe:pICMS', '0.00')
                item['valor_icms'] = _decimal(icms, 'nfe:vICMS', '0.00')

            # IPI
            ipi = imposto.find('.//nfe:IPI/nfe:IPITrib', ns)
            if ipi is None:
                ipi = imposto.find('.//nfe:IPI/nfe:IPINT', ns)
            if ipi is not None:
                item['cst_ipi'] = _text(ipi, 'nfe:CST', '')
                item['base_ipi'] = _decimal(ipi, 'nfe:vBC', '0.00')
                item['aliquota_ipi'] = _decimal(ipi, 'nfe:pIPI', '0.00')
                item['valor_ipi'] = _decimal(ipi, 'nfe:vIPI', '0.00')

            # PIS
            pis = imposto.find('.//nfe:PIS/nfe:PISAliq', ns)
            if pis is None:
                pis = imposto.find('.//nfe:PIS/nfe:PISNT', ns)
            if pis is None:
                pis = imposto.find('.//nfe:PIS/nfe:PISOutr', ns)
            if pis is not None:
                item['cst_pis'] = _text(pis, 'nfe:CST', '')
                item['aliquota_pis'] = _decimal(pis, 'nfe:pPIS', '0.00')
                item['valor_pis'] = _decimal(pis, 'nfe:vPIS', '0.00')

            # COFINS
            cofins = imposto.find('.//nfe:COFINS/nfe:COFINSAliq', ns)
            if cofins is None:
                cofins = imposto.find('.//nfe:COFINS/nfe:COFINSNT', ns)
            if cofins is None:
                cofins = imposto.find('.//nfe:COFINS/nfe:COFINSOutr', ns)
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

    # Read raw XML content for archival
    xml_raw = None
    if args.xml_path and os.path.isfile(args.xml_path):
        with open(args.xml_path, 'r', encoding='utf-8') as f:
            xml_raw = f.read()
    elif args.xml_content:
        xml_raw = args.xml_content

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
            xml_raw, supplier_id, company_id, status
        ) VALUES (
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?,
            ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, 'imported'
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
        xml_raw, supplier_id, company_id,
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
# DANFE (Documento Auxiliar da Nota Fiscal Eletrônica)
# ---------------------------------------------------------------------------

DANFE_CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Courier New', monospace; font-size: 11px; color: #000; background: #fff; }
.danfe { width: 210mm; margin: 0 auto; padding: 3mm; }
.danfe h1 { font-size: 14px; text-align: center; margin-bottom: 2mm; }
.frame { border: 1px dashed #000; margin-bottom: 1mm; padding: 1mm; }
.frame-title { font-size: 8px; font-weight: bold; text-transform: uppercase; display: inline-block; background: #fff; position: relative; top: -1.5mm; left: 2mm; padding: 0 1mm; }
.row { display: flex; }
.col { flex: 1; padding: 0.5mm 1mm; }
.col-2 { flex: 2; }
.col-3 { flex: 3; }
.col-4 { flex: 4; }
.label { font-size: 7px; font-weight: bold; }
.value { font-size: 10px; min-height: 4mm; }
.value-lg { font-size: 13px; font-weight: bold; }
table { width: 100%; border-collapse: collapse; font-size: 9px; margin-top: 0.5mm; }
table th { background: #ddd; font-size: 7px; padding: 0.5mm; border: 0.5px solid #999; text-align: center; }
table td { padding: 0.5mm; border: 0.5px solid #999; text-align: center; }
table td.left { text-align: left; }
table td.right { text-align: right; }
.chave { font-size: 12px; font-weight: bold; letter-spacing: 1px; word-break: break-all; }
.barcode { text-align: center; margin: 2mm 0; }
.barcode img { width: 100%; max-height: 18mm; }
.barcode-text { font-size: 7px; word-break: break-all; }
.separator { border-top: 2px solid #000; margin: 2mm 0; }
.consulta { font-size: 7px; text-align: center; margin-top: 1mm; }
.footer { font-size: 7px; text-align: center; margin-top: 2mm; }
.signature-box { border: 0.5px solid #000; height: 24mm; padding: 1mm; margin-top: 1mm; position: relative; }
.signature-line { position: absolute; bottom: 5mm; left: 10mm; right: 10mm; border-top: 0.5px solid #000; }
.signature-label { font-size: 7px; text-align: center; margin-top: 1mm; }
.canhoto { margin-top: 4mm; }
@media print { body { margin: 0; } .danfe { width: 100%; } }
.total-row { background: #f0f0f0; font-weight: bold; }
.watermark { position: fixed; top: 40%; left: 0; width: 100%; text-align: center; font-size: 60px; color: rgba(0,0,0,0.04); transform: rotate(-30deg); pointer-events: none; z-index: -1; }
"""


def _format_chave(chave):
    """Format 44-digit access key with spaces."""
    if len(chave) == 44:
        return ' '.join([chave[i:i+4] for i in range(0, 44, 4)])
    return chave


def _format_cnpj(cnpj):
    """Format CNPJ as XX.XXX.XXX/XXXX-XX."""
    cnpj = cnpj.zfill(14)
    return f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:14]}"


def _format_decimal(val):
    """Format decimal with thousand separators."""
    try:
        d = float(val)
        return f"{d:,.2f}"
    except (ValueError, TypeError):
        return str(val)


def _generate_danfe_html(nfe_data, company_name=""):
    """Generate DANFE HTML from parsed NF-e data."""
    emit = nfe_data.get('emitente', {})
    dest = nfe_data.get('destinatario', {})
    totais = nfe_data.get('totais', {})
    transp = nfe_data.get('transporte', {})
    items = nfe_data.get('items', [])
    info = nfe_data.get('informacoes_adicionais', '')

    # Build HTML
    html_parts = []

    def add(s):
        html_parts.append(s)

    add('<!DOCTYPE html>')
    add('<html lang="pt-BR">')
    add('<head><meta charset="UTF-8">')
    add('<title>DANFE - NFe ' + nfe_data.get('numero_nfe', '') + '</title>')
    add('<style>' + DANFE_CSS + '</style>')
    add('</head><body>')
    add('<div class="danfe">')
    add('<div class="watermark">DANFE</div>')

    # Header
    add('<div class="frame">')
    add('<span class="frame-title">DANFE - Documento Auxiliar da Nota Fiscal Eletrônica</span>')
    add('<div class="row">')
    add('<div class="col"><div class="label">RECEBEMOS DE</div><div class="value">' + emit.get('nome', '') + '</div></div>')
    add('<div class="col"><div class="label">CNPJ</div><div class="value">' + _format_cnpj(emit.get('cnpj', '')) + '</div></div>')
    add('<div class="col"><div class="label">INSC. ESTADUAL</div><div class="value">' + emit.get('ie', '') + '</div></div>')
    add('<div class="col"><div class="label">DATA EMISSÃO</div><div class="value">' + nfe_data.get('data_emissao', '') + '</div></div>')
    add('</div>')
    add('</div>')

    # Document info
    add('<div class="frame">')
    add('<span class="frame-title">Documento Fiscal</span>')
    add('<div class="row">')
    add('<div class="col"><div class="label">NATUREZA DA OPERAÇÃO</div><div class="value">' + nfe_data.get('natureza_operacao', '') + '</div></div>')
    add('<div class="col"><div class="label">Nº</div><div class="value value-lg">' + nfe_data.get('numero_nfe', '') + '</div></div>')
    add('<div class="col"><div class="label">SÉRIE</div><div class="value value-lg">' + nfe_data.get('serie', '') + '</div></div>')
    add('<div class="col"><div class="label">FOLHA</div><div class="value">1/1</div></div>')
    add('</div>')
    add('</div>')

    # Access key
    add('<div class="frame">')
    add('<span class="frame-title">Chave de Acesso</span>')
    add('<div class="chave">' + _format_chave(nfe_data.get('chave_acesso', '')) + '</div>')
    add('</div>')

    # Consulte em
    add('<div class="consulta">')
    add('Consulta de autenticidade no portal nacional da NF-e: www.nfe.fazenda.gov.br/portal ou no site da SEFAZ autora')
    add('</div>')
    add('<div class="separator"></div>')

    # Recipient
    add('<div class="frame">')
    add('<span class="frame-title">Destinatário / Remetente</span>')
    add('<div class="row">')
    add('<div class="col col-4"><div class="label">NOME / RAZÃO SOCIAL</div><div class="value">' + dest.get('nome', emit.get('nome', '')) + '</div></div>')
    add('<div class="col"><div class="label">CNPJ / CPF</div><div class="value">' + (_format_cnpj(dest.get('cnpj', '')) if dest.get('cnpj') else '') + '</div></div>')
    add('<div class="col"><div class="label">DATA SAÍDA</div><div class="value">' + nfe_data.get('data_saida', nfe_data.get('data_emissao', '')) + '</div></div>')
    add('</div>')
    add('<div class="row">')
    add('<div class="col col-3"><div class="label">ENDEREÇO</div><div class="value">' + dest.get('logradouro', '') + ', ' + dest.get('numero', '') + '</div></div>')
    add('<div class="col"><div class="label">BAIRRO</div><div class="value">' + dest.get('bairro', '') + '</div></div>')
    add('<div class="col"><div class="label">CEP</div><div class="value">' + dest.get('cep', '') + '</div></div>')
    add('<div class="col"><div class="label">DATA SAÍDA</div><div class="value">' + nfe_data.get('data_saida', nfe_data.get('data_emissao', '')) + '</div></div>')
    add('</div>')
    add('<div class="row">')
    add('<div class="col"><div class="label">MUNICÍPIO</div><div class="value">' + dest.get('municipio', '') + '</div></div>')
    add('<div class="col"><div class="label">UF</div><div class="value">' + dest.get('uf', '') + '</div></div>')
    add('<div class="col"><div class="label">INSC. ESTADUAL</div><div class="value">' + dest.get('ie', '') + '</div></div>')
    add('<div class="col"><div class="label">HORA SAÍDA</div><div class="value">' + nfe_data.get('hora_saida', '') + '</div></div>')
    add('</div>')
    add('</div>')

    # Tax calculation
    add('<div class="frame">')
    add('<span class="frame-title">Cálculo do Imposto</span>')
    add('<div class="row">')
    add('<div class="col"><div class="label">BASE DE CÁLC. ICMS</div><div class="value right">' + _format_decimal(totais.get('base_icms', '0')) + '</div></div>')
    add('<div class="col"><div class="label">VALOR ICMS</div><div class="value right">' + _format_decimal(totais.get('valor_icms', '0')) + '</div></div>')
    add('<div class="col"><div class="label">BASE CÁLC. ICMS ST</div><div class="value right">' + _format_decimal(totais.get('base_icms_st', '0')) + '</div></div>')
    add('<div class="col"><div class="label">VALOR ICMS ST</div><div class="value right">' + _format_decimal(totais.get('valor_icms_st', '0')) + '</div></div>')
    add('<div class="col"><div class="label">VALOR FRETE</div><div class="value right">' + _format_decimal(totais.get('valor_frete', '0')) + '</div></div>')
    add('</div>')
    add('<div class="row">')
    add('<div class="col"><div class="label">VALOR SEGURO</div><div class="value right">' + _format_decimal(totais.get('valor_seguro', '0')) + '</div></div>')
    add('<div class="col"><div class="label">DESCONTO</div><div class="value right">' + _format_decimal(totais.get('valor_desconto', '0')) + '</div></div>')
    add('<div class="col"><div class="label">OUTRAS DESPESAS</div><div class="value right">' + _format_decimal(totais.get('outras_despesas', '0')) + '</div></div>')
    add('<div class="col"><div class="label">VALOR IPI</div><div class="value right">' + _format_decimal(totais.get('valor_ipi', '0')) + '</div></div>')
    add('<div class="col"><div class="label">VALOR TOTAL NF</div><div class="value right value-lg">' + _format_decimal(totais.get('valor_total', '0')) + '</div></div>')
    add('</div>')
    add('</div>')

    # Transport
    add('<div class="frame">')
    add('<span class="frame-title">Transportador / Volumes</span>')
    add('<div class="row">')
    add('<div class="col col-3"><div class="label">TRANSPORTADOR</div><div class="value">' + transp.get('nome', '') + '</div></div>')
    add('<div class="col"><div class="label">CNPJ / CPF</div><div class="value">' + (transp.get('cnpj', '')) + '</div></div>')
    add('<div class="col"><div class="label">IE</div><div class="value">' + transp.get('ie', '') + '</div></div>')
    add('<div class="col"><div class="label">FRETE</div><div class="value">' + transp.get('modalidade_frete', '0 - Emitente') + '</div></div>')
    add('</div>')
    add('<div class="row">')
    add('<div class="col"><div class="label">ENDEREÇO</div><div class="value">' + transp.get('endereco', '') + '</div></div>')
    add('<div class="col"><div class="label">MUNICÍPIO</div><div class="value">' + transp.get('municipio', '') + '</div></div>')
    add('<div class="col"><div class="label">UF</div><div class="value">' + transp.get('uf', '') + '</div></div>')
    add('<div class="col"><div class="label">VEÍCULO</div><div class="value">' + transp.get('placa', '') + '</div></div>')
    add('<div class="col"><div class="label">UF VEÍC.</div><div class="value">' + transp.get('uf_veiculo', '') + '</div></div>')
    add('</div>')
    add('<div class="row">')
    add('<div class="col"><div class="label">QUANTIDADE</div><div class="value">' + transp.get('qtd_volumes', '') + '</div></div>')
    add('<div class="col"><div class="label">ESPÉCIE</div><div class="value">' + transp.get('especie', '') + '</div></div>')
    add('<div class="col"><div class="label">MARCA</div><div class="value">' + transp.get('marca', '') + '</div></div>')
    add('<div class="col"><div class="label">NUMERAÇÃO</div><div class="value">' + transp.get('numeracao', '') + '</div></div>')
    add('<div class="col"><div class="label">PESO BRUTO</div><div class="value">' + transp.get('peso_bruto', '') + '</div></div>')
    add('<div class="col"><div class="label">PESO LÍQUIDO</div><div class="value">' + transp.get('peso_liquido', '') + '</div></div>')
    add('</div>')
    add('</div>')

    # Items table
    add('<div class="frame">')
    add('<span class="frame-title">Dados dos Produtos / Serviços</span>')
    add('<table>')
    add('<thead><tr>')
    add('<th style="width:5%">Item</th>')
    add('<th style="width:7%">Código</th>')
    add('<th style="width:20%">Descrição</th>')
    add('<th style="width:5%">NCM</th>')
    add('<th style="width:5%">CFOP</th>')
    add('<th style="width:5%">Un</th>')
    add('<th style="width:6%">Qtde</th>')
    add('<th style="width:8%">Vl. Unit</th>')
    add('<th style="width:8%">Vl. Total</th>')
    add('<th style="width:7%">BC ICMS</th>')
    add('<th style="width:7%">Vl. ICMS</th>')
    add('<th style="width:6%">%ICMS</th>')
    add('<th style="width:6%">%IPI</th>')
    add('</tr></thead>')
    add('<tbody>')

    total_prod = 0.0
    total_icms = 0.0
    total_ipi = 0.0

    for item in items:
        vl_total = float(item.get('valor_total', 0) or 0)
        vl_icms = float(item.get('valor_icms', 0) or 0)
        vl_ipi = float(item.get('valor_ipi', 0) or 0)
        total_prod += vl_total
        total_icms += vl_icms
        total_ipi += vl_ipi

        add('<tr>')
        add('<td>' + str(item.get('numero_item', '')) + '</td>')
        add('<td>' + item.get('codigo_produto', '') + '</td>')
        add('<td class="left">' + item.get('descricao', '') + '</td>')
        add('<td>' + item.get('ncm', '') + '</td>')
        add('<td>' + item.get('cfop', '') + '</td>')
        add('<td>' + item.get('unidade', '') + '</td>')
        add('<td class="right">' + _format_decimal(item.get('quantidade', '0')) + '</td>')
        add('<td class="right">' + _format_decimal(item.get('valor_unitario', '0')) + '</td>')
        add('<td class="right">' + _format_decimal(item.get('valor_total', '0')) + '</td>')
        add('<td class="right">' + _format_decimal(item.get('base_icms', '0')) + '</td>')
        add('<td class="right">' + _format_decimal(item.get('valor_icms', '0')) + '</td>')
        add('<td>' + item.get('aliquota_icms', '') + '</td>')
        add('<td>' + item.get('aliquota_ipi', '') + '</td>')
        add('</tr>')

    # Totals row
    add('<tr class="total-row">')
    add('<td colspan="8" class="right"><strong>Totais:</strong></td>')
    add('<td class="right"><strong>' + _format_decimal(str(total_prod)) + '</strong></td>')
    add('<td class="right"><strong>' + _format_decimal(totais.get('base_icms', '0')) + '</strong></td>')
    add('<td class="right"><strong>' + _format_decimal(str(total_icms)) + '</strong></td>')
    add('<td></td>')
    add('<td></td>')
    add('</tr>')

    add('</tbody>')
    add('</table>')
    add('</div>')

    # Additional info
    if info:
        add('<div class="frame">')
        add('<span class="frame-title">Informações Complementares</span>')
        add('<div class="value" style="white-space:pre-wrap">' + info + '</div>')
        add('</div>')

    # Totals summary
    add('<div class="frame">')
    add('<span class="frame-title">Resumo dos Valores</span>')
    add('<div class="row">')
    add('<div class="col"><div class="label">VALOR PRODUTOS</div><div class="value right value-lg">' + _format_decimal(totais.get('valor_produtos', '0')) + '</div></div>')
    add('<div class="col"><div class="label">VALOR FRETE</div><div class="value right">' + _format_decimal(totais.get('valor_frete', '0')) + '</div></div>')
    add('<div class="col"><div class="label">VALOR SEGURO</div><div class="value right">' + _format_decimal(totais.get('valor_seguro', '0')) + '</div></div>')
    add('<div class="col"><div class="label">DESCONTO</div><div class="value right">' + _format_decimal(totais.get('valor_desconto', '0')) + '</div></div>')
    add('<div class="col"><div class="label">OUTRAS DESPESAS</div><div class="value right">' + _format_decimal(totais.get('outras_despesas', '0')) + '</div></div>')
    add('<div class="col"><div class="label">VALOR TOTAL</div><div class="value right value-lg">' + _format_decimal(totais.get('valor_total', '0')) + '</div></div>')
    add('</div>')
    add('</div>')

    # Signature area
    add('<div class="row" style="margin-top:2mm">')
    add('<div class="col" style="margin-right:1mm">')
    add('<div class="signature-box">')
    add('<div class="signature-label">RECEBEMOS DE ' + emit.get('nome', '') + '</div>')
    add('<div class="signature-line"></div>')
    add('<div style="font-size:7px;text-align:center;margin-top:2mm">DATA DE RECEBIMENTO</div>')
    add('<div class="signature-label" style="margin-top:5mm">IDENTIFICAÇÃO E ASSINATURA DO RECEBEDOR</div>')
    add('</div>')
    add('</div>')
    add('<div class="col" style="margin-left:1mm">')
    add('<div class="signature-box">')
    add('<div style="font-size:7px;text-align:center;margin-top:8mm">DOCUMENTO AUXILIAR DA NOTA FISCAL ELETRÔNICA</div>')
    add('<div style="font-size:7px;text-align:center">Não possui valor fiscal. A autenticidade deve ser verificada no site da SEFAZ.</div>')
    add('</div>')
    add('</div>')
    add('</div>')

    # Barcode representation
    add('<div class="frame" style="margin-top:2mm">')
    add('<span class="frame-title">Código de Barras</span>')
    add('<div class="barcode">')
    add('<div style="font-size:8px;border:1px solid #999;padding:2mm;background:#fff;font-family:monospace;letter-spacing:2px">')
    add('| | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | | |')
    add('</div>')
    add('<div class="barcode-text">' + _format_chave(nfe_data.get('chave_acesso', '')) + '</div>')
    add('</div>')
    add('</div>')

    # Footer
    add('<div class="consulta">')
    add('DANFE - Documento Auxiliar da Nota Fiscal Eletrônica - ' + company_name + '<br>')
    add('Gerado em ' + datetime.now().strftime('%d/%m/%Y %H:%M:%S') + ' via ERPClaw Region BR')
    add('</div>')

    add('</div>')
    add('</body></html>')

    return '\n'.join(html_parts)


def _extract_nfe_full(nfe_row, items_rows):
    """Build full NF-e data dict from database rows for DANFE generation."""
    data = {
        'chave_acesso': nfe_row[1],
        'numero_nfe': nfe_row[2],
        'serie': nfe_row[3],
        'modelo': nfe_row[4],
        'data_emissao': nfe_row[5],
        'natureza_operacao': nfe_row[9],
        'emitente': {
            'cnpj': nfe_row[6],
            'nome': nfe_row[7],
            'ie': nfe_row[8],
        },
        'destinatario': {},
        'totais': {
            'valor_total': nfe_row[11] or '0.00',
            'valor_produtos': nfe_row[12] or '0.00',
            'base_icms': nfe_row[13] or '0.00',
            'valor_icms': nfe_row[14] or '0.00',
            'base_icms_st': nfe_row[15] or '0.00',
            'valor_icms_st': nfe_row[16] or '0.00',
            'valor_ipi': nfe_row[17] or '0.00',
            'valor_pis': nfe_row[18] or '0.00',
            'valor_cofins': nfe_row[19] or '0.00',
            'valor_frete': nfe_row[20] or '0.00',
            'valor_seguro': nfe_row[21] or '0.00',
            'valor_desconto': nfe_row[22] or '0.00',
            'outras_despesas': nfe_row[23] or '0.00',
        },
        'transporte': {},
        'informacoes_adicionais': '',
        'data_saida': '',
        'hora_saida': '',
        'items': [],
    }

    for item in items_rows:
        data['items'].append({
            'numero_item': item[0],
            'codigo_produto': item[1],
            'descricao': item[2],
            'ncm': item[3],
            'cfop': item[4],
            'cst_icms': item[5],
            'unidade': item[6],
            'quantidade': item[7] or '0',
            'valor_unitario': item[8] or '0.00',
            'valor_total': item[9] or '0.00',
            'base_icms': item[11] or '0.00',
            'aliquota_icms': item[12] or '0.00',
            'valor_icms': item[13] or '0.00',
            'valor_ipi': item[16] or '0.00',
            'aliquota_ipi': item[15] or '0.00',
            'valor_pis': item[17] or '0.00',
            'valor_cofins': item[19] or '0.00',
        })

    return data


def _parse_nfe_full_from_xml(xml_content):
    """Parse NF-e XML and extract all fields needed for DANFE."""
    if not HAS_LXML:
        return None, "lxml not installed"

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
            base_xpath, attr_name = xpath_str.rsplit('/@', 1)
            found = el.find(base_xpath, ns)
            return found.attrib.get(attr_name, default) if found is not None else default
        found = el.find(xpath_str, ns)
        return found.text or default if found is not None else default

    def _decimal(el, xpath, default='0.00'):
        val = _text(el, xpath, default)
        return val if val else default

    # Extract basic data using existing parser
    flat, error = _parse_nfe_xml(xml_content)
    if error:
        return None, error

    # Restructure flat keys into nested format expected by DANFE generator
    data = {
        'chave_acesso': flat.get('chave_acesso', ''),
        'numero_nfe': flat.get('numero_nfe', ''),
        'serie': flat.get('serie', ''),
        'modelo': flat.get('modelo', ''),
        'data_emissao': flat.get('data_emissao', ''),
        'natureza_operacao': flat.get('natureza_operacao', ''),
        'emitente': {
            'cnpj': flat.get('emitente_cnpj', ''),
            'nome': flat.get('emitente_nome', ''),
            'ie': flat.get('emitente_ie', ''),
        },
        'totais': {
            'valor_total': flat.get('valor_total', '0.00'),
            'valor_produtos': flat.get('valor_produtos', '0.00'),
            'base_icms': flat.get('base_icms', '0.00'),
            'valor_icms': flat.get('valor_icms', '0.00'),
            'base_icms_st': flat.get('base_icms_st', '0.00'),
            'valor_icms_st': flat.get('valor_icms_st', '0.00'),
            'valor_ipi': flat.get('valor_ipi', '0.00'),
            'valor_pis': flat.get('valor_pis', '0.00'),
            'valor_cofins': flat.get('valor_cofins', '0.00'),
            'valor_frete': flat.get('valor_frete', '0.00'),
            'valor_seguro': flat.get('valor_seguro', '0.00'),
            'valor_desconto': flat.get('valor_desconto', '0.00'),
            'outras_despesas': flat.get('outras_despesas', '0.00'),
        },
        'items': flat.get('items', []),
        'destinatario': {},
        'transporte': {},
        'informacoes_adicionais': '',
        'data_saida': '',
        'hora_saida': '',
    }

    # Add destinatário
    dest = root.find('.//nfe:dest', ns)
    if dest is not None:
        ender_dest = dest.find('nfe:enderDest', ns)
        data['destinatario'] = {
            'cnpj': _text(dest, 'nfe:CNPJ', '') or _text(dest, 'nfe:CPF', ''),
            'nome': _text(dest, 'nfe:xNome', ''),
            'ie': _text(dest, 'nfe:IE', ''),
            'logradouro': _text(ender_dest, 'nfe:xLgr', '') if ender_dest is not None else '',
            'numero': _text(ender_dest, 'nfe:nro', '') if ender_dest is not None else '',
            'bairro': _text(ender_dest, 'nfe:xBairro', '') if ender_dest is not None else '',
            'cep': _text(ender_dest, 'nfe:CEP', '') if ender_dest is not None else '',
            'municipio': _text(ender_dest, 'nfe:xMun', '') if ender_dest is not None else '',
            'uf': _text(ender_dest, 'nfe:UF', '') if ender_dest is not None else '',
        }
    else:
        data['destinatario'] = {}

    # Add transporte
    transp = root.find('.//nfe:transp', ns)
    if transp is not None:
        transporta = transp.find('nfe:transporta', ns)
        vol = transp.find('nfe:vol', ns)
        mod_frete_map = {'0': '0 - Emitente', '1': '1 - Destinatário', '2': '2 - Terceiros', '3': '3 - Próprio por conta do remetente', '9': '9 - Sem transporte'}
        data['transporte'] = {
            'modalidade_frete': mod_frete_map.get(_text(transp, 'nfe:modFrete', '9'), '9 - Sem transporte'),
            'nome': _text(transporta, 'nfe:xNome', '') if transporta is not None else '',
            'cnpj': _text(transporta, 'nfe:CNPJ', '') if transporta is not None else '',
            'ie': _text(transporta, 'nfe:IE', '') if transporta is not None else '',
            'endereco': _text(transporta, 'nfe:xEnder', '') if transporta is not None else '',
            'municipio': _text(transporta, 'nfe:xMun', '') if transporta is not None else '',
            'uf': _text(transporta, 'nfe:UF', '') if transporta is not None else '',
            'placa': '',
            'uf_veiculo': '',
            'qtd_volumes': _text(vol, 'nfe:qVol', '') if vol is not None else '',
            'especie': _text(vol, 'nfe:esp', '') if vol is not None else '',
            'marca': _text(vol, 'nfe:marca', '') if vol is not None else '',
            'numeracao': _text(vol, 'nfe:nVol', '') if vol is not None else '',
            'peso_bruto': _text(vol, 'nfe:pesoB', '') if vol is not None else '',
            'peso_liquido': _text(vol, 'nfe:pesoL', '') if vol is not None else '',
        }
        # Veiculo (reboque or veicTransp)
        veic = transp.find('nfe:veicTransp', ns)
        if veic is not None:
            data['transporte']['placa'] = _text(veic, 'nfe:placa', '')
            data['transporte']['uf_veiculo'] = _text(veic, 'nfe:UF', '')
    else:
        data['transporte'] = {}

    # Additional info
    inf_ad = root.find('.//nfe:infAdic', ns)
    if inf_ad is not None:
        inf_cpl = _text(inf_ad, 'nfe:infCpl', '')
        data['informacoes_adicionais'] = inf_cpl
    else:
        data['informacoes_adicionais'] = ''

    # Data de saída
    ide = root.find('.//nfe:ide', ns)
    if ide is not None:
        data['data_saida'] = _text(ide, 'nfe:dSaiEnt', '')
        data['hora_saida'] = _text(ide, 'nfe:hSaiEnt', '')

    return data, None


def generate_danfe(conn, args):
    """Generate DANFE (HTML) from NF-e XML file or imported record."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")

    output_path = args.danfe_output or args.output_dir
    nfe_data = None
    source = ""

    # Get company name
    company = conn.execute(
        "SELECT name FROM company WHERE id = ?", (company_id,)
    ).fetchone()
    company_name = company[0] if company else ""

    # Option 1: From imported NF-e by ID
    if args.nfe_import_id:
        nfe_row = conn.execute("""
            SELECT id, chave_acesso, numero_nfe, serie, modelo, data_emissao,
                   emitente_cnpj, emitente_nome, emitente_ie,
                   natureza_operacao, cfop_principal,
                   valor_total, valor_produtos,
                   base_icms, valor_icms, base_icms_st, valor_icms_st,
                   valor_ipi, valor_pis, valor_cofins,
                   valor_frete, valor_seguro, valor_desconto, outras_despesas,
                   supplier_id, stock_entry_id, status, created_at
            FROM nfe_import WHERE id = ?
        """, (args.nfe_import_id,)).fetchone()

        if not nfe_row:
            return err(f"NF-e não encontrada: {args.nfe_import_id}")

        items_rows = conn.execute("""
            SELECT numero_item, codigo_produto, descricao, ncm, cfop,
                   cst_icms, unidade, quantidade, valor_unitario, valor_total,
                   valor_icms, base_icms, aliquota_icms,
                   valor_ipi, aliquota_ipi,
                   valor_pis, valor_cofins
            FROM nfe_item WHERE nfe_import_id = ?
            ORDER BY numero_item
        """, (args.nfe_import_id,)).fetchall()

        nfe_data = _extract_nfe_full(nfe_row, items_rows)
        source = f"nfe_db_{args.nfe_import_id}"

    # Option 2: From XML file
    elif args.xml_path or args.xml_content:
        xml_content = args.xml_path or args.xml_content
        nfe_data, error = _parse_nfe_full_from_xml(xml_content)
        if error:
            return err(error)
        source = "xml"

    else:
        return err("Forneça --nfe-import-id ou --xml-path para gerar o DANFE")

    # Generate HTML
    html = _generate_danfe_html(nfe_data, company_name)

    # Determine output path
    if not output_path:
        nfe_num = nfe_data.get('numero_nfe', '000000')
        output_dir = os.getcwd()
        output_path = os.path.join(output_dir, f"DANFE_NFe_{nfe_num}.html")
    elif os.path.isdir(output_path):
        nfe_num = nfe_data.get('numero_nfe', '000000')
        output_path = os.path.join(output_path, f"DANFE_NFe_{nfe_num}.html")

    # Write file
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    return ok({
        "danfe_path": output_path,
        "nfe_numero": nfe_data.get('numero_nfe', ''),
        "nfe_chave": nfe_data.get('chave_acesso', ''),
        "emitente": nfe_data.get('emitente', {}).get('nome', ''),
        "destinatario": nfe_data.get('destinatario', {}).get('nome', ''),
        "valor_total": nfe_data.get('totais', {}).get('valor_total', '0.00'),
        "total_items": len(nfe_data.get('items', [])),
        "source": source,
        "format": "html",
    })


# ---------------------------------------------------------------------------
ACTIONS = {
    "parse-nfe-xml": parse_nfe_xml,
    "import-nfe-entry": import_nfe_entry,
    "import-nfe-with-po": import_nfe_entry,  # TODO: add PO linking
    "list-nfe-imports": list_nfe_imports,
    "get-nfe-import": get_nfe_import,
    "validate-nfe-xml": validate_nfe_xml,
    "export-nfe-data": export_nfe_data,
    "generate-danfe": generate_danfe,
}
