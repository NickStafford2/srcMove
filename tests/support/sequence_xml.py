"""Test adapter for the shared native XML sequence admission policy."""
from srcmove_runtime.results_xml import element_positions
from srcmove_runtime.results_xml import validate_sequences as _validate_sequences


def validate_sequences(input_path, tree, payload, resolve):
    try:
        _validate_sequences(input_path.read_bytes(), tree, payload, resolve)
    except ValueError as error:
        raise AssertionError(str(error)) from error
