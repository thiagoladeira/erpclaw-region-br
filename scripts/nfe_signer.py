"""NF-e XML Digital Signer — XMLDSig with A1 Certificate

Signs NFe XML according to Brazilian NF-e standards:
- Reference to infNFe element (URI="#NFe{chave}")
- SHA-256 digest (for reference), SHA-1 for SignatureMethod per SEFAZ spec
- RSA-SHA1 signature per Brazilian standard
- X509 certificate embedded in KeyInfo

Requirements: cryptography, lxml, base64, struct

Library module: no direct ACTIONS — used by nfe_emission.py.
"""
from __future__ import annotations

import base64
import os
import re
import sys
from datetime import datetime

# ── Optional dependency checks ──────────────────────────────────────────
HAS_CRYPTO = False
HAS_LXML = False

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.backends import default_backend
    HAS_CRYPTO = True
except ImportError:
    pass

try:
    from lxml import etree
    HAS_LXML = True
except ImportError:
    pass


# ── XMLDSig Constants ──────────────────────────────────────────────────
DSIG_NS = "http://www.w3.org/2000/09/xmldsig#"
NFE_NS = "http://www.portalfiscal.inf.br/nfe"

C14N_METHOD = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
SIG_METHOD_RSA_SHA1 = "http://www.w3.org/2000/09/xmldsig#rsa-sha1"
DIGEST_METHOD_SHA1 = "http://www.w3.org/2000/09/xmldsig#sha1"
TRANSFORM_ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"
TRANSFORM_C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"


# ── Public API ─────────────────────────────────────────────────────────

def sign_nfe_xml(xml_content: str, pfx_path: str, pfx_password: str) -> str | None:
    """Sign an NFe XML document using an A1 certificate (PFX/P12).

    Args:
        xml_content: The complete NFe XML string (unsigned).
        pfx_path: Path to the .pfx or .p12 certificate file.
        pfx_password: Password for the certificate.

    Returns:
        Signed NFe XML string, or None on failure.
    """
    if not HAS_CRYPTO:
        raise ImportError(
            "cryptography library required for XML signing. "
            "Install: pip install cryptography"
        )
    if not HAS_LXML:
        raise ImportError(
            "lxml library required for XML signing. "
            "Install: pip install lxml"
        )
    if not os.path.isfile(pfx_path):
        raise FileNotFoundError(f"Certificate file not found: {pfx_path}")

    # Load certificate and private key from PFX
    cert, private_key = _load_pfx(pfx_path, pfx_password)

    # Extract chave_acesso for reference URI
    chave = _extract_chave_acesso(xml_content)
    if not chave:
        raise ValueError("Could not extract chave_acesso from XML content")

    # Parse XML
    root = etree.fromstring(xml_content.encode("utf-8"))

    # Locate infNFe element
    ns_map = {"nfe": NFE_NS}
    inf_nfe = root.find(".//nfe:infNFe", ns_map)
    if inf_nfe is None:
        raise ValueError("infNFe element not found in XML")

    # Build the <Signature> element
    signature = _build_signature(inf_nfe, chave, cert, private_key)

    # Append <Signature> as last child of <infNFe>
    inf_nfe.append(signature)

    # Serialize back to string
    signed_xml = etree.tostring(
        root, encoding="unicode", xml_declaration=True, pretty_print=False
    )
    return signed_xml


def sign_nfe_event_xml(xml_content: str, pfx_path: str,
                       pfx_password: str) -> str | None:
    """Sign an NF-e event XML (cancelamento, CC-e, inutilização).

    Same signing logic but for evento XML.
    """
    if not HAS_CRYPTO or not HAS_LXML:
        raise ImportError("cryptography and lxml required")

    cert, private_key = _load_pfx(pfx_path, pfx_password)

    # Parse XML
    root = etree.fromstring(xml_content.encode("utf-8"))

    # Find evento element
    evento = root.find(".//{http://www.portalfiscal.inf.br/nfe}evento")
    inf_evento = root.find(".//{http://www.portalfiscal.inf.br/nfe}infEvento")
    if evento is None or inf_evento is None:
        raise ValueError("evento/infEvento not found in XML")

    evento_id = inf_evento.get("Id", "")
    if not evento_id:
        raise ValueError("Missing infEvento@Id")

    signature = _build_signature(evento, evento_id, cert, private_key)
    evento.append(signature)

    return etree.tostring(
        root, encoding="unicode", xml_declaration=True, pretty_print=False
    )


