"""Single stratified 70/30 split, performed once and reused by every model."""

from __future__ import annotations

import pandas as pd
from sklearn.model_selection import train_test_split


def stratified_split(
    df: pd.DataFrame, label_col: str, test_size: float, seed: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    train_df, test_df = train_test_split(
        df,
        test_size=test_size,
        random_state=seed,
        stratify=df[label_col],
        shuffle=True,
    )
    return train_df.reset_index(drop=True), test_df.reset_index(drop=True)
