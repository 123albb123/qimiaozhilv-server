"""Prepare a reversible NAS shop pack from reviewed DLLs and offline YAML exports.

Does not change prices, disabled states or server data. Keeps AES LoadMethod 2
and all unrelated client bundle payloads. Run while the game is closed.
"""
import argparse
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import zlib
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
import UnityPy
from _patch_blue_mech_skin import AES_IV, AES_KEY, read_manifest, write_manifest

MANIFEST = 'PackageManifest_aa0_2025-01-05-1027.bytes'
INPUT_DLLS = {
 'Hotfix.dll': '24b3b6abb5189a178a5389ff05407e04a8578185ab67b5438d11408e3fbde4f5',
 'HotfixView.dll': '37e9bdcd4e50c54b80fb872dfac8b5d698274c8577f5634ae8a366ba02a13b4b',
}
OUTPUT_DLLS = {
 'Hotfix.dll': '59867c35054c16247f69902a097fc9b87be90ef9829ab73258d052afce6c22ae',
 'HotfixView.dll': 'c20d793f00812dd4ea6cb91c4d0a7172ee1dde47779b3469f206c4c080493ebf',
}

FIRST_SHOP_DLLS = dict(OUTPUT_DLLS)
OUTPUT_DLLS['Hotfix.dll'] = '16b241bab0734c70b60537da9b9e0834920d55cb3bba1daf9648b89683471772'

def sha(raw): return hashlib.sha256(raw).hexdigest()
def payloads(raw):
 out = {}
 for obj in UnityPy.load(raw).objects:
  if obj.type.name == 'TextAsset':
   item = obj.read(); val = item.m_Script
   out[item.m_Name] = val.encode('utf8', errors='surrogateescape') if isinstance(val, str) else bytes(val)
 return out

