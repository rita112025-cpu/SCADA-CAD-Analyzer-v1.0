import pytest
from name_normalizer import normalize_name


@pytest.mark.parametrize('names', [('RTU01','RTU-01','RTU_01'), ('RACK01','RACK-01','RACK_01'), ('trayX600','TRAY-X600','TRAY_X600')])
def test_equivalent_candidates(names):
    assert len({normalize_name(n)['normalized_name'] for n in names}) == 1
    assert normalize_name(names[1])['raw_name'] == names[1]


def test_track_is_not_rack():
    assert normalize_name('TRACK01')['normalized_name'] != normalize_name('RACK01')['normalized_name']
