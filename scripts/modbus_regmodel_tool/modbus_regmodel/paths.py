"""Разрешение путей вывода .h/.c файлов относительно YAML-файла."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

DEFAULT_HEADER_NAME = "modbus_reg_model.h"
DEFAULT_SOURCE_NAME = "modbus_reg_model.c"
DEFAULT_DOCS_NAME = "modbus_reg_model.md"


@dataclass
class OutputSpec:
    header_path: str
    source_path: str
    docs_path: str


def resolve_output_paths(yaml_path: str, output_cfg: Optional[dict]) -> OutputSpec:
    """
    Разрешает пути к .h/.c/.md файлам относительно директории YAML-файла.

    Пути в YAML (`output.header`, `output.source`, `output.docs`) задаются
    относительно расположения самого YAML-файла и могут содержать '..' для
    подъёма на уровень выше (например, YAML лежит в data/, а исходники
    проекта - в соседней source/). Разрешение выполняется через
    os.path.normpath(os.path.join(yaml_dir, relative_path)) - это стандартная
    файловая семантика ОС, поэтому произвольная вложенность '..' поддерживается
    автоматически, без специальной обработки.

    Если какой-то из путей не задан, соответствующий файл кладётся рядом с
    YAML под именем по умолчанию.
    """
    output_cfg = output_cfg or {}
    yaml_dir = os.path.dirname(os.path.abspath(yaml_path))

    header_rel = output_cfg.get('header', DEFAULT_HEADER_NAME)
    source_rel = output_cfg.get('source', DEFAULT_SOURCE_NAME)
    docs_rel = output_cfg.get('docs', DEFAULT_DOCS_NAME)

    if not all(isinstance(v, str) for v in (header_rel, source_rel, docs_rel)):
        raise ValueError("output.header, output.source и output.docs должны быть строками")

    header_path = os.path.normpath(os.path.join(yaml_dir, header_rel))
    source_path = os.path.normpath(os.path.join(yaml_dir, source_rel))
    docs_path = os.path.normpath(os.path.join(yaml_dir, docs_rel))
    return OutputSpec(header_path=header_path, source_path=source_path, docs_path=docs_path)