# ── Certificate Loading ───────────────────────────────────────────────

def _load_pfx(pfx_path: str, pfx_password: str):
    """Load A1 certificate and private key from PFX/P12 file."""
    with open(pfx_path, "rb") as f:
        pfx_data = f.read()

    from cryptography.hazmat.primitives.serialization import pkcs12

    private_key, cert, additional_certs = pkcs12.load_key_and_certificates(
        pfx_data,
        pfx_password.encode("utf-8") if pfx_password else b"",
        backend=default_backend()
    )

    if private_key is None:
        raise ValueError("No private key found in certificate")

    return cert, private_key


# ── XMLDSig Construction ──────────────────────────────────────────────

def _build_signature(parent_element, ref_id: str,
                     cert, private_key) -> "etree.Element":
    """Build the complete XMLDSig <Signature> element.

    Args:
        parent_element: The element to sign (infNFe or evento).
        ref_id: The URI reference string (e.g. "#NFe...", "#ID...").
        cert: X509 certificate object.
        private_key: RSA private key.
    """
    # Extract cert in DER format for X509Certificate element
    cert_der = cert.public_bytes(serialization.Encoding.DER)
    cert_b64 = base64.b64encode(cert_der).decode("ascii")

    # Build <Signature> element
    signature = etree.Element(f"{{{DSIG_NS}}}Signature")

    # --- SignedInfo ---
    signed_info = etree.SubElement(signature, f"{{{DSIG_NS}}}SignedInfo")

    # CanonicalizationMethod
    c14n_method = etree.SubElement(signed_info, f"{{{DSIG_NS}}}CanonicalizationMethod")
    c14n_method.set("Algorithm", C14N_METHOD)

    # SignatureMethod (RSA-SHA1 per Brazilian standard)
    sig_method = etree.SubElement(signed_info, f"{{{DSIG_NS}}}SignatureMethod")
    sig_method.set("Algorithm", SIG_METHOD_RSA_SHA1)

    # Reference
    reference = etree.SubElement(signed_info, f"{{{DSIG_NS}}}Reference")
    reference.set("URI", f"#{ref_id}")

    # Transforms
    transforms = etree.SubElement(reference, f"{{{DSIG_NS}}}Transforms")
    t1 = etree.SubElement(transforms, f"{{{DSIG_NS}}}Transform")
    t1.set("Algorithm", TRANSFORM_ENVELOPED)
    t2 = etree.SubElement(transforms, f"{{{DSIG_NS}}}Transform")
    t2.set("Algorithm", TRANSFORM_C14N)

    # DigestMethod (SHA-1 per Brazilian standard)
    digest_method = etree.SubElement(reference, f"{{{DSIG_NS}}}DigestMethod")
    digest_method.set("Algorithm", DIGEST_METHOD_SHA1)

    # DigestValue — compute over the canonicalized parent_element
    digest_value = _compute_digest(parent_element)
    digest_value_elem = etree.SubElement(reference, f"{{{DSIG_NS}}}DigestValue")
    digest_value_elem.text = digest_value

    # --- SignatureValue ---
    sig_value_b64 = _compute_signature(signed_info, private_key)
    sig_value_elem = etree.SubElement(signature, f"{{{DSIG_NS}}}SignatureValue")
    sig_value_elem.text = sig_value_b64

    # --- KeyInfo ---
    key_info = etree.SubElement(signature, f"{{{DSIG_NS}}}KeyInfo")
    x509_data = etree.SubElement(key_info, f"{{{DSIG_NS}}}X509Data")
    x509_cert = etree.SubElement(x509_data, f"{{{DSIG_NS}}}X509Certificate")
    x509_cert.text = cert_b64

    return signature


