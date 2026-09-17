import Foundation
@preconcurrency import CoreBluetooth
import LinkProtocol

/// Persistent authenticated session, with exactly one RPC in flight.
/// Delegate state is confined to queue. Failures are never automatically retried.
public final class LinkSession: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate, @unchecked Sendable {
    private let queue = DispatchQueue(label: "ble.central")
    private let handshake: ClientHandshake
    private let format: WireFormat
    private let name: String?
    private var request: RPCRequest?
    private var completion: (@Sendable (RPCResponse) -> Void)?
    private let timeout: Int
    private var manager: CBCentralManager!
    private var peripheral: CBPeripheral?
    private var rx: CBCharacteristic?, tx: CBCharacteristic?
    private var decoder = FrameDecoder()
    private var outgoing = Data()
    private var writing = false, done = false
    private var stage = "challenge"

    public init(key: Data, name: String?, timeout: Int, format: WireFormat = .protobuf) throws {
        self.format = format
        handshake = try ClientHandshake(key: key, format: format); self.name = name; self.timeout = timeout
        super.init()
        manager = CBCentralManager(delegate: self, queue: queue)
    }

    public func perform(_ request: RPCRequest, completion: @escaping @Sendable (RPCResponse) -> Void) {
        queue.async {
            self.trace("perform \(request.method) stage=\(self.stage)")
            guard self.request == nil else { LinkBridgeMain.fail(RPCError("busy", "Request already active")) }
            guard request.version == 1, request.method == "server.info" || request.bootID != nil else {
                LinkBridgeMain.fail(RPCError("protocol", "Version 1 and explicit bootID required"))
            }
            self.request = request; self.completion = completion
            self.queue.asyncAfter(deadline: .now() + .seconds(self.timeout)) { [weak self] in
                guard let self, self.request?.id == request.id else { return }
                self.finish(.failure(RPCError("timeout", "BLE request timed out; outcome may be unknown")))
            }
            do { try self.submit() } catch { self.finish(.failure(error)) }
        }
    }

    private func submit() throws {
        trace("submit stage=\(stage) request=\(request != nil)")
        guard stage == "idle", let request, let channel = handshake.channel else { return }
        stage = "result"
        try send(channel.seal(format.encodeRequest(request)))
    }

    public func centralManagerDidUpdateState(_ central: CBCentralManager) {
        trace("Bluetooth state=\(central.state.rawValue)")
        guard central.state == .poweredOn else {
            if central.state == .unauthorized || central.state == .unsupported || central.state == .poweredOff {
                finish(.failure(RPCError("bluetooth", "Bluetooth unavailable: \(central.state.rawValue)")))
            }
            return
        }
        central.scanForPeripherals(withServices: [LinkServiceIDs.service])
    }

    public func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
                               advertisementData: [String: Any], rssi RSSI: NSNumber) {
        trace("discovered \(peripheral.name ?? "unnamed")")
        guard self.peripheral == nil else { return }
        let advertised = advertisementData[CBAdvertisementDataLocalNameKey] as? String ?? peripheral.name
        guard name == nil || advertised == name else { return }
        self.peripheral = peripheral; peripheral.delegate = self
        central.stopScan(); central.connect(peripheral)
    }

    public func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        trace("connected")
        peripheral.discoverServices([LinkServiceIDs.service])
    }

    public func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        finish(.failure(error ?? RPCError("connection", "Connection failed")))
    }

    public func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        finish(.failure(error ?? RPCError("disconnected", "Connection lost; submitted mutation outcome may be unknown")))
    }

    public func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        trace("services")
        if let error { finish(.failure(error)); return }
        guard let service = peripheral.services?.first(where: { $0.uuid == LinkServiceIDs.service }) else {
            finish(.failure(RPCError("protocol", "Missing service"))); return
        }
        peripheral.discoverCharacteristics([LinkServiceIDs.request, LinkServiceIDs.response], for: service)
    }

    public func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        trace("characteristics")
        if let error { finish(.failure(error)); return }
        tx = service.characteristics?.first { $0.uuid == LinkServiceIDs.request }
        rx = service.characteristics?.first { $0.uuid == LinkServiceIDs.response }
        guard tx != nil, let rx else { finish(.failure(RPCError("protocol", "Missing characteristics"))); return }
        peripheral.setNotifyValue(true, for: rx)
    }

    public func peripheral(_ peripheral: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic, error: Error?) {
        trace("notifications=\(characteristic.isNotifying)")
        if let error { finish(.failure(error)); return }
        guard characteristic.isNotifying else { finish(.failure(RPCError("protocol", "Notifications not enabled"))); return }
        do { try send(handshake.hello) } catch { finish(.failure(error)) }
    }

    public func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        if let error { finish(.failure(error)); return }
        guard characteristic.uuid == LinkServiceIDs.response, let value = characteristic.value else { return }
        do {
            for data in try decoder.append(value) { try receive(format.decodeEnvelope(data)) }
        } catch { finish(.failure(error)) }
    }

    private func receive(_ envelope: Envelope) throws {
        trace("receive \(envelope.type) stage=\(stage)")
        if stage == "challenge" {
            let auth = try handshake.authenticate(envelope)
            stage = "ready"; try send(auth); return
        }
        guard let channel = handshake.channel else { throw RPCError("auth", "No authenticated session") }
        let data = try channel.open(envelope)
        if stage == "ready" {
            guard data == Data("ready".utf8) else { throw RPCError("auth", "Invalid authentication acknowledgement") }
            stage = "idle"; try submit(); return
        }
        let response = try format.decodeResponse(data)
        guard stage == "result", response.version == 1, response.id == request?.id else {
            throw RPCError("protocol", "Unexpected response")
        }
        let callback = completion
        request = nil; completion = nil; stage = "idle"
        trace("complete callback=\(callback != nil)")
        callback?(response)
    }

    private func send(_ envelope: Envelope) throws {
        guard outgoing.isEmpty else { throw RPCError("protocol", "Previous write is unfinished") }
        outgoing = try FrameDecoder.encode(format.encodeEnvelope(envelope)); pump()
    }

    private func pump() {
        guard !done, !writing, !outgoing.isEmpty, let peripheral, let tx else { return }
        let count = min(outgoing.count, peripheral.maximumWriteValueLength(for: .withResponse))
        guard count > 0 else { finish(.failure(RPCError("protocol", "Invalid write size"))); return }
        let chunk = Data(outgoing.prefix(count)); outgoing.removeFirst(count); writing = true
        peripheral.writeValue(chunk, for: tx, type: .withResponse)
    }

    public func peripheral(_ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic, error: Error?) {
        if let error { finish(.failure(error)); return }
        trace("write acknowledged")
        writing = false; pump()
    }

    private func trace(_ message: String) {
        if ProcessInfo.processInfo.environment["LINK_TRACE"] == "1" {
            FileHandle.standardError.write(Data("BLE: \(message)\n".utf8))
        }
    }

    private func finish(_ result: Result<RPCResponse, Error>) {
        guard !done else { return }; done = true
        manager.stopScan()
        if let peripheral { manager.cancelPeripheralConnection(peripheral) }
        if case .failure(let error) = result { LinkBridgeMain.fail(error) }
    }
}
