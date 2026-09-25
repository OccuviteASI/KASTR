"""KASTR local TLS (0.8.9): a per-install certificate authority and a server
certificate signed by it, so phones on the LAN can open the web UI and the
relay's WebSocket over HTTPS after trusting the CA once.

Why a CA and not the relay's fingerprint trick: the @moq library pins a
self-signed relay certificate by SHA-256 only for WebTransport on http://
URLs. A page served over https cannot use http:// relays (mixed content) and
iOS has no WebTransport at all, so the phone path is wss:// with ordinary
chain validation -- which needs a root the phone trusts.

Files live in <state_dir>/tls: ca.key, ca.crt, server.key, server.crt,
server-chain.crt (leaf + CA, what moq-relay's `cert` wants), meta.json (the
SAN set the leaf was issued for). The leaf is reissued when the SAN set
changes (new IP address) or the CA changes. Validity: CA 10 years, leaf 800
days (Apple accepts <= 825 for user-trusted roots). Keys are P-256 ECDSA.
"""
import datetime
import hashlib
import ipaddress
import json
import os
import socket
import ssl

TLS_DIR = "tls"


def _paths(state_dir):
    d = os.path.join(state_dir, TLS_DIR)
    return {
        "dir": d,
        "ca_key": os.path.join(d, "ca.key"),
        "ca_crt": os.path.join(d, "ca.crt"),
        "key": os.path.join(d, "server.key"),
        "cert": os.path.join(d, "server.crt"),
        "chain": os.path.join(d, "server-chain.crt"),
        "meta": os.path.join(d, "meta.json"),
    }


def available():
    try:
        import cryptography  # noqa: F401
        return True
    except Exception:
        return False


def _ini_names(ini):
    """0.17.0: the operator's names for this host -- kastr.ini `tls_hostname` (the DNS
    name devices use) and `web_names` (comma list of extra SANs for the local-CA leaf)."""
    out = []
    if not ini:
        return out
    hn = str(ini.get("tls_hostname", "") or "").strip().lower()
    if hn:
        out.append(hn)
    for n in str(ini.get("web_names", "") or "").split(","):
        n = n.strip().lower()
        if n and n not in out:
            out.append(n)
    return out


def _names(extra=None, ini=None):
    names = ["localhost", "127.0.0.1"]
    try:
        hn = socket.gethostname()
        if hn:
            names.append(hn)
            names.append(hn.lower())
            names.append(hn.lower() + ".local")   # 0.17.0: mDNS name phones resolve on the LAN
    except OSError:
        pass
    for n in _ini_names(ini):                     # 0.17.0
        if n and n not in names:
            names.append(n)
    for n in extra or []:
        if n and n not in names:
            names.append(n)
    out = []
    for n in names:
        if n not in out:
            out.append(n)
    return out


def _san(names):
    from cryptography import x509
    entries = []
    for n in names:
        try:
            entries.append(x509.IPAddress(ipaddress.ip_address(n)))
        except ValueError:
            entries.append(x509.DNSName(n))
    return x509.SubjectAlternativeName(entries)


def _write(path, data, private=False):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    if private and os.name != "nt":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def _pem_key(key):
    from cryptography.hazmat.primitives import serialization
    return key.private_bytes(serialization.Encoding.PEM,
                             serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


def _pem_cert(cert):
    from cryptography.hazmat.primitives import serialization
    return cert.public_bytes(serialization.Encoding.PEM)


def _load_key(path):
    from cryptography.hazmat.primitives import serialization
    with open(path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def _load_cert(path):
    from cryptography import x509
    with open(path, "rb") as f:
        return x509.load_pem_x509_certificate(f.read())


def _ensure_ca(p):
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    if os.path.exists(p["ca_key"]) and os.path.exists(p["ca_crt"]):
        try:
            cert = _load_cert(p["ca_crt"])
            if cert.not_valid_after_utc > datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30):
                return _load_key(p["ca_key"]), cert
        except Exception:
            pass
    key = ec.generate_private_key(ec.SECP256R1())
    host = ""
    try:
        host = socket.gethostname()
    except OSError:
        pass
    name = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Autonomous Solutions, Inc."),
        x509.NameAttribute(NameOID.COMMON_NAME, ("KASTR Local CA (%s)" % host)[:64]),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                         content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    _write(p["ca_key"], _pem_key(key), private=True)
    _write(p["ca_crt"], _pem_cert(cert))
    # a new CA invalidates any leaf issued by the old one
    for k in ("key", "cert", "chain", "meta"):
        try:
            os.remove(p[k])
        except OSError:
            pass
    return key, cert


def _leaf_current(p, names, ca_cert):
    try:
        with open(p["meta"], encoding="utf-8") as f:
            meta = json.load(f)
        if sorted(meta.get("names") or []) != sorted(names):
            return False
        if meta.get("ca") != _fingerprint(ca_cert):
            return False
        cert = _load_cert(p["cert"])
        return cert.not_valid_after_utc > datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)
    except Exception:
        return False


