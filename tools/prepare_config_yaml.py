#!/usr/bin/env python3
"""Offline, lossless conversion of repository reference tables into YAML.

Only this build tool reads JSON. Game and administration binaries consume YAML
or MySQL. No third-party Python modules are required.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path


def strip_trailing_commas(text):
    out, quoted, escaped = [], False, False
    for i, char in enumerate(text):
        if quoted:
            out.append(char)
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
            out.append(char)
        elif char == ',':
            next_index = i + 1
            while next_index < len(text) and text[next_index].isspace():
                next_index += 1
            if next_index == len(text) or text[next_index] not in ']}':
                out.append(char)
        else:
            out.append(char)
    return ''.join(out)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate object key: {key}')
        result[key] = value
    return result


def read_reference(path):
    return json.loads(strip_trailing_commas(path.read_text(encoding='utf-8-sig')),
                      object_pairs_hook=unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def validate_table(name, value):
    if not isinstance(value, list):
        raise ValueError(f'{name}: table must be an array')
    seen = set()
    for index, pair in enumerate(value):
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError(f'{name} row {index}: expected [id, object]')
        key, fields = pair
        if type(key) is not int or not 0 <= key <= 2147483647:
            raise ValueError(f'{name} row {index}: invalid integer id {key!r}')
        if key in seen:
            raise ValueError(f'{name}: duplicate id {key}')
        if not isinstance(fields, dict):
            raise ValueError(f'{name} row {index}: value must be an object')
        seen.add(key)


def yaml_scalar(value):
    if type(value) is int and not -(2**63) <= value < 2**63:
        raise ValueError('integer is outside the MySQL signed BIGINT range')
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('non-finite float')
    if value is None or type(value) in (str, int, float, bool):
        return json.dumps(value, ensure_ascii=False)
    raise ValueError(f'unsupported scalar: {type(value)}')


def yaml_lines(value, indent=0):
    prefix = ' ' * indent
    if isinstance(value, dict) and value:
        for key, child in value.items():
            label = json.dumps(key, ensure_ascii=False) + ':'
            if isinstance(child, (dict, list)) and child:
                yield prefix + label
                yield from yaml_lines(child, indent + 2)
            else:
                scalar = '{}' if child == {} else '[]' if child == [] else yaml_scalar(child)
                yield prefix + label + ' ' + scalar
    elif isinstance(value, list) and value:
        for child in value:
            if isinstance(child, (dict, list)) and child:
                yield prefix + '-'
                yield from yaml_lines(child, indent + 2)
            else:
                scalar = '{}' if child == {} else '[]' if child == [] else yaml_scalar(child)
                yield prefix + '- ' + scalar
    else:
        yield prefix + ('{}' if value == {} else '[]' if value == [] else yaml_scalar(value))


def prepare(source, skill, output):
    tables = output / 'tables'
    if output.exists() and any(output.iterdir()):
        raise ValueError(f'output directory must be empty: {output}')
    prepared, manifest = [], {}
    for path in sorted(source.glob('*.json')):
        value = read_reference(path)
        validate_table(path.stem, value)
        prepared.append((path.stem, value))
        manifest[path.name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'rows': len(value)}
    if not prepared:
        raise ValueError('no reference tables found')
    logic = read_reference(skill)
    if not isinstance(logic, dict) or not logic.get('skillDic'):
        raise ValueError('SkillLogicConfig has no skills')
    manifest['SkillLogicConfig'] = {'sha256': hashlib.sha256(skill.read_bytes()).hexdigest(), 'skills': len(logic['skillDic'])}
    tables.mkdir(parents=True, exist_ok=True)
    for name, value in prepared:
        (tables / (name + '.yaml')).write_text('\n'.join(yaml_lines(value)) + '\n', encoding='utf-8')
    (output / 'SkillLogicConfig.yaml').write_text('\n'.join(yaml_lines(logic)) + '\n', encoding='utf-8')
    (output / 'manifest.yaml').write_text('\n'.join(yaml_lines(manifest)) + '\n', encoding='utf-8')
    print(f'Converted {len(prepared)} tables and {len(logic["skillDic"])} skills into {output}')


if __name__ == '__main__':
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=root / 'datatable_json')
    parser.add_argument('--skill', type=Path, default=root / 'server-mysql/testdata/SkillLogicConfig')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.source, args.skill, args.output)
