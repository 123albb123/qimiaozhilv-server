"""Repack only two audited fixes for the alternate client; preserve its other features.

This archive already ships plaintext LoadMethod 0 bundles with stale original
manifest hashes. Admit only its known config bytes; correct the changed config
record while keeping every other manifest record and object unchanged.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import struct
import zlib

import UnityPy
from _patch_blue_mech_skin import read_manifest, write_manifest

MANIFEST = 'PackageManifest_aa0_2025-01-05-1027.bytes'
INPUT = {'Hotfix.dll': '08e774a4a8d2e667c4d1309dc6df80c3dfdc083026c835dd0c9ee9794a629497',
         'HotfixView.dll': 'dfad86065c4963f63853af112f8029e2728ede4a6021cb93e5b0e7942dc32d15'}
OUTPUT = {'Hotfix.dll': '6d11f836d56f26e8a441347eed43920c8781a3d62c9270b1c023aeca7199cd7a',
          'HotfixView.dll': '708bdcd6e971d608cf688356323767eec4022beff3019878bdca0ba3221d0b30'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def inspect(raw):
    environment = UnityPy.load(raw)
    texts, other = {}, {}
    for obj in environment.objects:
        key = (obj.path_id, obj.type.name)
        if obj.type.name == 'TextAsset':
            item = obj.read()
            value = item.m_Script
            texts[item.m_Name] = value.encode('utf-8', errors='surrogateescape') if isinstance(value, str) else bytes(value)
        else:
            other[str(key)] = obj.read_typetree()
    return environment, texts, other, {(obj.path_id, obj.type.name) for obj in environment.objects}


def prepare(args):
    client = args.client.resolve()
    authorized = Path(__file__).resolve().parents[2] / 'client-qimiaozhilv-nas'
    if client != authorized.resolve():
        raise ValueError('This installer is scoped to the independent alternate NAS client')
    if args.install and not args.confirm_client_closed:
        raise ValueError('Close the client and explicitly confirm before installing')
    if args.output.exists():
        raise ValueError('Output directory must be new')
    aa0 = client / '梦幻奇遇记_Data/StreamingAssets/yoo/aa0'
    manifest_path = aa0 / MANIFEST
    original_manifest = manifest_path.read_bytes()
    original_hash = manifest_path.with_suffix('.hash').read_bytes()
    if original_hash.decode('ascii').strip() != hashlib.md5(original_manifest).hexdigest():
        raise ValueError('Input manifest hash file is invalid')
    header, assets, records = read_manifest(original_manifest)
    original_records = deepcopy(records)
    record = next(r for r in records if r['name'] == 'assets_download_config.bundle')
    old_bundle = aa0 / (record['hash'] + '.bundle')
    original = old_bundle.read_bytes()
    if record['load_method'] != 0 or not original.startswith(b'UnityFS'):
        raise ValueError('Require this archive plaintext config bundle')
    if hashlib.md5(original).hexdigest() != 'f55d3bca2441fcc0608d06f17458c3b3':
        raise ValueError('Unknown input bundle bytes')
    env, before, other, identities = inspect(original)
    if any(sha(before[name]) != digest for name, digest in INPUT.items()):
        raise ValueError('Input DLL identities do not match the reviewed archive')
    replacements = {'Hotfix.dll': args.hotfix.read_bytes(), 'HotfixView.dll': args.view.read_bytes()}
    if any(sha(replacements[name]) != digest for name, digest in OUTPUT.items()):
        raise ValueError('Replacement DLLs must match the independent method audits')
    expected = dict(before)
    expected.update(replacements)
    for obj in env.objects:
        if obj.type.name == 'TextAsset':
            item = obj.read()
            if item.m_Name in replacements:
                item.m_Script = replacements[item.m_Name].decode('utf-8', errors='surrogateescape')
                item.save()
    updated = next(iter(env.files.values())).save(packer='lz4')
    _, after, next_other, next_identities = inspect(updated)
    if after != expected or other != next_other or identities != next_identities:
        raise ValueError('Unrelated TextAssets, objects or identities changed')
    stale_input = {key: record[key] for key in ('hash', 'crc', 'size', 'load_method')}
    record.update(hash=hashlib.md5(updated).hexdigest(), size=len(updated),
                  crc=struct.pack('<I', zlib.crc32(updated) & 0xffffffff).hex())
    if any(a != b for a, b in zip(original_records, records) if a['name'] != record['name']):
        raise ValueError('Unrelated manifest record changed')
    manifest = write_manifest(header, assets, records)
    if read_manifest(manifest) != (header, assets, records):
        raise ValueError('Manifest round-trip mismatch')
    args.output.mkdir(parents=True)
    bundle_name = record['hash'] + '.bundle'
    prepared = {bundle_name: updated, MANIFEST: manifest,
                Path(MANIFEST).with_suffix('.hash').name: hashlib.md5(manifest).hexdigest().encode('ascii')}
    for name, raw in prepared.items():
        (args.output / name).write_bytes(raw)
    report = {'inputManifestSha256': sha(original_manifest), 'outputManifestSha256': sha(manifest),
              'inputBundleActualMd5': hashlib.md5(original).hexdigest(), 'staleInputRecord': stale_input,
              'outputConfigRecord': record, 'inputDllSha256': INPUT, 'outputDllSha256': OUTPUT,
              'objectsCompared': len(identities), 'textAssetsCompared': len(before),
              'unchangedOtherTextAssets': len(before) - 2, 'otherManifestRecordsUnchanged': len(records) - 1,
              'loadMethod': 0, 'installed': args.install}
    if args.install:
        suffix = '.alternate-compat.bak'
        paths = [manifest_path, manifest_path.with_suffix('.hash')]
        if any(p.with_name(p.name + suffix).exists() for p in paths):
            raise ValueError('Existing compatibility backup; refusing to overwrite it')
        for path in paths:
            shutil.copy2(path, path.with_name(path.name + suffix))
        try:
            for name in prepared:
                shutil.copy2(args.output / name, aa0 / name)
            if sha(manifest_path.read_bytes()) != report['outputManifestSha256']:
                raise ValueError('Installed manifest mismatch')
        except Exception:
            for path in paths:
                shutil.copy2(path.with_name(path.name + suffix), path)
            raise
        relative = manifest_path.relative_to(client)
        restore = f'''$ErrorActionPreference='Stop'
$manifest=Join-Path $PSScriptRoot '{relative}'
$hash=[IO.Path]::ChangeExtension($manifest,'.hash')
if((Get-FileHash -LiteralPath ($manifest+'{suffix}') -Algorithm SHA256).Hash.ToLower() -ne '{sha(original_manifest)}'){{throw 'Manifest backup mismatch'}}
if((Get-FileHash -LiteralPath ($hash+'{suffix}') -Algorithm SHA256).Hash.ToLower() -ne '{sha(original_hash)}'){{throw 'Hash-file backup mismatch'}}
Copy-Item -LiteralPath ($manifest+'{suffix}') -Destination $manifest -Force
Copy-Item -LiteralPath ($hash+'{suffix}') -Destination $hash -Force
Write-Output 'Restored this client before the HUD/market fixes; NAS address is retained.'
'''
        (client / '恢复本次HUD与商城修复.ps1').write_text(restore, encoding='utf-8-sig')
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('client', 'hotfix', 'view', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--confirm-client-closed', action='store_true')
    prepare(parser.parse_args())
