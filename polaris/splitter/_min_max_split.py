import datamol as dm
from typing import Callable, Union, Optional, List

import numpy as np
from loguru import logger
from sklearn.model_selection import BaseShuffleSplit
from sklearn.model_selection._split import _validate_shuffle_split
from sklearn.utils.validation import _num_samples


class MinMaxSplit(BaseShuffleSplit):
    """Group-based split that uses the k-Mean clustering in the input space for splitting."""

    def __init__(
        self,
        n_splits: int = 5,
        smiles: Optional[List[str]] = None,
        *,
        test_size=None,
        train_size=None,
        random_state=None,
    ):
        super().__init__(
            n_splits=n_splits,
            test_size=test_size,
            train_size=train_size,
            random_state=random_state,
        )
        self._smiles = smiles

    def _iter_indices(self, X, y=None, groups=None):
        """Generate (train, test) indices"""

        n_samples = _num_samples(X)
        n_train, n_test = _validate_shuffle_split(
            n_samples,
            self.test_size,
            self.train_size,
            default_test_size=self._default_test_size,
        )

        is_smiles = all(isinstance(x, str) for x in X)
        if self._smiles is None and not is_smiles:
            raise ValueError(
                "If the input is not a list of SMILES, you need to provide the SMILES to the constructor."
            )

        base_seed = self.random_state
        if base_seed is None:
            base_seed = 0

        smiles = X if is_smiles else self._smiles
        mols = dm.utils.parallelized(dm.to_mol, smiles, n_jobs=1, progress=False)

        for i in range(self.n_splits):
            picked_samples, _ = dm.pick_diverse(mols=mols, npick=n_train, seed=base_seed + i)

            yield picked_samples, np.setdiff1d(np.arange(n_samples), picked_samples)
