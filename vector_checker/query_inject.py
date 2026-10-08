"""Подстановка списка ключей (LOSS_NUMBER) в текст запроса 1С."""

from __future__ import annotations

import json
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

# Пробелы/тонкие пробелы как разделители тысяч в выгрузках 1С (в т.ч. \xa0).
_THOUSAND_SEP_RE = re.compile(r"[\s\u00a0\u202f\u2009'`]+")

# Маркеры шаблона с одним параметром &Убыток (как в queries/Сутяжность.txt).
_FIRST_FILTER = "Убыток.Ссылка = &Убыток"
_AUDANET_FILTER = "СрезПервых(, Убыток = &Убыток)"
_FINAL_FILTER = "ЗаявлениеНаВыплату.Убыток = &Убыток"

_AUDANET_REPLACEMENT = (
    "СрезПервых(, Убыток В (ВЫБРАТЬ втУбыток.Убыток ИЗ втУбыток))"
)
_FINAL_REPLACEMENT = (
    "ЗаявлениеНаВыплату.Убыток В (ВЫБРАТЬ втУбыток.Убыток ИЗ втУбыток)"
)


def read_query_text(path: Path) -> tuple[str, str]:
    """Прочитать запрос; вернуть (текст, encoding). Сначала cp1251, затем utf-8."""
    raw = path.read_bytes()
    for encoding in ("cp1251", "utf-8-sig", "utf-8"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Не удалось декодировать запрос: {path}")


def normalize_loss_number(value: object) -> str:
    """Нормализовать LOSS_NUMBER: ``8513115.0`` / ``8\\xa0513\\xa0115`` → ``8513115``."""
    if value is None or (not isinstance(value, (list, dict, set)) and pd.isna(value)):
        return ""
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value).strip()

    text = _THOUSAND_SEP_RE.sub("", str(value).strip())
    if not text or text.lower() in {"nan", "none", "null"}:
        return ""
    text = text.replace(",", ".")
    try:
        num = float(text)
        if num.is_integer():
            return str(int(num))
        return str(num)
    except ValueError:
        return text


def format_loss_literals(
    loss_numbers: Sequence[object],
    *,
    as_strings: bool = True,
) -> str:
    """Список литералов для конструкции ``В (...)`` в языке запросов 1С."""
    parts: list[str] = []
    for value in loss_numbers:
        text = normalize_loss_number(value)
        if not text:
            continue
        if as_strings:
            escaped = text.replace('"', '""')
            parts.append(f'"{escaped}"')
        else:
            parts.append(text)
    if not parts:
        raise ValueError("Пустой список LOSS_NUMBER для подстановки в запрос")
    return ", ".join(parts)


def inject_loss_numbers(
    query_text: str,
    loss_numbers: Sequence[object],
    *,
    as_strings: bool = True,
) -> str:
    """Заменить единственный ``&Убыток`` на фильтр по номерам + ``В (втУбыток)``."""
    literals = format_loss_literals(loss_numbers, as_strings=as_strings)
    first_replacement = f"Убыток.Номер В ({literals})"

    missing = [
        marker
        for marker in (_FINAL_FILTER, _AUDANET_FILTER, _FIRST_FILTER)
        if marker not in query_text
    ]
    if missing:
        raise ValueError(
            "В тексте запроса не найдены ожидаемые маркеры: "
            + ", ".join(repr(m) for m in missing)
        )

    result = query_text.replace(_FINAL_FILTER, _FINAL_REPLACEMENT, 1)
    result = result.replace(_AUDANET_FILTER, _AUDANET_REPLACEMENT, 1)
    result = result.replace(_FIRST_FILTER, first_replacement, 1)

    if "&Убыток" in result:
        raise ValueError(
            "После подстановки в запросе остался параметр &Убыток — "
            "проверьте шаблон запроса"
        )
    return result


def build_query_header(
    n_losses: int,
    source_df: Path | None = None,
    *,
    n_total: int | None = None,
    random_seed: int | None = None,
) -> str:
    """Комментарий в шапке файла для 1С."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    src = str(source_df) if source_df else "—"
    sample_line = ""
    if n_total is not None and random_seed is not None and n_losses < n_total:
        sample_line = f"// sample: {n_losses} из {n_total}, random_seed={random_seed}\n"
    elif n_total is not None:
        sample_line = f"// sample: все {n_losses} (из {n_total})\n"
    return (
        f"// vector_checker: {n_losses} ключей; сгенерировано {ts}\n"
        f"{sample_line}"
        f"// source df: {src}\n"
        "// Рабочая копия для консоли 1С (не шаблон).\n"
        "\n"
    )


def write_injected_query(
    query_path: Path,
    loss_numbers: Sequence[object],
    out_path: Path,
    *,
    source_df: Path | None = None,
    as_strings: bool = True,
    encoding_out: str | None = None,
    n_total: int | None = None,
    random_seed: int | None = None,
) -> Path:
    """Прочитать шаблон, подставить номера, записать промежуточный файл."""
    losses_list = list(loss_numbers)
    text, encoding_in = read_query_text(query_path)
    injected = inject_loss_numbers(text, losses_list, as_strings=as_strings)
    header = build_query_header(
        len(losses_list),
        source_df=source_df,
        n_total=n_total,
        random_seed=random_seed,
    )
    body = injected
    if body.lstrip().startswith("// vector_checker:"):
        idx = body.find("ВЫБРАТЬ")
        if idx > 0:
            body = body[idx:]
    out_encoding = encoding_out or encoding_in
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes((header + body).encode(out_encoding))
    return out_path


def write_sample_meta(
    path: Path,
    losses: Sequence[str],
    *,
    source_df: Path | None = None,
    query_path: Path | None = None,
    n_total: int,
    n: int | None,
    random_seed: int,
) -> Path:
    """Сохранить список выбранных ключей для воспроизводимого compare."""
    payload = {
        "n": n,
        "n_total": n_total,
        "n_sampled": len(losses),
        "random_seed": random_seed,
        "source_df": str(source_df) if source_df else None,
        "query_path": str(query_path) if query_path else None,
        "loss_numbers": list(losses),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_sample_meta(path: Path) -> dict:
    """Прочитать sampled_losses.json."""
    return json.loads(path.read_text(encoding="utf-8"))


def unique_loss_numbers(values: Iterable[object]) -> list[str]:
    """Уникальные ключи с сохранением порядка."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = normalize_loss_number(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def sample_loss_numbers(
    loss_numbers: Sequence[object],
    n: int | None = None,
    *,
    random_seed: int = 42,
) -> list[str]:
    """Уникальные ключи; при ``n`` — случайная выборка с фиксированным seed."""
    unique = unique_loss_numbers(loss_numbers)
    if n is None:
        return unique
    if n < 0:
        raise ValueError(f"n должно быть >= 0, получено {n}")
    if n >= len(unique):
        return unique
    rng = random.Random(int(random_seed))
    return rng.sample(unique, n)
