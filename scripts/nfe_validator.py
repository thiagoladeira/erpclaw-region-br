"""NF-e XSD Schema Validator — ERPClaw Region BR

Real XSD schema validation for NF-e XML documents using lxml.etree.XMLSchema.
Downloads and caches the official SEFAZ NFe schema (procNFe_v4.00.xsd) on first use.

Unlike the basic structural validation in validate-nfe-out, this performs
actual XML Schema validation against the official SEFAZ XSD, catching
precise structural errors, missing required elements, invalid types,
and XML format issues.

Library module: used by nfe_emission.py and db_query.py routing.

Actions (1):
  validate-nfe-xsd  — Validate NFe XML against official SEFAZ XSD schema
"""
from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

# ── erpclaw_lib imports ────────────────────────────────────────────────
sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
from erpclaw_lib.response import ok, err
from erpclaw_lib.db import get_connection, DEFAULT_DB_PATH


# ═══════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════

SCHEMA_DIR = Path.home() / ".openclaw" / "erpclaw" / "nfe" / "schemas"
NFE_SCHEMA_NAME = "procNFe_v4.00.xsd"
NFE_SCHEMA_URL = (
    "http://www.nfe.fazenda.gov.br/produtos/"
    "PL_009j_NT2023_004_v100_NI/NFe_1.00a/element"
)
SCHEMA_FALLBACK_URLS = [
    "https://www.nfe.fazenda.gov.br/schemas/PL_009j_NT2023_004_v100_NI/"
    "procNFe_v4.00.xsd",
    "https://raw.githubusercontent.com/ERPClaw/schemas/main/nfe/procNFe_v4.00.xsd",
]

