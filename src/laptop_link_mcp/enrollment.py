"""Interactive HTTP enrollment; never evaluate user input as shell code."""
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import tempfile


def config_directory():
    return Path.home() / '.config/laptop-link'


def key_filename(name):
    # A basename, not a path or expression. The extension is added by us.
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', name, flags=re.ASCII):
        raise ValueError('Use 1–64 ASCII letters, digits, hyphens or underscores; start with a letter or digit. Omit .key.')
    return name + '.key'


def server_url(address, port):
    ip = ipaddress.ip_address(address)
    if ip.is_unspecified or ip.is_multicast or getattr(ip, 'scope_id', None):
        raise ValueError('Use a specific IPv4 or unscoped IPv6 address, without http:// or a port')
    if not re.fullmatch(r'[0-9]{1,5}', port) or not 1 <= int(port) <= 65535:
        raise ValueError('Port must be a number between 1 and 65535')
    host = f'[{ip}]' if ip.version == 6 else str(ip)
    return f'http://{host}:{int(port)}/client.key'


def private_directory(directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError(f'Expected a directory owned by you: {directory}')
    directory.chmod(0o700)


def save_default_key(path, directory):
    descriptor, temporary = tempfile.mkstemp(dir=directory, prefix='.config-')
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump({'key': str(path.absolute())}, stream, indent=2)
            stream.write('\n')
        os.replace(temporary, directory / 'config.json')
    finally:
        Path(temporary).unlink(missing_ok=True)


def default_key():
    path = config_directory() / 'config.json'
    try:
        value = json.loads(path.read_text())
        key = value['key']
        if not isinstance(key, str) or not Path(key).is_absolute():
            raise ValueError('Saved key path must be absolute')
        return Path(key)
    except FileNotFoundError as error:
        raise ValueError('No saved enrollment key. Run scripts/setup.sh or supply --key PATH.') from error
    except (TypeError, KeyError, json.JSONDecodeError) as error:
        raise ValueError(f'Invalid saved enrollment configuration: {path}') from error


def download_key(address, port, name, directory=None):
    directory = directory if directory is not None else config_directory()
    url = server_url(address, port)
    filename = key_filename(name)
    private_directory(directory)
    destination = directory / filename
    if destination.exists() or destination.is_symlink():
        raise ValueError(f'Key already exists: {destination}. Choose another name; existing keys are never overwritten.')
    descriptor, temporary = tempfile.mkstemp(dir=directory, prefix='.download-')
    os.close(descriptor)
    try:
        # --disable comes first to ignore .curlrc; use argv, never shell=True.
        command = ['curl', '--disable', '--fail', '--silent', '--show-error',
                   '--noproxy', '*', '--proto', '=http', '--connect-timeout', '5',
                   '--max-time', '30', '--max-filesize', '32', '--output', temporary,
                   '--write-out', '%{http_code}', '--url', url]
        print('Downloading: ' + shlex.join(command), flush=True)
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=35)
        if result.returncode or result.stdout != '200':
            raise ValueError(f'Download failed (curl {result.returncode}, HTTP {result.stdout or "unavailable"}). '
                             'Check the IP, port, HTTP server and client.key file.')
        if Path(temporary).stat().st_size != 32:
            raise ValueError('Downloaded file is not a 32-byte enrollment key; nothing was installed.')
        # Atomic no-clobber installation, including if a destination appears mid-download.
        os.link(temporary, destination)
        try:
            save_default_key(destination, directory)
        except BaseException:
            destination.unlink()
            raise
        return destination
    finally:
        Path(temporary).unlink(missing_ok=True)


def prompt_valid(label, validate):
    while True:
        value = input(label).strip()
        try:
            validate(value)
            return value
        except ValueError as error:
            print(error)


def main():
    print('Download the receiving Mac’s client.key from its temporary HTTP server.')
    print('Use a trusted LAN: this one-time HTTP key transfer is unencrypted.')
    address = prompt_valid('Server IP: ', lambda value: server_url(value, '8000'))
    port = prompt_valid('Server port: ', lambda value: server_url(address, value))
    def validate_name(value):
        path = config_directory() / key_filename(value)
        if path.exists() or path.is_symlink():
            raise ValueError('That key name already exists; choose a different name.')
    name = prompt_valid('Save key as (name without .key): ', validate_name)
    path = download_key(address, port, name)
    print(f'Enrollment saved: {path} (32 bytes, mode 600).')
    print('This is now the default key for scripts/run.sh; --key PATH overrides it.')
    print('Key setup complete. Stop HTTP sharing on the receiving Mac. BLE authentication is checked on first connection.')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit('\nKey setup cancelled.')
    except (OSError, ValueError, EOFError, subprocess.TimeoutExpired) as error:
        raise SystemExit(f'Key setup failed: {error}')
