#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
link_swiftc="${LINK_SWIFTC:-$(command -v swiftc)}"
link_sdk="${LINK_SDK:-$(xcrun --sdk macosx --show-sdk-path)}"
link_output="$PWD/.build/native"
mkdir -p "$link_output/modules" "$link_output/module-cache"
link_flags=(-swift-version 6 -parse-as-library -O -sdk "$link_sdk"
    -target "$(uname -m)-apple-macosx13.0" -module-cache-path "$link_output/module-cache"
    -I "$link_output/modules")
"$link_swiftc" "${link_flags[@]}" -module-name LinkProtocol -emit-module \
    -emit-module-path "$link_output/modules/LinkProtocol.swiftmodule" \
    -emit-library -static native/LinkProtocol/*.swift -o "$link_output/libLinkProtocol.a"
link_app="$PWD/dist/LaptopLinkBridge.app/Contents"
mkdir -p "$link_app/MacOS"
"$link_swiftc" "${link_flags[@]}" -module-name LinkBridge native/LinkBridge/*.swift \
    "$link_output/libLinkProtocol.a" -o "$link_app/MacOS/link-bridge"
cat > "$link_app/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>local.laptop-link-mcp.bridge</string>
<key>CFBundleName</key><string>Laptop Link MCP Bridge</string>
<key>CFBundleExecutable</key><string>link-bridge</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>1</string>
<key>LSMinimumSystemVersion</key><string>13.0</string>
<key>LSUIElement</key><true/>
<key>NSBluetoothAlwaysUsageDescription</key><string>Connect to your enrolled Mac to access files and run commands over Bluetooth.</string>
</dict></plist>
PLIST
codesign --force --sign - "$PWD/dist/LaptopLinkBridge.app"
codesign --verify --deep --strict "$PWD/dist/LaptopLinkBridge.app"
echo "Built $link_app/MacOS/link-bridge"
