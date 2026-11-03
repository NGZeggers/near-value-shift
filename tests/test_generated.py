from near_thesis.check_generated import same_artifact


def test_numeric_precision_allowed_but_stale_market_cap_rejected():
    baseline = b'chain,market_cap\nNear,5081673866.0\n'
    assert same_artifact('peers.csv', baseline, b'chain,market_cap\nNear,5081673866.000001\n')
    assert not same_artifact('peers.csv', baseline, b'chain,market_cap\nNear,5068386772.0\n')
    assert not same_artifact('peers.csv', baseline, b'chain,market_cap\nSui,5081673866.0\n')


def test_source_hashes_and_argument_require_exact_matches():
    assert not same_artifact('model.json', b'{"hash":"abc","p":0.1}', b'{"hash":"def","p":0.1}')
    assert not same_artifact('THESIS.md', b'rejected', b'inconclusive')
