"""Пути репозитория vector_checker (без привязки к конкретной модели)."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent

WORK_DIR = REPO_ROOT / "work"
EXCEL_DIR = WORK_DIR / "excel"
REPORTS_DIR = WORK_DIR / "reports"
FIXTURES_DIR = REPO_ROOT / "fixtures" / "synthetic"
QUERIES_DIR = REPO_ROOT / "queries"

DEFAULT_QUERY_PATH = QUERIES_DIR / "Сутяжность.txt"
DEFAULT_QUERY_OUT = WORK_DIR / "query_for_1c.txt"
DEFAULT_SAMPLE_META = WORK_DIR / "sampled_losses.json"

# Ключ сверки и колонки, которые обычно не сравниваем как фичи.
KEY_COL = "LOSS_NUMBER"
PRED_COLS = ("preds_cf", "preds_rg")

# Опциональный список фич. Пустой / None → сверка всех общих колонок.
DEFAULT_FEATURES: tuple[str, ...] = ()


def ensure_work_dirs() -> None:
    """Создать work/excel/reports/fixtures при необходимости."""
    for path in (WORK_DIR, EXCEL_DIR, REPORTS_DIR, FIXTURES_DIR, QUERIES_DIR):
        path.mkdir(parents=True, exist_ok=True)


def resolve_dataset(explicit: str | Path | None = None) -> Path:
    """Путь к parquet/датасету: --df / VECTOR_CHECKER_DF_PATH (обязателен явно)."""
    if explicit is not None:
        path = Path(explicit)
        if not path.is_file():
            raise FileNotFoundError(f"Датасет не найден: {path}")
        return path.resolve()

    env_path = os.environ.get("VECTOR_CHECKER_DF_PATH", "").strip()
    if env_path:
        path = Path(env_path)
        if path.is_file():
            return path.resolve()
        raise FileNotFoundError(f"VECTOR_CHECKER_DF_PATH не найден: {path}")

    raise FileNotFoundError(
        "Укажите датасет: --df path/to/dataset.parquet "
        "или переменную окружения VECTOR_CHECKER_DF_PATH"
    )


def resolve_query(explicit: str | Path | None = None) -> Path:
    """Путь к шаблону запроса 1С: --query / VECTOR_CHECKER_QUERY_PATH / queries/."""
    if explicit is not None:
        path = Path(explicit)
        if not path.is_file():
            raise FileNotFoundError(f"Шаблон запроса не найден: {path}")
        return path.resolve()

    env_path = os.environ.get("VECTOR_CHECKER_QUERY_PATH", "").strip()
    if env_path:
        path = Path(env_path)
        if path.is_file():
            return path.resolve()
        raise FileNotFoundError(f"VECTOR_CHECKER_QUERY_PATH не найден: {path}")

    if DEFAULT_QUERY_PATH.is_file():
        return DEFAULT_QUERY_PATH.resolve()

    raise FileNotFoundError(
        "Укажите шаблон: --query path/to/query.txt "
        f"или положите файл в {DEFAULT_QUERY_PATH}"
    )
