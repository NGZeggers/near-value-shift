"""Keep the committed receipt-status attestation aligned with its extract."""
import csv
import hashlib
import json

from near_thesis.config import DATA
from near_thesis.blocks import SUCCESS_STATUSES


def test_verified_extract_matches_attestation_and_contains_no_failed_receipts():
    path = DATA / 'blocks/intents_events_sampled.csv'
    report = json.loads((DATA / 'blocks/event_verification.json').read_text())
    with path.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert hashlib.sha256(path.read_bytes()).hexdigest() == report['output_sha256']
    assert len(rows) == report['accepted_events']
    assert all(row['execution_status'] in SUCCESS_STATUSES for row in rows)
    assert report['input_events'] == report['accepted_events'] + report['failed_events_removed']
