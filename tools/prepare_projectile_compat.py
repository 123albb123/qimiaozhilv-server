"""Install verified DOMove-signature and initial HUD-null compatibility repairs."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import struct
import zlib

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
import UnityPy
from _patch_blue_mech_skin import AES_IV, AES_KEY, read_manifest, write_manifest

ORIGINAL_DLL = '7d9256fff2746310227e0509eb340198842c78cec7d857e9c482a201e52fc889'
REPAIRED_DLL = '37e9bdcd4e50c54b80fb872dfac8b5d698274c8577f5634ae8a366ba02a13b4b'
MANIFEST = 'PackageManifest_aa0_2025-01-05-1027.bytes'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def texts(raw):
    result = {}
    for obj in UnityPy.load(raw).objects:
        if obj.type.name == 'TextAsset':
            item = obj.read()
            value = item.m_Script
            result[item.m_Name] = value.encode('utf-8', errors='surrogateescape') if isinstance(value, str) else bytes(value)
    return result


def prepare(client, patched, output, install):
    data_dirs = list(client.glob('*_Data'))
    if len(data_dirs) != 1:
        raise ValueError('require exactly one Unity Data directory')
    aa0 = data_dirs[0] / 'StreamingAssets/yoo/aa0'
    original_manifest = (aa0 / MANIFEST).read_bytes()
    original_hashfile = (aa0 / MANIFEST).with_suffix('.hash').read_bytes()
    if original_hashfile.decode('ascii').strip().lower() != hashlib.md5(original_manifest).hexdigest():
        raise ValueError('original manifest hash mismatch')
    header, assets, bundles = read_manifest(original_manifest)
    original_bundles = deepcopy(bundles)
    record = next(row for row in bundles if row['name'] == 'assets_download_config.bundle')
    if record['hash'] != '5ff0cd3f4dadb1ed406add45f5bbb636' or record['load_method'] != 2:
        raise ValueError('this isolated repair requires the original encrypted config bundle')
    encrypted = (aa0 / (record['hash'] + '.bundle')).read_bytes()
    if hashlib.md5(encrypted).hexdigest() != record['hash']:
        raise ValueError('original bundle hash mismatch')
    plain = unpad(AES.new(AES_KEY, AES.MODE_CBC, AES_IV).decrypt(encrypted), 16)
    original_texts = texts(plain)
    if sha(original_texts['HotfixView.dll']) != ORIGINAL_DLL:
        raise ValueError('unsupported HotfixView build')
    repair = patched.read_bytes()
    if not repair.startswith(b'MZ') or sha(repair) != REPAIRED_DLL:
        raise ValueError('supply the independently verified repaired PE file')
    env = UnityPy.load(plain)
    for obj in env.objects:
        if obj.type.name == 'TextAsset' and obj.read().m_Name == 'HotfixView.dll':
            item = obj.read()
            item.m_Script = repair.decode('utf-8', errors='surrogateescape')
            item.save()
    updated_plain = next(iter(env.files.values())).save(packer='lz4')
    updated_texts = texts(updated_plain)
    expected = dict(original_texts, **{'HotfixView.dll': repair})
    if updated_texts != expected:
        raise ValueError('bundle changed unrelated TextAssets')
    updated = AES.new(AES_KEY, AES.MODE_CBC, AES_IV).encrypt(pad(updated_plain, 16))
    record.update(hash=hashlib.md5(updated).hexdigest(), crc=struct.pack('<I', zlib.crc32(updated) & 0xffffffff).hex(), size=len(updated))
    manifest = write_manifest(header, assets, bundles)
    h2, a2, b2 = read_manifest(manifest)
    if h2 != header or a2 != assets or b2 != bundles:
        raise ValueError('manifest failed complete round-trip validation')
    for old, new in zip(original_bundles, bundles):
        if old['name'] != record['name'] and old != new:
            raise ValueError('unrelated bundle metadata changed')
    if output.exists():
        raise ValueError('output must be a new directory')
    output.mkdir(parents=True)
    (output / (record['hash'] + '.bundle')).write_bytes(updated)
    (output / MANIFEST).write_bytes(manifest)
    (output / MANIFEST).with_suffix('.hash').write_text(hashlib.md5(manifest).hexdigest(), encoding='ascii')
    report = {'originalDllSha256': ORIGINAL_DLL, 'patchedDllSha256': sha(repair),
              'originalManifestSha256': sha(original_manifest), 'patchedManifestSha256': sha(manifest),
              'bundleFile': record['hash'] + '.bundle', 'loadMethod': record['load_method'],
              'preservedTextAssets': sorted(set(original_texts) - {'HotfixView.dll'}),
              'repairs': ['DOMove return signature matches installed DOTween', 'InitHeadInfo returns while MyUnit is not created'], 'installed': install}
    if install:
        for path in [aa0 / MANIFEST, (aa0 / MANIFEST).with_suffix('.hash')]:
            backup = path.with_name(path.name + '.projectile-compat.bak')
            if backup.exists():
                raise ValueError('existing compatibility backup; restore before reinstalling')
            shutil.copy2(path, backup)
        for path in output.iterdir():
            if path.suffix in ('.bundle', '.bytes', '.hash'):
                shutil.copy2(path, aa0 / path.name)
        if sha((aa0 / MANIFEST).read_bytes()) != report['patchedManifestSha256']:
            raise ValueError('installed manifest verification failed')
        relative = (aa0 / MANIFEST).relative_to(client)
        restore = f'''$ErrorActionPreference = 'Stop'
$manifest = Join-Path $PSScriptRoot '{relative}'
$backup = $manifest + '.projectile-compat.bak'
if ((Get-FileHash -LiteralPath $backup -Algorithm SHA256).Hash.ToLowerInvariant() -ne '{report['originalManifestSha256']}') {{ throw 'Original manifest backup hash mismatch' }}
Copy-Item -LiteralPath $backup -Destination $manifest -Force
$hashFile = [IO.Path]::ChangeExtension($manifest, '.hash')
Copy-Item -LiteralPath ($hashFile + '.projectile-compat.bak') -Destination $hashFile -Force
Write-Host 'Original encrypted client code restored. Close and reopen the game.'
'''
        (client / '恢复原版特效.ps1').write_text(restore, encoding='utf-8-sig')
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', required=True, type=Path)
    parser.add_argument('--patched-dll', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    prepare(args.client.resolve(), args.patched_dll.resolve(), args.output.resolve(), args.install)
