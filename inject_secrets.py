#!/usr/bin/env python3
"""Inject email credentials into GitHub repo secrets using GITHUB_TOKEN."""
import base64, json, os, subprocess, urllib.request, urllib.error
from nacl import encoding, public as naclpub

GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
if not GITHUB_TOKEN:
    proc = subprocess.run(['git', 'credential-manager', 'get'], input='protocol=https\nhost=github.com\n\n', capture_output=True, text=True)
    cred = {}
    for line in proc.stdout.split('\n'):
        if '=' in line:
            k, v = line.split('=', 1)
            cred[k.strip()] = v.strip()
    GITHUB_TOKEN = cred.get('password', '')

if not GITHUB_TOKEN:
    raise Exception("No GitHub token found")

EMAIL_PASS = os.environ.get('EMAIL_PASS', 'rvwrgbvxnjitiwmo')
GITHUB_API = "https://api.github.com/repos/sameer-sys/video-autopost/actions/secrets"

# Get repo public key
req = urllib.request.Request(f"{GITHUB_API}/public-key",
    headers={"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"})
with urllib.request.urlopen(req, timeout=10) as r:
    pk_data = json.load(r)

public_key = naclpub.PublicKey(pk_data["key"].encode(), encoding.Base64Encoder())

secrets = [
    ("GMAIL_APP_PASSWORD", EMAIL_PASS),
    ("GMAIL_USER", "samesuf629@gmail.com"),
    ("EMAIL_TO", "samesuf786@gmail.com"),
]

for name, value in secrets:
    sealed = naclpub.SealedBox(public_key).encrypt(value.encode())
    encrypted = base64.b64encode(sealed).decode()
    payload = json.dumps({"encrypted_value": encrypted, "key_id": pk_data["key_id"]})
    data = payload.encode()
    req2 = urllib.request.Request(f"{GITHUB_API}/{name}",
        data=data,
        headers={"Authorization": f"token {GITHUB_TOKEN}",
                 "Accept": "application/vnd.github.v3+json",
                 "Content-Type": "application/json",
                 "Content-Length": str(len(data))},
        method="PUT")
    try:
        with urllib.request.urlopen(req2, timeout=15) as r2:
            print(f"✅ Injected secret: {name}")
    except urllib.error.HTTPError as e:
        err = e.read().decode()[:300]
        print(f"❌ Failed {name}: {e.code} {err}")

print("\nAll secrets injected.")
