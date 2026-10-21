"""Stage the two final, individually audited client repairs on the known two-fix bundle."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import struct
import zlib
from prepare_qimiaozhilv_compat import inspect
from _patch_blue_mech_skin import read_manifest, write_manifest

MANIFEST = 'PackageManifest_aa0_2025-01-05-1027.bytes'
BEFORE = {'Hotfix.dll': '6d11f836d56f26e8a441347eed43920c8781a3d62c9270b1c023aeca7199cd7a',
          'HotfixView.dll': '708bdcd6e971d608cf688356323767eec4022beff3019878bdca0ba3221d0b30'}
AFTER = {'Hotfix.dll': '4f13a35ac89b934b8482e9587ef96af51729f6826c8708858015e69f793f08a0',
         'HotfixView.dll': '4d22791bd5313503be4a7b2a9ae0d5b6b3a1d934040383c4c90128dddfa4bcc5'}

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('client', 'hotfix', 'view', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Output directory must be new')
    aa0 = args.client / '梦幻奇遇记_Data/StreamingAssets/yoo/aa0'
    raw_manifest = (aa0 / MANIFEST).read_bytes()
    if sha(raw_manifest) != 'dec4af2d3b2557c9a6171b12061c541da40be107186df75dc1c1b07698e0df9a':
        raise ValueError('Require the audited two-fix manifest')
    header, assets, records = read_manifest(raw_manifest)
    previous = deepcopy(records)
    record = next(r for r in records if r['name'] == 'assets_download_config.bundle')
    raw_bundle = (aa0 / (record['hash'] + '.bundle')).read_bytes()
    if record['load_method'] != 0 or hashlib.md5(raw_bundle).hexdigest() != '39c75df8be6f1014e904f568c7573237':
        raise ValueError('Require known plaintext config bundle')
    env, before, other, identities = inspect(raw_bundle)
    if any(sha(before[name]) != value for name, value in BEFORE.items()):
        raise ValueError('Input DLL identity mismatch')
    changed = {'Hotfix.dll': args.hotfix.read_bytes(), 'HotfixView.dll': args.view.read_bytes()}
    if any(sha(changed[name]) != value for name, value in AFTER.items()):
        raise ValueError('Replacement DLL identity mismatch')
    for obj in env.objects:
        if obj.type.name == 'TextAsset':
            item = obj.read()
            if item.m_Name in changed:
                item.m_Script = changed[item.m_Name].decode('utf-8', errors='surrogateescape')
                item.save()
    bundle = next(iter(env.files.values())).save(packer='lz4')
    _, after, after_other, after_ids = inspect(bundle)
    expected = dict(before)
    expected.update(changed)
    if after != expected or after_other != other or after_ids != identities:
        raise ValueError('Unrelated bundle contents changed')
    record.update(hash=hashlib.md5(bundle).hexdigest(), size=len(bundle),
                  crc=struct.pack('<I', zlib.crc32(bundle) & 0xffffffff).hex())
    if any(a != b for a, b in zip(previous, records) if a['name'] != record['name']):
        raise ValueError('Unrelated manifest record changed')
    manifest = write_manifest(header, assets, records)
    if read_manifest(manifest) != (header, assets, records):
        raise ValueError('Manifest round-trip mismatch')
    args.output.mkdir(parents=True)
    (args.output / (record['hash'] + '.bundle')).write_bytes(bundle)
    (args.output / MANIFEST).write_bytes(manifest)
    (args.output / MANIFEST.replace('.bytes', '.hash')).write_bytes(hashlib.md5(manifest).hexdigest().encode())
    report = {'beforeDllSha256': BEFORE, 'afterDllSha256': AFTER,
              'bundleMd5': record['hash'], 'manifestSha256': sha(manifest),
              'objectsCompared': len(identities), 'textAssetsCompared': len(before),
              'unchangedOtherTextAssets': len(before)-2, 'otherManifestRecordsUnchanged': len(records)-1,
              'stagedOnly': True}
    (args.output / 'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__ == '__main__':
    main()