def _compute_digest(element: "etree.Element") -> str:
    """Compute SHA-1 digest of the canonicalized element.

    Brazilian NF-e standard uses SHA-1 for the reference digest.
    """
    # Canonicalize the element (C14N exclusive WITHOUT comments)
    c14n_xml = etree.tostring(element, method="c14n", exclusive=True, with_comments=False)

    # SHA-1 digest
    sha1 = hashes.Hash(hashes.SHA1(), backend=default_backend())
    sha1.update(c14n_xml)
    digest = sha1.finalize()

    return base64.b64encode(digest).decode("ascii")


def _compute_signature(signed_info: "etree.Element", private_key) -> str:
    """Compute RSA-SHA1 signature of the SignedInfo element."""
    # Canonicalize SignedInfo
    c14n_si = etree.tostring(
        signed_info, method="c14n", exclusive=True, with_comments=False
    )

    # Sign with RSA-SHA1
    signature_bytes = private_key.sign(
        c14n_si,
        padding.PKCS1v15(),
        hashes.SHA1()
    )

    return base64.b64encode(signature_bytes).decode("ascii")


# ── XML Helpers ───────────────────────────────────────────────────────

def _extract_chave_acesso(xml_content: str) -> str:
    """Extract chave_acesso from the infNFe@Id attribute."""
    match = re.search(r'Id="NFe(\d{44})"', xml_content)
    if match:
        return match.group(1)

    # Try with lxml
    if HAS_LXML:
        root = etree.fromstring(xml_content.encode("utf-8"))
        ns_map = {"nfe": NFE_NS}
        inf_nfe = root.find(".//nfe:infNFe", ns_map)
        if inf_nfe is not None:
            id_attr = inf_nfe.get("Id", "")
            if id_attr.startswith("NFe"):
                return id_attr[3:]

    return ""


# ── Certificate Validation Helpers ────────────────────────────────────

def validate_certificate(pfx_path: str, pfx_password: str) -> dict:
    """Validate a PFX certificate: check expiry, CN, etc.

    Returns dict with cert info on success.
    """
    try:
        cert, _ = _load_pfx(pfx_path, pfx_password)
    except Exception as e:
        return {"valid": False, "error": str(e)}

    subject = cert.subject
    cn = ""
    for attr in subject:
        if attr.oid._name == "commonName":
            cn = attr.value
            break

    not_after = cert.not_valid_after_utc.isoformat() if hasattr(
        cert, "not_valid_after_utc"
    ) else cert.not_valid_after.isoformat()

    not_before = cert.not_valid_before_utc.isoformat() if hasattr(
        cert, "not_valid_before_utc"
    ) else cert.not_valid_before.isoformat()

    is_expired = datetime.now() > (
        cert.not_valid_after_utc if hasattr(cert, "not_valid_after_utc")
        else cert.not_valid_after.replace(tzinfo=None)
    )

    issuer_cn = ""
    for attr in cert.issuer:
        if attr.oid._name == "commonName":
            issuer_cn = attr.value
            break

    return {
        "valid": not is_expired,
        "expired": is_expired,
        "subject_cn": cn,
        "issuer_cn": issuer_cn,
        "not_before": not_before,
        "not_after": not_after,
        "serial_number": str(cert.serial_number),
    }


# ── ACTIONS ────────────────────────────────────────────────────────────

# ── Shared Certificate Loading (public API) ──────────────────────────

def _load_certificate(pfx_path: str, password: str):
    """Load private key and certificate from PKCS#12 file.

    Returns (private_key, certificate).
    Used by ecd.py, ecf.py, and nfse.py for SPED digital signing.
    """
    from cryptography.hazmat.primitives.serialization import pkcs12

    with open(pfx_path, 'rb') as f:
        pfx_data = f.read()

    private_key, certificate, _ = pkcs12.load_key_and_certificates(
        pfx_data,
        password.encode() if password else b"",
        backend=default_backend()
    )
    return private_key, certificate


ACTIONS: dict = {}