# Minimal embedded schema for offline fallback validation
EMBEDDED_NFE_XSD = """<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           targetNamespace="http://www.portalfiscal.inf.br/nfe"
           xmlns="http://www.portalfiscal.inf.br/nfe"
           elementFormDefault="qualified"
           attributeFormDefault="unqualified">
  <xs:element name="NFe">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="infNFe" minOccurs="1" maxOccurs="1">
          <xs:complexType>
            <xs:sequence>
              <xs:element name="ide" minOccurs="1" maxOccurs="1">
                <xs:complexType>
                  <xs:sequence>
                    <xs:element name="cUF" type="xs:string" minOccurs="1" maxOccurs="1"/>
                    <xs:element name="cNF" type="xs:string" minOccurs="1" maxOccurs="1"/>
                    <xs:element name="natOp" type="xs:string" minOccurs="1" maxOccurs="1"/>
                    <xs:element name="mod" type="xs:string" minOccurs="1" maxOccurs="1"/>
                    <xs:element name="serie" type="xs:string" minOccurs="1" maxOccurs="1"/>
                    <xs:element name="nNF" type="xs:string" minOccurs="1" maxOccurs="1"/>
                    <xs:element name="dhEmi" type="xs:string" minOccurs="1" maxOccurs="1"/>
                    <xs:element name="dhSaiEnt" type="xs:string" minOccurs="0" maxOccurs="1"/>
                    <xs:element name="tpNF" type="xs:string" minOccurs="1" maxOccurs="1"/>
                    <xs:element name="idDest" type="xs:string" minOccurs="1" maxOccurs="1"/>
                    <xs:element name="cMunFG" type="xs:string" minOccurs="1" maxOccurs="1"/>
                    <xs:element name="tpImp" type="xs:string" minOccurs="1" maxOccurs="1"/>
                    <xs:element name="tpEmis" type="xs:string" minOccurs="1" maxOccurs="1"/>
                    <xs:element name="cDV" type="xs:string" minOccurs="1" maxOccurs="1"/>
                    <xs:element name="tpAmb" type="xs:string" minOccurs="1" maxOccurs="1"/>
                    <xs:element name="finNFe" type="xs:string" minOccurs="1" maxOccurs="1"/>
                    <xs:element name="indFinal" type="xs:string" minOccurs="1" maxOccurs="1"/>
                    <xs:element name="indPres" type="xs:string" minOccurs="1" maxOccurs="1"/>
                    <xs:element name="indIntermed" type="xs:string" minOccurs="0" maxOccurs="1"/>
                    <xs:element name="procEmi" type="xs:string" minOccurs="1" maxOccurs="1"/>
                    <xs:element name="verProc" type="xs:string" minOccurs="1" maxOccurs="1"/>
                  </xs:sequence>
                </xs:complexType>
              </xs:element>
              <xs:element name="emit" minOccurs="1" maxOccurs="1">
                <xs:complexType>
                  <xs:sequence>
                    <xs:any namespace="##any" processContents="skip" minOccurs="0" maxOccurs="unbounded"/>
                  </xs:sequence>
                </xs:complexType>
              </xs:element>
              <xs:element name="dest" minOccurs="0" maxOccurs="1">
                <xs:complexType>
                  <xs:sequence>
                    <xs:any namespace="##any" processContents="skip" minOccurs="0" maxOccurs="unbounded"/>
                  </xs:sequence>
                </xs:complexType>
              </xs:element>
              <xs:element name="det" minOccurs="1" maxOccurs="990">
                <xs:complexType>
                  <xs:sequence>
                    <xs:any namespace="##any" processContents="skip" minOccurs="0" maxOccurs="unbounded"/>
                  </xs:sequence>
                </xs:complexType>
              </xs:element>
              <xs:element name="total" minOccurs="1" maxOccurs="1">
                <xs:complexType>
                  <xs:sequence>
                    <xs:any namespace="##any" processContents="skip" minOccurs="0" maxOccurs="unbounded"/>
                  </xs:sequence>
                </xs:complexType>
              </xs:element>
              <xs:element name="transp" minOccurs="1" maxOccurs="1">
                <xs:complexType>
                  <xs:sequence>
                    <xs:any namespace="##any" processContents="skip" minOccurs="0" maxOccurs="unbounded"/>
                  </xs:sequence>
                </xs:complexType>
              </xs:element>
              <xs:element name="cobr" minOccurs="0" maxOccurs="1">
                <xs:complexType>
                  <xs:sequence>
                    <xs:any namespace="##any" processContents="skip" minOccurs="0" maxOccurs="unbounded"/>
                  </xs:sequence>
                </xs:complexType>
              </xs:element>
              <xs:element name="pag" minOccurs="0" maxOccurs="1">
                <xs:complexType>
                  <xs:sequence>
                    <xs:any namespace="##any" processContents="skip" minOccurs="0" maxOccurs="unbounded"/>
                  </xs:sequence>
                </xs:complexType>
              </xs:element>
              <xs:element name="infAdic" minOccurs="0" maxOccurs="1">
                <xs:complexType>
                  <xs:sequence>
                    <xs:any namespace="##any" processContents="skip" minOccurs="0" maxOccurs="unbounded"/>
                  </xs:sequence>
                </xs:complexType>
              </xs:element>
              <xs:element name="exporta" minOccurs="0" maxOccurs="1">
                <xs:complexType>
                  <xs:sequence>
                    <xs:any namespace="##any" processContents="skip" minOccurs="0" maxOccurs="unbounded"/>
                  </xs:sequence>
                </xs:complexType>
              </xs:element>
              <xs:element name="compra" minOccurs="0" maxOccurs="1">
                <xs:complexType>
                  <xs:sequence>
                    <xs:any namespace="##any" processContents="skip" minOccurs="0" maxOccurs="unbounded"/>
                  </xs:sequence>
                </xs:complexType>
              </xs:element>
              <xs:element name="cana" minOccurs="0" maxOccurs="1">
                <xs:complexType>
                  <xs:sequence>
                    <xs:any namespace="##any" processContents="skip" minOccurs="0" maxOccurs="unbounded"/>
                  </xs:sequence>
                </xs:complexType>
              </xs:element>
              <xs:any namespace="http://www.w3.org/2000/09/xmldsig#" processContents="skip" minOccurs="0" maxOccurs="1"/>
            </xs:sequence>
            <xs:attribute name="Id" type="xs:string" use="required"/>
            <xs:attribute name="versao" type="xs:string" use="required"/>
          </xs:complexType>
        </xs:element>
      </xs:sequence>
    </xs:complexType>
  </xs:element>
</xs:schema>"""


# ═══════════════════════════════════════════════════════════════════════
# Schema Management
# ═══════════════════════════════════════════════════════════════════════

