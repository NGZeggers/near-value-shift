"""Validate the completed reconciliation against the frozen original and cached public blocks."""
import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from near_thesis import blocks

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('original', type=Path, help='Frozen original extract from the pre-revalidation commit')
parser.add_argument('--output', type=Path, required=True, help='New directory for verification evidence')
args = parser.parse_args()
OLD = args.original
CURRENT = ROOT/'data/blocks/intents_events_sampled.csv'
OUT = args.output
OUT.mkdir(parents=True, exist_ok=True)
old = list(csv.DictReader(OLD.open()))
new = list(csv.DictReader(CURRENT.open()))
report = json.loads((ROOT/'data/blocks/event_verification.json').read_text())
checks = []
def check(name, passed):
    checks.append({'name':name, 'passed':bool(passed)})
    if not passed:
        raise ValueError(name)

check('input_sha256_matches_frozen_original',report['input_sha256']==hashlib.sha256(OLD.read_bytes()).hexdigest())
check('output_sha256_matches_current_extract',report['output_sha256']==hashlib.sha256(CURRENT.read_bytes()).hexdigest())
check('only_success_statuses_in_output',all(r['execution_status'] in blocks.SUCCESS_STATUSES for r in new))
fields = list(old[0])
def original_key(row): return tuple(row[field] for field in fields)
new_keys = Counter(original_key(r) for r in new)
expected = Counter()
manifest = []
statuses = Counter()
receipts = {}
network_events = Counter()
failed_rows = []
for height in sorted({int(r['block_height']) for r in old}):
    block = blocks.fetch_block(height,offline=True)
    check(f'cached_height_{height}',block is not None and block['height']==height)
    network_events.update((str(height),rid,caller,log,status) for rid,caller,log,status in block['events'])
    manifest.append({'height':height,'file':f'data/blocks/cache/{height}.json',
        'sha256':hashlib.sha256((blocks.CACHE/f'{height}.json').read_bytes()).hexdigest(),
        'source':blocks.NEARDATA.format(h=height)})
    for row in (r for r in old if int(r['block_height'])==height):
        rc=block['receipts'].get(row['receipt_id'])
        check(f"provenance_{height}_{row['receipt_id']}_{hashlib.sha256(row['log'].encode()).hexdigest()[:12]}",
            rc is not None and row['log'] in rc['logs'] and row['caller']==rc['caller']
            and int(row['block_timestamp'])==block['ts'])
        status=rc['status']
        check('recognized_status',status in blocks.SUCCESS_STATUSES|{'FAILURE'})
        if status == 'FAILURE':
            failed_rows.append(dict(row, execution_status=status, verification_source=blocks.NEARDATA.format(h=height)))
        statuses[status]+=1
        receipts[row['receipt_id']]=status
        if status in blocks.SUCCESS_STATUSES:
            expected[original_key(row)]+=1
check('output_exactly_equals_successful_original_events',expected==new_keys)
output_network_keys=Counter((r['block_height'],r['receipt_id'],r['caller'],r['log'],r['execution_status']) for r in new)
check('all_successful_logs_from_revalidated_event_blocks_are_present',network_events==output_network_keys)
check('report_counts_match_original',report['input_events']==len(old))
check('report_counts_match_output',report['accepted_events']==len(new))
check('report_counts_match_failures',report['failed_events_removed']==statuses['FAILURE'])
check('all_events_accounted',len(old)==len(new)+statuses['FAILURE'])
summary={'verified_at_utc':datetime.now(timezone.utc).isoformat(),'blocks':len(manifest),
    'input_events':len(old),'accepted_events':len(new),'removed_failed_events':statuses['FAILURE'],
    'event_statuses':dict(statuses),'unique_receipts':len(receipts),'receipt_statuses':dict(Counter(receipts.values())),
    'checks_passed':len(checks),'input_sha256':report['input_sha256'],'output_sha256':report['output_sha256'],
    'verification_scope':'Public-source reconciliation; no cryptographic execution proof claimed.'}
(OUT/'revalidation-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
(OUT/'block-cache-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
(OUT/'excluded-failed-events.json').write_text(json.dumps(failed_rows,indent=2)+'\n')
(OUT/'provenance-checks.json').write_text(json.dumps(checks,indent=2)+'\n')
print(json.dumps(summary,indent=2),flush=True)
