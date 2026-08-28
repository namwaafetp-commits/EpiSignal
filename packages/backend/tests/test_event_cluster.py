from episignal_backend.db.types import Precision
from episignal_backend.events.cluster import precision_weight


def test_precision_weights():
    assert precision_weight(Precision.PLACE) == 1.0
    assert precision_weight(Precision.ADMIN2) == 0.75
    assert precision_weight(Precision.ADMIN1) == 0.5
    assert precision_weight(Precision.COUNTRY) == 0.25
    assert precision_weight(Precision.UNRESOLVED) == 0.0


def test_precision_weights_strictly_decreasing():
    precisions = [
        Precision.PLACE,
        Precision.ADMIN2,
        Precision.ADMIN1,
        Precision.COUNTRY,
        Precision.UNRESOLVED,
    ]
    weights = [precision_weight(p) for p in precisions]
    for i in range(len(weights) - 1):
        assert weights[i] > weights[i + 1]