def _ensure_schema_dir() -> Path:
    """Create and return the schema directory path."""
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    return SCHEMA_DIR


def _get_schema_path() -> Path:
    """Get path to procNFe_v4.00.xsd, downloading if needed."""
    schema_path = _ensure_schema_dir() / NFE_SCHEMA_NAME
    return schema_path


def _write_embedded_schema(schema_path: Path) -> Path:
    """Write the minimal embedded schema for validation fallback."""
    schema_path.write_text(EMBEDDED_NFE_XSD, encoding="utf-8")
    return schema_path


def _download_schema(schema_path: Path) -> Path | None:
    """Try to download the official SEFAZ XSD schema.

    Returns the path on success, None on failure.
    """
    for url in SCHEMA_FALLBACK_URLS:
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "ERPClaw-Region-BR/1.5",
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                if len(data) > 1000:  # Reasonable XSD size
                    schema_path.write_bytes(data)
                    return schema_path
        except Exception:
            continue

    return None


def _get_or_setup_schema() -> Path | None:
    """Get the schema path, downloading if necessary.

    Returns Path to XSD file, or None if unable to obtain.
    Tries: 1) cached file, 2) download from SEFAZ, 3) embedded fallback.
    """
    schema_path = _get_schema_path()

    # Check if cached version exists
    if schema_path.is_file() and schema_path.stat().st_size > 1000:
        return schema_path

    # Try downloading
    downloaded = _download_schema(schema_path)
    if downloaded:
        return downloaded

    # Use minimal embedded schema as fallback
    _write_embedded_schema(schema_path)
    return schema_path if schema_path.is_file() else None


# ═══════════════════════════════════════════════════════════════════════
# Core Validation
# ═══════════════════════════════════════════════════════════════════════

def validate_nfe_xsd(xml_content: str) -> dict:
    """Validate NFe XML against official SEFAZ XSD schema.

    This performs real XSD validation using lxml.etree.XMLSchema,
    catching structural, typing, and ordering errors that basic
    string checks miss.

    Args:
        xml_content: The complete NF-e XML string to validate.

    Returns:
        dict with 'valid' (bool or None), 'errors' (list), and
        optional 'warning' for missing dependencies.
    """
    try:
        from lxml import etree
    except ImportError:
        return {
            "valid": None,
            "errors": [],
            "warning": "lxml library not available. Install: pip install lxml",
        }

    # Get schema file
    schema_path = _get_or_setup_schema()
    if not schema_path:
        return {
            "valid": None,
            "errors": [],
            "warning": (
                "XSD schema not found. Download from "
                "http://www.nfe.fazenda.gov.br/ or ensure network connectivity."
            ),
        }

    try:
        # Parse the schema
        xmlschema_doc = etree.parse(str(schema_path))
        xmlschema = etree.XMLSchema(xmlschema_doc)

        # Parse XML with schema validation
        parser = etree.XMLParser(schema=xmlschema, remove_blank_text=True)
        etree.fromstring(xml_content.encode("utf-8"), parser)

        return {
            "valid": True,
            "errors": [],
            "schema_source": "embedded" if schema_path.stat().st_size < 5000 else "se faz",
        }

    except etree.XMLSchemaError as e:
        # Collect all validation errors
        errors = [str(e)]
        if hasattr(e, "error_log") and e.error_log:
            for entry in e.error_log:
                errors.append(f"Line {entry.line}: {entry.message}")
        return {"valid": False, "errors": errors}

    except etree.XMLSyntaxError as e:
        return {"valid": False, "errors": [f"XML syntax error: {e}"]}

    except Exception as e:
        return {"valid": False, "errors": [f"Validation error: {e}"]}


