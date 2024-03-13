import uuid
from typing import TYPE_CHECKING, Optional

import datamol as dm
import pandas as pd
from rdkit import Chem

from polaris.dataset import ColumnAnnotation, Modality
from polaris.dataset.converters._base import Converter, FactoryProduct

if TYPE_CHECKING:
    from polaris.dataset import DatasetFactory


class SDFConverter(Converter):
    """Convert from a SDF file"""

    def __init__(
        self,
        mol_column: str = "molecule",
        smiles_column: Optional[str] = "smiles",
        mol_id_column: Optional[str] = None,
        mol_prop_as_cols: bool = True,
        groupby_key: Optional[str] = None,
        n_jobs: int = 1,
    ) -> None:
        """ """
        super().__init__()
        self.mol_column = mol_column
        self.smiles_column = smiles_column
        self.mol_id_column = mol_id_column
        self.mol_prop_as_cols = mol_prop_as_cols
        self.groupby_key = groupby_key
        self.n_jobs = n_jobs

    def convert(self, path: str, factory: "DatasetFactory") -> FactoryProduct:
        """
        Converts the molecules in an SDF file to a Polaris compatible format.
        """

        tmp_col = uuid.uuid4().hex

        # We do not sanitize the molecules or remove the Hs.
        # We assume the SDF has been processed by the user already and do not want to change it.
        df = dm.read_sdf(
            path,
            as_df=self.mol_prop_as_cols,
            smiles_column=self.smiles_column,
            mol_column=tmp_col,
            remove_hs=False,
            sanitize=False,
        )

        if not isinstance(df, pd.DataFrame):
            df = pd.DataFrame({tmp_col: df})

        if self.mol_column in df.columns:
            raise ValueError(
                f"The column name '{self.mol_column}' clashes with the name of a property in the SDF file. "
                f"Please choose another name by setting the `mol_column` in the {self.__class__.__name__}."
            )

        # Add a column with the molecule name if it doesn't exist yet
        if self.mol_id_column is not None and self.mol_id_column not in df.columns:

            def _get_name(mol: dm.Mol):
                return mol.GetProp(self.mol_id_column) if mol.HasProp(self.mol_id_column) else None

            names = dm.parallelized(_get_name, df[tmp_col], n_jobs=self.n_jobs, scheduler="threads")
            df[self.mol_id_column] = names

        # Add a column with the SMILES if it doesn't exist yet
        if self.smiles_column is not None and self.smiles_column not in df.columns:
            names = dm.parallelized(
                lambda mol: dm.to_smiles(mol, isomeric=False), df[tmp_col], n_jobs=self.n_jobs
            )
            df[self.smiles_column] = names

        # Convert the molecules to binary strings (for ML purposes, this should be lossless).
        # This might not be the most storage efficient, but is fastest and easiest to maintain.
        # We do not save the MolProps, because we have already extracted these into columns.
        # See: https://github.com/rdkit/rdkit/discussions/7235

        # NOTE (cwognum): We might want to improve efficiency
        #  by not always storing private and computed properties.
        props = Chem.PropertyPickleOptions.AllProps
        if self.mol_prop_as_cols:
            props &= ~Chem.PropertyPickleOptions.MolProps
        bytes_data = [mol.ToBinary(props) for mol in df[tmp_col]]

        df.drop(columns=[tmp_col], inplace=True)

        # Create the zarr array
        factory.zarr_root.array(self.mol_column, bytes_data, dtype=bytes)

        # Add a pointer column to the table
        # We support grouping by a key, to allow inputs of variable length

        grouped = pd.DataFrame(columns=[*df.columns, self.mol_column])
        if self.groupby_key is not None:
            for _, group in df.reset_index(drop=True).groupby(by=self.groupby_key):
                start = group.index[0]
                end = group.index[-1]

                if group.nunique().sum() != len(group.columns):
                    raise ValueError(
                        f"After grouping by {self.groupby_key}, values for other columns are not unique within a group. "
                        "Please handle this manually to ensure aggregation is done correctly."
                    )

                # Get the pointer path
                pointer_idx = f"{start}:{end}" if start != end else f"{start}"
                pointer = self.get_pointer(factory.zarr_root_path, self.mol_column, pointer_idx)

                # Get the single unique value per column for the group and append
                unique_values = [group[col].unique()[0] for col in df.columns]
                grouped.loc[len(grouped)] = [*unique_values, pointer]

            df = grouped

        else:
            pointers = [self.get_pointer(factory.zarr_root_path, self.mol_column, i) for i in range(len(df))]
            df[self.mol_column] = pd.Series(pointers)

        # Set the annotations
        annotations = {self.mol_column: ColumnAnnotation(is_pointer=True, modality=Modality.MOLECULE_3D)}
        if self.smiles_column is not None:
            annotations[self.smiles_column] = ColumnAnnotation(modality=Modality.MOLECULE)

        # Return the dataframe and the annotations
        return df, annotations
