"""Prepare a new fnOS deployment bundle without printing generated secrets."""
import argparse
import hashlib
import ipaddress
from pathlib import Path
import re
import secrets
import shutil
import tarfile


def prepare(output, address, tag, node_image):
    if output.exists() and any(output.iterdir()):
        raise ValueError('output directory must be empty; existing credentials will not be replaced')
    ip = ipaddress.ip_address(address)
    if ip.version != 4 or not re.fullmatch(r'[A-Za-z0-9_.-]+', tag):
        raise ValueError('require an IPv4 NAS address and a valid image tag')
    source = Path(__file__).resolve().parent
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / 'compose.yaml', output / 'compose.yaml')
    shutil.copytree(source.parent.parent / 'config/operations', output / 'config/operations')
    shutil.copytree(source / 'scripts', output / 'ops')
    env = {'MYSQL_ROOT_PASSWORD': secrets.token_hex(24), 'MHQ_DB_PASSWORD': secrets.token_hex(24),
           'GM_ADMIN_USERNAME': 'admin', 'GM_ADMIN_PASSWORD': secrets.token_hex(18),
           'MHQ_IMAGE_TAG': tag, 'MHQ_BIND_IP': str(ip), 'MHQ_PUBLIC_ADDR': f'{ip}:7756',
           'MHQ_GAME_PORT': '7756', 'MHQ_GM_PORT': '8897', 'MHQ_NODE_IMAGE': node_image}
    (output / '.env').write_text(''.join(f'{key}={value}\n' for key, value in env.items()), encoding='utf-8', newline='\n')
    archive_path = output.parent / (output.name + '.tar.gz')
    if archive_path.exists():
        raise ValueError(f'refusing to overwrite deployment archive: {archive_path}')
    with tarfile.open(archive_path, 'w:gz') as archive:
        for path in sorted(output.rglob('*')):
            if path.is_file():
                relative = path.relative_to(output).as_posix()
                info = archive.gettarinfo(str(path), arcname=relative)
                info.uid = info.gid = 1000
                info.uname = info.gname = ''
                info.mode = 0o600 if path.name == '.env' else 0o755 if path.suffix == '.sh' else 0o644
                with path.open('rb') as stream:
                    archive.addfile(info, stream)
    print(f'Prepared {archive_path.name}; credentials are in {output / ".env"} (not printed)')
    print('SHA256:', hashlib.sha256(archive_path.read_bytes()).hexdigest())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--nas-ip', default='192.168.1.22')
    parser.add_argument('--tag', required=True)
    parser.add_argument('--node-image', default='node:22.16.0-alpine3.22')
    args = parser.parse_args()
    prepare(args.output, args.nas_ip, args.tag, args.node_image)
