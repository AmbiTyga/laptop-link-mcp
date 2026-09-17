#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
ble_plugin="${PROTOC_GEN_SWIFT:-$(command -v protoc-gen-swift)}"
if [[ "$("$ble_plugin" --version)" != *'1.38.1'* ]]; then
    echo 'Use protoc-gen-swift 1.38.1 to match the vendored runtime.' >&2
    exit 1
fi
protoc --plugin="protoc-gen-swift=$ble_plugin" --proto_path=Protocol \
    --swift_opt=Visibility=Public --swift_out=native/LinkProtocol Protocol/ble_wire.proto
