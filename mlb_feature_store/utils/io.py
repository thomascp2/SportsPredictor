from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from loguru import logger


def save_parquet(df: pd.DataFrame, path: Path) -> None:
    """
    Save a DataFrame to Parquet (snappy compressed), creating parent dirs as needed.

    Args:
        df: DataFrame to persist.
        path: Destination file path.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, path, compression="snappy")
    logger.debug(f"Saved {len(df):,} rows -> {path}")


def load_parquet(path: Path) -> pd.DataFrame:
    """
    Load a Parquet file. Returns an empty DataFrame if the file does not exist.

    Args:
        path: File path to read.

    Returns:
        Loaded DataFrame, or empty DataFrame on missing file.
    """
    path = Path(path)
    if not path.exists():
        logger.warning(f"Parquet file not found: {path}")
        return pd.DataFrame()
    return pd.read_parquet(path)


def load_parquet_dir(directory: Path, pattern: str = "*.parquet") -> pd.DataFrame:
    """
    Load all Parquet files matching a glob pattern in a directory into one DataFrame.

    Args:
        directory: Directory to search.
        pattern: Glob pattern for file matching.

    Returns:
        Concatenated DataFrame, or empty DataFrame if no files found.
    """
    directory = Path(directory)
    files = sorted(directory.glob(pattern))
    if not files:
        logger.warning(f"No parquet files found in {directory} matching '{pattern}'")
        return pd.DataFrame()
    frames = [pd.read_parquet(f) for f in files]
    df = pd.concat(frames, ignore_index=True)
    logger.debug(f"Loaded {len(df):,} rows from {len(files)} files in {directory}")
    return df