def prepare(client, dll_dir, table_dir, output, install, update_installed=False):
 data_dirs = list(client.glob('*_Data'))
 if len(data_dirs) != 1: raise ValueError('require one Unity Data directory')
 aa0 = data_dirs[0] / 'StreamingAssets/yoo/aa0'
 manifest_path = aa0 / MANIFEST
 original_manifest = manifest_path.read_bytes()
 if update_installed and sha(original_manifest) != 'f5341dd4d64e13f9449eb6e577856b6eac267ea9335d41b0215027a57b30982b':
  raise ValueError('installed-order repair requires the independently verified first NAS shop pack')
 backup_suffix = '.nas-shop-order.bak' if update_installed else '.nas-shop.bak'
 original_hash = manifest_path.with_suffix('.hash').read_bytes()
 if original_hash.decode('ascii').strip() != hashlib.md5(original_manifest).hexdigest():
  raise ValueError('current manifest hash mismatch')
 header, assets, records = read_manifest(original_manifest)
 previous = deepcopy(records)
 replacements = {name: (dll_dir / name).read_bytes() for name in OUTPUT_DLLS}
 if any(sha(replacements[name]) != digest for name,digest in OUTPUT_DLLS.items()):
  raise ValueError('DLLs must match the independently reviewed shop patch')
 prepared = {}; changes = {}
 for bundle_name in ['assets_download_config.bundle', 'assets_download_datatable.bundle']:
  record = next(x for x in records if x['name'] == bundle_name)
  if record['load_method'] != 2: raise ValueError('require encrypted LoadMethod 2')
  encrypted = (aa0 / (record['hash']+'.bundle')).read_bytes()
  if hashlib.md5(encrypted).hexdigest() != record['hash']: raise ValueError('bundle hash mismatch')
  plain = unpad(AES.new(AES_KEY,AES.MODE_CBC,AES_IV).decrypt(encrypted),16)
  before = payloads(plain); expected = dict(before)
  if 'config' in bundle_name:
   if any(sha(before[name]) != digest for name,digest in (FIRST_SHOP_DLLS if update_installed else INPUT_DLLS).items()):
    raise ValueError('require original Hotfix and verified projectile/HUD HotfixView')
   expected.update(replacements)
  else:
   if not update_installed and record['hash'] != '87c13c7e72546d4e4e0960392e451498': raise ValueError('unsupported datatable build')
   for name in ['MarketBase','ShopBase']:
    original_rows = json.loads(re.sub(r',\s*([\]}])',r'\1',zlib.decompress(base64.b64decode(before[name])).decode('utf8')))
    rows = json.loads((table_dir/(name+'.json')).read_text(encoding='utf8'))
    rows.sort(key=lambda row: int(row[0]))
    by_id = dict(rows)
    if len(by_id)!=len(rows) or any(int(k)!=int(v['_id']) for k,v in rows): raise ValueError('invalid exported row IDs')
    if update_installed and by_id != dict(original_rows): raise ValueError('installed order repair must preserve every shop row value')
    if not set(dict(original_rows)).issubset(by_id): raise ValueError('export deleted original client shop rows')
    if name=='MarketBase' and set(by_id)-set(dict(original_rows)) != (set() if update_installed else {10033}): raise ValueError('unexpected new market IDs')
    encoded = json.dumps(rows,ensure_ascii=False,separators=(',',':')).encode('utf8')
    expected[name] = base64.b64encode(zlib.compress(encoded))
    changes[name] = {'beforeRows':len(original_rows),'afterRows':len(rows)}
  env=UnityPy.load(plain)
  for obj in env.objects:
   if obj.type.name!='TextAsset': continue
   item=obj.read()
   if expected[item.m_Name] != before[item.m_Name]:
    item.m_Script=expected[item.m_Name].decode('utf8',errors='surrogateescape');item.save()
  updated_plain=next(iter(env.files.values())).save(packer='lz4')
  if payloads(updated_plain)!=expected: raise ValueError('unrelated bundle TextAsset changed')
  updated=AES.new(AES_KEY,AES.MODE_CBC,AES_IV).encrypt(pad(updated_plain,16))
  record.update(hash=hashlib.md5(updated).hexdigest(),crc=struct.pack('<I',zlib.crc32(updated)&0xffffffff).hex(),size=len(updated))
  prepared[record['hash']+'.bundle']=updated
 if any(a!=b for a,b in zip(previous,records) if a['name'] not in ['assets_download_config.bundle','assets_download_datatable.bundle']):
  raise ValueError('unrelated manifest bundle changed')
 manifest=write_manifest(header,assets,records)
 if read_manifest(manifest)!=(header,assets,records): raise ValueError('manifest round-trip mismatch')
 if output.exists(): raise ValueError('output must be new')
 output.mkdir(parents=True)
 prepared[MANIFEST]=manifest;prepared[Path(MANIFEST).with_suffix('.hash').name]=hashlib.md5(manifest).hexdigest().encode('ascii')
 for name,raw in prepared.items(): (output/name).write_bytes(raw)
 report={'inputManifestSha256':sha(original_manifest),'outputManifestSha256':sha(manifest),'dllSha256':OUTPUT_DLLS,'tables':changes,'loadMethod':2,'installed':install}
 if install:
  paths=[manifest_path,manifest_path.with_suffix('.hash')]
  if any(p.with_name(p.name+backup_suffix).exists() for p in paths): raise ValueError('existing shop backup; restore first')
  for p in paths: shutil.copy2(p,p.with_name(p.name+backup_suffix))
  try:
   for name in prepared:
    if name.endswith('.bundle'): shutil.copy2(output/name,aa0/name)
   for p in paths: shutil.copy2(output/p.name,p)
   if sha(manifest_path.read_bytes())!=report['outputManifestSha256']: raise ValueError('installed manifest mismatch')
  except Exception:
   for p in paths: shutil.copy2(p.with_name(p.name+backup_suffix),p)
   raise
  relative=manifest_path.relative_to(client)
  restore=f'''$ErrorActionPreference='Stop'
$manifest=Join-Path $PSScriptRoot '{relative}'
$backup=$manifest+'{backup_suffix}'
if((Get-FileHash -LiteralPath $backup -Algorithm SHA256).Hash.ToLowerInvariant() -ne '{report['inputManifestSha256']}'){{throw 'Shop backup hash mismatch'}}
Copy-Item -LiteralPath $backup -Destination $manifest -Force
$hash=[IO.Path]::ChangeExtension($manifest,'.hash')
Copy-Item -LiteralPath ($hash+'{backup_suffix}') -Destination $hash -Force
Write-Output 'Restored pre-shop client; projectile/HUD compatibility is retained.'
'''
  (client/('恢复商城排序修复前状态.ps1' if update_installed else '恢复商城兼容前状态.ps1')).write_text(restore,encoding='utf-8-sig')
 (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__)
 for name in ['client','dll-dir','table-dir','output']:p.add_argument('--'+name,type=Path,required=True)
 p.add_argument('--install',action='store_true');p.add_argument('--update-installed',action='store_true');a=p.parse_args()
 prepare(a.client,a.dll_dir,a.table_dir,a.output,a.install,a.update_installed)