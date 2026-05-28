import can
from typing import List, Optional

from .can_parser import decode_can


def decode(batch_id: str, data_file: str, dbc_files: List[str],
           batch_size: int = 5000, signal_filter_list: Optional[List[str]] = None):
    return decode_can(
        parser_type="blf",
        batch_id=batch_id,
        data_file=data_file,
        dbc_files=dbc_files,
        reader_class=can.BLFReader,
        reader_kwargs={},
        batch_size=batch_size,
        signal_filter_list=signal_filter_list,
    )