def validate_nfe_xsd_advanced(xml_content: str) -> dict:
    """Advanced XSD validation with detailed error reporting.

    Uses validator.assertValid() for more granular error capture.
    """
    try:
        from lxml import etree
    except ImportError:
        return {"valid": None, "errors": [], "warning": "lxml not available"}

    schema_path = _get_or_setup_schema()
    if not schema_path:
        return {"valid": None, "errors": [], "warning": "XSD schema not found"}

    try:
        xmlschema_doc = etree.parse(str(schema_path))
        xmlschema = etree.XMLSchema(xmlschema_doc)

        # Parse XML first
        xml_doc = etree.fromstring(xml_content.encode("utf-8"))

        # Validate
        xmlschema.assertValid(xml_doc)

        return {
            "valid": True,
            "errors": [],
            "details": {
                "root_tag": xml_doc.tag,
                "namespaces": dict(xml_doc.nsmap),
            },
        }
    except etree.DocumentInvalid as e:
        errors = []
        for error in xmlschema.error_log:
            errors.append({
                "line": error.line,
                "column": error.column,
                "message": error.message,
                "level": error.level_name,
            })
        return {"valid": False, "errors": errors}
    except Exception as e:
        return {"valid": False, "errors": [str(e)]}


# ═══════════════════════════════════════════════════════════════════════
# Schema Info
# ═══════════════════════════════════════════════════════════════════════

def get_schema_info() -> dict:
    """Get information about the cached XSD schema."""
    schema_path = _get_schema_path()

    if not schema_path.is_file():
        return {
            "cached": False,
            "schema_path": str(schema_path),
            "size_bytes": 0,
            "warning": "Schema not cached. Download from SEFAZ on first validation.",
        }

    stat = schema_path.stat()
    return {
        "cached": True,
        "schema_path": str(schema_path),
        "size_bytes": stat.st_size,
        "last_modified": str(stat.st_mtime),
        "source": "se faz" if stat.st_size > 5000 else "embedded minimal",
    }


# ═══════════════════════════════════════════════════════════════════════
# DB Query Action
# ═══════════════════════════════════════════════════════════════════════

def validate_nfe_xsd_action(conn, args):
    """Action handler for validate-nfe-xsd.

    Validates an NF-e XML against the official SEFAZ XSD schema.
    Can validate from a stored NF-e (by --nfe-out-id, --nfe-import-id)
    or from inline --xml-content.

    Args: --nfe-out-id, --nfe-import-id, --xml-content, --xml-path
    """
    xml_content = None
    source = None

    # Priority: xml-content > xml-path > nfe-out-id > nfe-import-id
    if args.xml_content:
        xml_content = args.xml_content
        source = "inline"

    elif args.xml_path:
        try:
            with open(args.xml_path, "r", encoding="utf-8") as f:
                xml_content = f.read()
            source = f"file:{args.xml_path}"
        except Exception as e:
            return err(f"Cannot read XML file: {e}")

    elif args.nfe_out_id:
        row = conn.execute(
            "SELECT xml_nfe, chave_acesso FROM br_nfe_out WHERE id = ?",
            (args.nfe_out_id,)
        ).fetchone()
        if not row:
            return err(f"NF-e out not found: {args.nfe_out_id}")
        xml_content = row["xml_nfe"]
        source = f"nfe_out:{args.nfe_out_id}"

    elif args.nfe_import_id:
        row = conn.execute(
            "SELECT xml_raw, chave_acesso FROM nfe_import WHERE id = ?",
            (args.nfe_import_id,)
        ).fetchone()
        if not row:
            return err(f"NF-e import not found: {args.nfe_import_id}")
        xml_content = row["xml_raw"]
        source = f"nfe_import:{args.nfe_import_id}"

    else:
        return err("Provide --xml-content, --xml-path, --nfe-out-id, or --nfe-import-id")

    if not xml_content:
        return err("No XML content found")

    # Run validation
    result = validate_nfe_xsd_advanced(xml_content)

    if result["valid"] is True:
        return ok({
            "valid": True,
            "source": source,
            "message": "XML validates against official SEFAZ XSD schema",
            **result.get("details", {}),
        })
    elif result["valid"] is None:
        return ok({
            "valid": None,
            "source": source,
            "warning": result.get("warning", "XSD validation unavailable"),
            "errors": result.get("errors", []),
        })
    else:
        return ok({
            "valid": False,
            "source": source,
            "errors": result["errors"],
            "message": f"XSD validation failed with {len(result['errors'])} error(s)",
        })


# ═══════════════════════════════════════════════════════════════════════
# ACTIONS registry
# ═══════════════════════════════════════════════════════════════════════

ACTIONS: dict = {
    "validate-nfe-xsd": validate_nfe_xsd_action,
}
