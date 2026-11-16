#!/usr/bin/env python3
import socket
import subprocess
import sys
from pathlib import Path

CERTS_DIR = Path(__file__).resolve().parent


def get_lan_ips() -> list[str]:
    ips = {"127.0.0.1"}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        out = subprocess.check_output(["ifconfig"], text=True)
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("inet ") and not line.startswith("inet 127."):
                parts = line.split()
                if len(parts) >= 2:
                    ips.add(parts[1])
    except Exception:
        pass
    return sorted(ips)


def get_hostnames() -> list[str]:
    names = {"localhost", "rishta.local"}
    try:
        hn = socket.gethostname().split(".")[0]
        if hn:
            names.add(hn)
            names.add(f"{hn}.local")
    except Exception:
        pass
    try:
        lhn = subprocess.check_output(["scutil", "--get", "LocalHostName"], text=True).strip()
        if lhn:
            names.add(lhn)
            names.add(f"{lhn}.local")
    except Exception:
        pass
    return sorted(names)


def ensure_certs(force: bool = False) -> dict[str, str]:
    CERTS_DIR.mkdir(parents=True, exist_ok=True)
    ca_key = CERTS_DIR / "rishta-local-ca.key"
    ca_crt = CERTS_DIR / "rishta-local-ca.crt"
    srv_key = CERTS_DIR / "server.key"
    srv_csr = CERTS_DIR / "server.csr"
    srv_crt = CERTS_DIR / "server.crt"
    ext_cfg = CERTS_DIR / "server_ext.cnf"

    openssl = "/opt/homebrew/bin/openssl"
    if not Path(openssl).exists():
        openssl = "openssl"

    if force or not (ca_key.exists() and ca_crt.exists()):
        subprocess.run(
            [openssl, "genrsa", "-out", str(ca_key), "2048"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                openssl,
                "req",
                "-x509",
                "-new",
                "-nodes",
                "-key",
                str(ca_key),
                "-sha256",
                "-days",
                "3650",
                "-out",
                str(ca_crt),
                "-subj",
                "/C=IN/ST=Delhi/O=RishtaTracker Local CA/CN=RishtaTracker Root CA",
            ],
            check=True,
            capture_output=True,
        )

    ips = get_lan_ips()
    hostnames = get_hostnames()
    san_entries = [f"DNS:{h}" for h in hostnames] + [f"IP:{ip}" for ip in ips]
    san_line = ",".join(san_entries)

    prev_san = ext_cfg.read_text() if ext_cfg.exists() else ""
    new_ext = (
        "authorityKeyIdentifier=keyid,issuer\n"
        "basicConstraints=CA:FALSE\n"
        "keyUsage = digitalSignature, nonRepudiation, keyEncipherment, dataEncipherment\n"
        "extendedKeyUsage = serverAuth\n"
        f"subjectAltName = {san_line}\n"
    )

    if force or not (srv_key.exists() and srv_crt.exists()) or (prev_san != new_ext):
        ext_cfg.write_text(new_ext)
        subprocess.run(
            [openssl, "genrsa", "-out", str(srv_key), "2048"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                openssl,
                "req",
                "-new",
                "-key",
                str(srv_key),
                "-out",
                str(srv_csr),
                "-subj",
                f"/C=IN/ST=Delhi/O=RishtaTracker/CN={hostnames[0]}",
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                openssl,
                "x509",
                "-req",
                "-in",
                str(srv_csr),
                "-CA",
                str(ca_crt),
                "-CAkey",
                str(ca_key),
                "-CAcreateserial",
                "-out",
                str(srv_crt),
                "-days",
                "825",
                "-sha256",
                "-extfile",
                str(ext_cfg),
            ],
            check=True,
            capture_output=True,
        )

    return {
        "ca_crt": str(ca_crt),
        "server_crt": str(srv_crt),
        "server_key": str(srv_key),
        "ips": ips,
        "hostnames": hostnames,
    }


if __name__ == "__main__":
    info = ensure_certs(force="--force" in sys.argv)
    print(f"Certs ready: IPs={info['ips']} Hostnames={info['hostnames']}")
