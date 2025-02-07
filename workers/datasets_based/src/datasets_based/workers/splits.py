# SPDX-License-Identifier: Apache-2.0
# Copyright 2022 The HuggingFace Authors.

import logging
from http import HTTPStatus
from typing import Any, List, Literal, Mapping, Optional, TypedDict, Union

from datasets import get_dataset_config_names, get_dataset_split_names
from datasets.data_files import EmptyDatasetError as _EmptyDatasetError
from libcommon.exceptions import CustomError
from libcommon.simple_cache import SplitFullName

from datasets_based.workers._datasets_based_worker import DatasetsBasedWorker

SplitsWorkerErrorCode = Literal[
    "EmptyDatasetError",
    "SplitsNamesError",
]


class SplitWorkerError(CustomError):
    """Base class for worker exceptions."""

    def __init__(
        self,
        message: str,
        status_code: HTTPStatus,
        code: SplitsWorkerErrorCode,
        cause: Optional[BaseException] = None,
        disclose_cause: bool = False,
    ):
        super().__init__(
            message=message, status_code=status_code, code=str(code), cause=cause, disclose_cause=disclose_cause
        )


class SplitsNamesError(SplitWorkerError):
    """Raised when the split names could not be fetched."""

    def __init__(self, message: str, cause: Optional[BaseException] = None):
        super().__init__(message, HTTPStatus.INTERNAL_SERVER_ERROR, "SplitsNamesError", cause, True)


class EmptyDatasetError(SplitWorkerError):
    """Raised when the dataset has no data."""

    def __init__(self, message: str, cause: Optional[BaseException] = None):
        super().__init__(message, HTTPStatus.INTERNAL_SERVER_ERROR, "EmptyDatasetError", cause, True)


class SplitItem(TypedDict):
    dataset: str
    config: str
    split: str


class SplitsResponseContent(TypedDict):
    splits: List[SplitItem]


def get_dataset_split_full_names(dataset: str, use_auth_token: Union[bool, str, None] = False) -> List[SplitItem]:
    """Get the list of splits full names (split and config) for a dataset.

    Args:
        dataset (str): A dataset name. If the repository is namespaced (a user or an organization), the namespace and
          the dataset name are separated with a slash (`/`), for example: `user/dataset`.
        use_auth_token (Union[bool, str, None], optional): user token. It allows to retrieve the splits for gated
          datasets. Defaults to False (no authentication).

    Returns:
        List[SplitItem]: a list of splits full names: objects with the keys `dataset`, `config` and `split`. They
          are sorted alphabetically by configuration (config), but the splits order for a given configuration is
          preserved.
    """
    logging.info(f"get dataset '{dataset}' split full names")
    return [
        {"dataset": dataset, "config": str(config), "split": str(split)}
        for config in sorted(get_dataset_config_names(path=dataset, use_auth_token=use_auth_token))
        for split in get_dataset_split_names(path=dataset, config_name=config, use_auth_token=use_auth_token)
    ]


def compute_splits_response(
    dataset: str,
    hf_token: Optional[str] = None,
) -> SplitsResponseContent:
    """
    Get the response of /splits for one specific dataset on huggingface.co.
    Dataset can be private or gated if you pass an acceptable token.

    It is assumed that the dataset exist and can be accessed using the token.

    The list of splits might require the dataset to support the streaming mode. See
    https://github.dev/huggingface/datasets/blob/e183a269067575db8765ee979bd8523d14a1adae/src/datasets/inspect.py#L389-L390

    The /splits response generated by this function does not include the optional "stats" field. See ./parquet.py

    Args:
        dataset (`str`):
            A namespace (user or an organization) and a repo name separated
            by a `/`.
        hf_endpoint (`str`):
            The Hub endpoint (for example: "https://huggingface.co")
        hf_token (`str`, *optional*):
            An authentication token (See https://huggingface.co/settings/token)
    Returns:
        `SplitsResponseContent`: An object with the list of split names.
    <Tip>
    Raises the following errors:
        - [`~splits.worker.EmptyDatasetError`]
          The dataset is empty.
        - [`~splits.worker.SplitsNamesError`]
          If the list of splits could not be obtained using the datasets library.
    </Tip>
    """
    logging.info(f"get splits for dataset={dataset}")
    use_auth_token: Union[bool, str, None] = hf_token if hf_token is not None else False
    # get the list of splits in streaming mode
    try:
        split_items = get_dataset_split_full_names(dataset=dataset, use_auth_token=use_auth_token)
    except _EmptyDatasetError as err:
        raise EmptyDatasetError("The dataset is empty.", cause=err) from err
    except Exception as err:
        raise SplitsNamesError("Cannot get the split names for the dataset.", cause=err) from err
    # As a rule, null values should have their fields removed -> "stats" field is not included
    return {"splits": split_items}


class SplitsWorker(DatasetsBasedWorker):
    @staticmethod
    def get_job_type() -> str:
        return "/splits"

    @staticmethod
    def get_version() -> str:
        return "2.0.0"

    def compute(self) -> Mapping[str, Any]:
        return compute_splits_response(dataset=self.dataset, hf_token=self.common_config.hf_token)

    def get_new_splits(self, content: Mapping[str, Any]) -> set[SplitFullName]:
        """Get the set of new splits, from the content created by the compute."""
        return {SplitFullName(dataset=s["dataset"], config=s["config"], split=s["split"]) for s in content["splits"]}
