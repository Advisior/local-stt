#!/bin/bash
# Create a self-signed code signing identity for Local-STT development.
# This identity persists in your macOS Keychain and ensures that macOS
# permissions (Microphone, Accessibility, etc.) survive app rebuilds.
#
# Run once. After that, all builds will use this identity automatically.
set -euo pipefail

IDENTITY_NAME="Local-STT Developer"

# Check if identity already exists
if security find-identity -v -p codesigning 2>/dev/null | grep -q "$IDENTITY_NAME"; then
    echo "Identity '$IDENTITY_NAME' already exists."
    security find-identity -v -p codesigning 2>/dev/null | grep "$IDENTITY_NAME"
    exit 0
fi

echo "Creating code signing identity: $IDENTITY_NAME"

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

# 1. Create certificate config
cat > "$TMPDIR/cert.conf" << 'EOF'
[req]
distinguished_name = req_dn
x509_extensions = codesign

[req_dn]
CN = Local-STT Developer

[codesign]
keyUsage = critical, digitalSignature
extendedKeyUsage = codeSigning
EOF

# 2. Generate self-signed certificate (valid for 10 years)
openssl req -x509 -newkey rsa:2048 \
    -keyout "$TMPDIR/key.pem" \
    -out "$TMPDIR/cert.pem" \
    -days 3650 \
    -nodes \
    -config "$TMPDIR/cert.conf" \
    -subj "/CN=$IDENTITY_NAME" 2>/dev/null

# 3. Export as PKCS12 (-legacy flag required for macOS Sonoma+)
openssl pkcs12 -export \
    -out "$TMPDIR/identity.p12" \
    -inkey "$TMPDIR/key.pem" \
    -in "$TMPDIR/cert.pem" \
    -passout pass:localstt \
    -legacy 2>/dev/null

# 4. Import into login keychain
security import "$TMPDIR/identity.p12" \
    -k ~/Library/Keychains/login.keychain-db \
    -T /usr/bin/codesign \
    -P "localstt"

# 5. Trust for code signing
security add-trusted-cert -d -r trustRoot -p codeSign \
    -k ~/Library/Keychains/login.keychain-db \
    "$TMPDIR/cert.pem"

echo ""
echo "Identity created and trusted:"
security find-identity -v -p codesigning 2>/dev/null | grep "$IDENTITY_NAME"
echo ""
echo "All future builds will use this identity automatically."
echo "macOS permissions will persist across rebuilds."