def _issue_leaf(p, names, ca_key, ca_cert):
    from cryptography import x509
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    cn = next((n for n in names if n not in ("localhost", "127.0.0.1")), "localhost")
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Autonomous Solutions, Inc."),
                x509.NameAttribute(NameOID.COMMON_NAME, ("KASTR %s" % cn)[:64])]))
            .issuer_name(ca_cert.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=800))
            .add_extension(_san(names), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=True, content_commitment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                         crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    _write(p["key"], _pem_key(key), private=True)
    _write(p["cert"], _pem_cert(cert))
    _write(p["chain"], _pem_cert(cert) + _pem_cert(ca_cert))
    _write(p["meta"], json.dumps({"names": names, "ca": _fingerprint(ca_cert),
                                  "issued": now.isoformat()}).encode())


def _fingerprint(cert):
    from cryptography.hazmat.primitives import serialization
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def ensure(state_dir, extra_names=None, ini=None):
    """Make sure the CA and a leaf covering `extra_names` (IPs/hosts) exist.

    Returns a dict of paths plus `fingerprint` (CA, sha-256 hex) and `names`;
    None when the cryptography package is missing (source checkouts).
    0.17.0: `ini` adds tls_hostname / web_names / <hostname>.local to the SANs;
    a changed SAN set reissues the leaf under the SAME CA (phones stay trusted)."""
    if not available():
        return None
    p = _paths(state_dir)
    os.makedirs(p["dir"], exist_ok=True)
    names = _names(extra_names, ini)
    ca_key, ca_cert = _ensure_ca(p)
    if not _leaf_current(p, names, ca_cert):
        _issue_leaf(p, names, ca_key, ca_cert)
    p["fingerprint"] = _fingerprint(ca_cert)
    p["names"] = names
    p["source"] = "local-ca"
    p["hostname"] = (_ini_names(ini) or [None])[0]
    try:
        p["expires"] = _load_cert(p["cert"]).not_valid_after_utc.isoformat()
    except Exception:
        p["expires"] = None
    p["stamp"] = _stamp(p["chain"], p["key"])
    return p


def _stamp(*files):
    """sha256 over the PEM files -- the daily check compares it to notice a swap."""
    h = hashlib.sha256()
    for f in files:
        try:
            with open(f, "rb") as fh:
                h.update(fh.read())
        except OSError:
            h.update(b"-")
    return h.hexdigest()


def _cert_names(cert):
    from cryptography import x509
    out = []
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        out += [str(v) for v in san.get_values_for_type(x509.DNSName)]
        out += [str(v) for v in san.get_values_for_type(x509.IPAddress)]
    except Exception:
        pass
    return [n.lower() for n in out]


def operator_paths(state_dir, ini, log=None):
    """0.17.0: an operator-provided certificate -- kastr.ini `tls_cert` + `tls_key`
    (PEM; unencrypted key), optional `tls_chain` (intermediates). Both must load,
    or None is returned and the caller falls back to the local CA (logged once).
    The chain file KASTR and moq-relay serve is leaf + chain, written under
    <state_dir>/tls/operator-chain.crt; the key is used from where it lives."""
    if not ini or not available():
        return None
    cert_p = str(ini.get("tls_cert", "") or "").strip()
    key_p = str(ini.get("tls_key", "") or "").strip()
    if not cert_p and not key_p:
        return None
    say = log or (lambda m: None)
    if not (cert_p and key_p):
        say("tls: operator certificate needs BOTH tls_cert and tls_key in kastr.ini -- using the local CA")
        return None
    try:
        cert = _load_cert(cert_p)
        _load_key(key_p)
    except Exception as e:
        say("tls: operator certificate unusable (%s) -- using the local CA" % e)
        return None
    p = _paths(state_dir)
    os.makedirs(p["dir"], exist_ok=True)
    chain_p = str(ini.get("tls_chain", "") or "").strip()
    with open(cert_p, "rb") as f:
        leaf_pem = f.read()
    if chain_p:
        try:
            with open(chain_p, "rb") as f:
                extra = f.read()
            chain_file = os.path.join(p["dir"], "operator-chain.crt")
            _write(chain_file, leaf_pem.rstrip(b"\n") + b"\n" + extra)
        except OSError as e:
            say("tls: tls_chain unreadable (%s) -- serving the leaf alone" % e)
            chain_file = cert_p
    else:
        chain_file = cert_p
    names = _cert_names(cert)
    hostname = (_ini_names(ini) or [None])[0]
    if hostname and hostname not in names:
        say("tls: %s is not a name in the operator certificate (%s)" % (hostname, ", ".join(names) or "no SANs"))
    out = {"dir": p["dir"], "ca_key": None, "ca_crt": None, "key": key_p, "cert": cert_p, "chain": chain_file,
           "meta": None, "fingerprint": _fingerprint(cert), "names": names, "source": "operator",
           "hostname": hostname or (names[0] if names else None), "stamp": _stamp(chain_file, key_p)}
    try:
        out["expires"] = cert.not_valid_after_utc.isoformat()
    except Exception:
        out["expires"] = None
    return out


def resolve(state_dir, extra_names=None, ini=None, log=None):
    """0.17.0: the certificate both listeners serve -- the operator's when kastr.ini
    names one and it loads, else the local CA's leaf (issued/reissued as needed)."""
    op = operator_paths(state_dir, ini, log)
    if op:
        return op
    return ensure(state_dir, extra_names, ini)


def days_left(paths):
    """Days until the served certificate expires (None when unknown)."""
    try:
        cert = _load_cert(paths["cert"])
        return (cert.not_valid_after_utc - datetime.datetime.now(datetime.timezone.utc)).days
    except Exception:
        return None


def ssl_context(paths):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(paths["chain"], paths["key"])
    return ctx
