import Foundation
import Darwin
import LinkProtocol

/// Private newline-JSON transport for the Python MCP process. Stdout is protocol only.
@main
struct LinkBridgeMain {
    static func main() {
        signal(SIGPIPE, SIG_IGN)
        let args = Array(CommandLine.arguments.dropFirst())
        func option(_ name: String) -> String? {
            guard let i = args.firstIndex(of: name), i + 1 < args.count else { return nil }
            return args[i + 1]
        }
        do {
            guard let path = option("--key") else { throw RPCError("arguments", "--key is required") }
            let key = try Data(contentsOf: URL(fileURLWithPath: path))
            guard key.count == 32 else { throw RPCError("arguments", "Key must contain 32 bytes") }
            let timeout = option("--timeout").flatMap(Int.init) ?? 120
            guard (1...3600).contains(timeout) else { throw RPCError("arguments", "Invalid timeout") }
            guard let format = WireFormat(rawValue: option("--wire") ?? "protobuf") else {
                throw RPCError("arguments", "--wire must be protobuf or json")
            }
            let client = try LinkSession(key: key, name: option("--name"), timeout: timeout, format: format)
            DispatchQueue.global().async {
                do {
                    var buffer = Data()
                    var chunk = [UInt8](repeating: 0, count: 8192)
                    while true {
                        let count = Darwin.read(STDIN_FILENO, &chunk, chunk.count)
                        if count == 0 { exit(0) }
                        if count < 0 {
                            if errno == EINTR { continue }
                            throw RPCError("stdin", "Input read failed")
                        }
                        buffer.append(contentsOf: chunk.prefix(count))
                        while let end = buffer.firstIndex(of: 10) {
                            let line = Data(buffer[..<end]); buffer.removeSubrange(...end)
                            guard line.count <= 131_072 else { throw RPCError("limit", "Request too large") }
                            let request = try WireJSON.decode(RPCRequest.self, from: line)
                            let ready = DispatchSemaphore(value: 0)
                            client.perform(request) { response in
                                do {
                                    try FileHandle.standardOutput.write(contentsOf: WireJSON.encode(response) + Data([10]))
                                    ready.signal()
                                } catch { fail(error) }
                            }
                            ready.wait()
                        }
                        guard buffer.count <= 131_072 else { throw RPCError("limit", "Request too large") }
                    }
                } catch { fail(error) }
            }
            withExtendedLifetime(client) { dispatchMain() }
        } catch { fail(error) }
    }

    static func fail(_ error: Error) -> Never {
        FileHandle.standardError.write(Data("\(error.localizedDescription)\n".utf8))
        exit(1)
    }
}
