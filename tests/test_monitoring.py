import numpy as np
import pytest

from gridpulse.monitoring.quality import psi


def test_psi_identical_and_shift():
    reference = np.random.default_rng(42).normal(0, 1, 2000)
    assert psi(reference, reference) == pytest.approx(0)
    assert psi(reference, reference + 5) > 0.25


def test_psi_constant_shift_not_hidden():
    assert psi(np.zeros(100), np.zeros(100)) == 0
    assert psi(np.zeros(100), np.ones(100)) > 0.25


def test_psi_rejects_invalid_values():
    with pytest.raises(ValueError):
        psi(np.array([1, 2]), np.array([np.nan]))
