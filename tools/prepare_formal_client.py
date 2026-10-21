"""Package this audited alternate client without test files or an unused old bundle."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile

import UnityPy

ZIP_SHA = 'e633bdf9c4f92cabab2a292c3df20b2352585db756cf22b94e9ea37fac115055'
MANIFEST = 'PackageManifest_aa0_2025-01-05-1027.bytes'
NEW_BUNDLE = 'faf8974da5385672d4f9f9885856450d.bundle'
OLD_BUNDLE = '5ff0cd3f4dadb1ed406add45f5bbb636.bundle'
DATA = '梦幻奇遇记_Data/'
AA0 = DATA + 'StreamingAssets/yoo/aa0/'
PATCHED = {
    DATA + 'resources.assets': '7b5f5beb390c8f5e626a5748fb3b7df6b33e446ef55ec350636132fd84fe7a72',
    AA0 + MANIFEST: 'cbf2b435f7e968630bd6dc538bba0c91cc4fadbf40ad8431161bf27cd9f340b7',
}
DLL_SHA = {
    'Hotfix.dll': '4f13a35ac89b934b8482e9587ef96af51729f6826c8708858015e69f793f08a0',
    'HotfixView.dll': '4d22791bd5313503be4a7b2a9ae0d5b6b3a1d934040383c4c90128dddfa4bcc5',
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('original-zip', 'patched-client', 'output', 'evidence'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if sha(args.original_zip.read_bytes()) != ZIP_SHA:
        raise ValueError('Unsupported original client archive')
    source, output = args.patched_client.resolve(), args.output.resolve()
    if output.exists() or args.evidence.exists() or source in output.parents:
        raise ValueError('Use new independent output and evidence paths')
    manifest = (source / (AA0 + MANIFEST)).read_bytes()
    manifest_hash_name = AA0 + MANIFEST.replace('.bytes', '.hash')
    if (source / manifest_hash_name).read_bytes() != hashlib.md5(manifest).hexdigest().encode():
        raise ValueError('Manifest hash-file mismatch')
    bundle = (source / (AA0 + NEW_BUNDLE)).read_bytes()
    if hashlib.md5(bundle).hexdigest() + '.bundle' != NEW_BUNDLE:
        raise ValueError('Configuration bundle hash mismatch')
    dlls = {}
    for obj in UnityPy.load(bundle).objects:
        if obj.type.name == 'TextAsset':
            text = obj.read()
            if text.m_Name in DLL_SHA:
                raw = text.m_Script
                if isinstance(raw, str):
                    raw = raw.encode('utf-8', errors='surrogateescape')
                dlls[text.m_Name] = sha(raw)
    if dlls != DLL_SHA:
        raise ValueError('The two audited DLL repairs must both be present')
    copied, skipped = [], []
    output.mkdir(parents=True)
    with zipfile.ZipFile(args.original_zip) as archive:
        members = [entry for entry in archive.infolist() if not entry.is_dir()]
        if len(members) != 1167:
            raise ValueError('Unexpected original archive file count')
        seen = set()
        for entry in members:
            path = PurePosixPath(entry.filename)
            if (path.is_absolute() or path.parts[0] != 'qimiaozhilv-client' or
                    '..' in path.parts or ':' in entry.filename or
                    stat.S_ISLNK(entry.external_attr >> 16)):
                raise ValueError('Unsafe original archive path')
            relative = str(PurePosixPath(*path.parts[1:]))
            if relative.casefold() in seen:
                raise ValueError('Duplicate archive path')
            seen.add(relative.casefold())
            if relative == AA0 + OLD_BUNDLE:
                skipped.append(relative)
                continue
            raw = (source / relative).read_bytes()
            expected = PATCHED.get(relative)
            if relative == manifest_hash_name:
                expected = sha(hashlib.md5(manifest).hexdigest().encode())
            if sha(raw) != (expected or sha(archive.read(entry))):
                raise ValueError('Unexpected client change: ' + relative)
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            copied.append(relative)
    if skipped != [AA0 + OLD_BUNDLE]:
        raise ValueError('Expected precisely one obsolete config bundle')
    shutil.copy2(source / (AA0 + NEW_BUNDLE), output / (AA0 + NEW_BUNDLE))
    files = []
    for path in sorted(output.rglob('*')):
        if path.is_file():
            raw = path.read_bytes()
            files.append({'path': path.relative_to(output).as_posix(),
                          'size': len(raw), 'sha256': sha(raw)})
    report = {'originalZipSha256': ZIP_SHA, 'files': files,
              'fileCount': len(files), 'removedObsoleteBundle': skipped,
              'auditedDllSha256': dlls, 'address': '192.168.1.22:7756',
              'excluded': ['test scripts', 'backup files', 'cached login credentials']}
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Formal client prepared:', len(files), 'verified runtime files; no test scripts or backups.')


if __name__ == '__main__':
    main()
