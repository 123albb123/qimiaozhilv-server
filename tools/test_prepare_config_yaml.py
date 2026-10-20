import json
import unittest
from prepare_config_yaml import read_reference, strip_trailing_commas, validate_table, yaml_lines


class ConversionTests(unittest.TestCase):
    def test_trailing_commas_do_not_change_string_contents(self):
        raw = r'[[1,{"text":"keep ,] and ,} and \\\"quoted", "nested":[true,0,1.0,null,],}],]'
        value = json.loads(strip_trailing_commas(raw))
        self.assertEqual(value[0][1]['nested'], [True, 0, 1.0, None])
        self.assertIn(',] and ,}', value[0][1]['text'])

    def test_invalid_rows_and_duplicate_ids_are_rejected(self):
        for value in ([[1]], [[1, {}, 'extra']], [[True, {}]], [[1, []]], [[1, {}], [1, {}]]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_table('Test', value)

    def test_yaml_preserves_scalar_types_and_empty_values(self):
        text = '\n'.join(yaml_lines({'s': 'true', 'b': True, 'n': None, 'i': 9007199254740993,
                                     'f': 1.0, 'a': [], 'o': {}, 'nested': [[1, {'x': False}]]}))
        for token in ('"s": "true"', '"b": true', '"n": null', '9007199254740993', '"f": 1.0', '"a": []', '"o": {}'):
            self.assertIn(token, text)


if __name__ == '__main__':
    unittest.main()
