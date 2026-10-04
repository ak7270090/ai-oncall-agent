"""Key pair for the MCP bearer tokens (Phase 22).

The AI server signs tokens with the private key; the MCP servers and the gateway check
them with the public key, published as a JWKS file. Verifiers can't mint tokens, so a
gateway or server config that leaks gives no one a way in.

    make mcp-keys      (writes ../keys)"""

import hashlib
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from auth.constants import MCP_TOKEN_ALGORITHM

PRIVATE_KEY_FILE = "mcp-token-private.pem"
JWKS_FILE = "jwks.json"
RSA_KEY_BITS = 2048
RSA_PUBLIC_EXPONENT = 65537
KEY_ID_LENGTH = 16


def compute_key_id(public_key: rsa.RSAPublicKey) -> str:
    der = public_key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return hashlib.sha256(der).hexdigest()[:KEY_ID_LENGTH]


def to_jwks(public_key: rsa.RSAPublicKey) -> dict:
    jwk = RSAAlgorithm.to_jwk(public_key, as_dict=True)
    return {"keys": [{**jwk, "kid": compute_key_id(public_key), "use": "sig", "alg": MCP_TOKEN_ALGORITHM}]}


def load_private_key(path: Path) -> tuple[str, str]:
    """(PEM text, key id) of the signing key."""
    pem = path.read_text(encoding="utf-8")
    private_key = serialization.load_pem_private_key(pem.encode(), password=None)
    return pem, compute_key_id(private_key.public_key())


def write_key_files(directory: Path) -> None:
    private_key = rsa.generate_private_key(public_exponent=RSA_PUBLIC_EXPONENT, key_size=RSA_KEY_BITS)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / PRIVATE_KEY_FILE).write_bytes(private_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    (directory / JWKS_FILE).write_text(json.dumps(to_jwks(private_key.public_key()), indent=2), encoding="utf-8")


def main() -> None:
    directory = Path(sys.argv[1] if len(sys.argv) > 1 else "keys")
    write_key_files(directory)
    print(f"wrote {directory / PRIVATE_KEY_FILE} (AI server only) and {directory / JWKS_FILE} (MCP servers, gateway)")


if __name__ == "__main__":
    main()
