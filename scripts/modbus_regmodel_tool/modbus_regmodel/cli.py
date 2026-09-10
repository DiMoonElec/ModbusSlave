"""Точка входа: YAML -> валидация -> генерация .h/.c."""
from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

from .codegen import generate_header, generate_source
from .docgen import generate_markdown
from .model import parse_spec
from .validate import validate_model


def run(yaml_path: str, *, dry_run: bool = False) -> int:
    result = parse_spec(yaml_path)
    errors = list(result.errors)

    # Перекрёстную валидацию имеет смысл запускать, только если структурный
    # разбор прошёл чисто - иначе плоская модель может быть неполной/некорректной.
    if not errors:
        errors.extend(validate_model(result.registers))

    if errors:
        print(f"НАЙДЕНЫ ОШИБКИ ({len(errors)}):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    registers = sorted(result.registers, key=lambda r: r.addr)

    header_text = generate_header()
    source_text = generate_source(registers, result.includes)
    docs_text = generate_markdown(result)

    print(f"Валидация прошла успешно. Регистров в плоской модели: {len(registers)}.")

    if dry_run:
        print(f"[dry-run] .h будет записан в: {result.output.header_path}")
        print(f"[dry-run] .c будет записан в: {result.output.source_path}")
        print(f"[dry-run] .md будет записан в: {result.output.docs_path}")
        return 0

    for path, text in (
        (result.output.header_path, header_text),
        (result.output.source_path, source_text),
        (result.output.docs_path, docs_text),
    ):
        out_dir = os.path.dirname(path) or "."
        os.makedirs(out_dir, exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)

    print(f"Записан заголовок:      {result.output.header_path}")
    print(f"Записан исходник:       {result.output.source_path}")
    print(f"Записана документация:  {result.output.docs_path}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="modbus-regmodel",
        description="Генератор диспетчера Modbus holding-регистров из YAML-спецификации.",
    )
    parser.add_argument("yaml_path", help="Путь к YAML-файлу регистровой модели")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Только проверить файл и показать пути вывода, не записывая .h/.c",
    )
    args = parser.parse_args(argv)
    return run(args.yaml_path, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
