"""Сравнение фич датафрейма модели и Excel-выгрузки из 1С."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from .paths import DEFAULT_FEATURES, KEY_COL, PRED_COLS
from .query_inject import normalize_loss_number


@dataclass
class CompareReport:
    """Итог сверки векторов."""

    ok: bool
    n_service: int
    n_excel: int
    n_matched_keys: int
    n_only_service: int
    n_only_excel: int
    n_mismatch_cells: int
    features_compared: list[str] = field(default_factory=list)
    features_missing_in_excel: list[str] = field(default_factory=list)
    features_missing_in_service: list[str] = field(default_factory=list)
    only_service_losses: list[str] = field(default_factory=list)
    only_excel_losses: list[str] = field(default_factory=list)
    mismatch_preview: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _normalize_loss_key(series: pd.Series) -> pd.Series:
    return series.map(normalize_loss_number)


def _normalize_value(value: object) -> object:
    """Привести значение к сопоставимому виду для 1:1 сверки."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        ts = pd.Timestamp(value)
        if pd.isna(ts):
            return None
        return ts.isoformat(sep="T", timespec="seconds")
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        if float(value).is_integer():
            return int(value)
        return float(value)
    text = str(value).strip()
    if text == "" or text.lower() in {"nan", "none", "null"}:
        return None
    try:
        num = float(text.replace(",", "."))
        if num.is_integer():
            return int(num)
        return num
    except ValueError:
        return text


def _values_equal(left: object, right: object, *, rtol: float = 0.0) -> bool:
    a = _normalize_value(left)
    b = _normalize_value(right)
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if rtol > 0:
            return bool(np.isclose(float(a), float(b), rtol=rtol, atol=0.0, equal_nan=True))
        return float(a) == float(b)
    return a == b


def resolve_feature_columns(
    service_df: pd.DataFrame,
    excel_df: pd.DataFrame,
    *,
    features: Sequence[str] | None = None,
    all_overlap: bool = False,
    key_col: str = KEY_COL,
) -> tuple[list[str], list[str], list[str]]:
    """Колонки для сверки + списки отсутствующих."""
    service_cols = set(service_df.columns)
    excel_cols = set(excel_df.columns)

    use_overlap = all_overlap or not features
    if use_overlap and not features:
        skip = {key_col, *PRED_COLS}
        candidates = sorted((service_cols & excel_cols) - skip)
    else:
        candidates = list(features or DEFAULT_FEATURES)

    compared = [c for c in candidates if c in service_cols and c in excel_cols]
    missing_excel = [c for c in candidates if c in service_cols and c not in excel_cols]
    missing_service = [c for c in candidates if c in excel_cols and c not in service_cols]
    return compared, missing_excel, missing_service


def load_excel_export(path: Path) -> pd.DataFrame:
    """Загрузить выгрузку 1С (xlsx/xls/csv/parquet)."""
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, engine="openpyxl" if suffix == ".xlsx" else None)
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".parquet":
        return pd.read_parquet(path)
    raise ValueError(f"Неподдерживаемый формат выгрузки: {path.suffix}")


def compare_feature_frames(
    service_df: pd.DataFrame,
    excel_df: pd.DataFrame,
    *,
    features: Sequence[str] | None = None,
    all_overlap: bool = False,
    rtol: float = 0.0,
    preview_limit: int = 50,
    key_col: str = KEY_COL,
) -> tuple[CompareReport, pd.DataFrame]:
    """Сверить фичи по key_col. Возвращает отчёт и таблицу расхождений."""
    if key_col not in service_df.columns:
        raise KeyError(f"В датасете нет колонки {key_col}")
    if key_col not in excel_df.columns:
        raise KeyError(f"В Excel нет колонки {key_col}")

    compared, missing_excel, missing_service = resolve_feature_columns(
        service_df,
        excel_df,
        features=features,
        all_overlap=all_overlap,
        key_col=key_col,
    )
    if not compared:
        raise ValueError(
            "Нет общих колонок для сверки. "
            f"Нет в Excel: {missing_excel[:10]}; нет в service: {missing_service[:10]}"
        )

    left = service_df.copy()
    right = excel_df.copy()
    left["_key"] = _normalize_loss_key(left[key_col])
    right["_key"] = _normalize_loss_key(right[key_col])
    left = left[left["_key"] != ""].drop_duplicates("_key", keep="first")
    right = right[right["_key"] != ""].drop_duplicates("_key", keep="first")

    left_keys = set(left["_key"])
    right_keys = set(right["_key"])
    only_service = sorted(left_keys - right_keys)
    only_excel = sorted(right_keys - left_keys)
    common = sorted(left_keys & right_keys)

    left_i = left.set_index("_key").loc[common]
    right_i = right.set_index("_key").loc[common]

    rows: list[dict] = []
    for key in common:
        for col in compared:
            lv = left_i.at[key, col] if col in left_i.columns else None
            rv = right_i.at[key, col] if col in right_i.columns else None
            if not _values_equal(lv, rv, rtol=rtol):
                rows.append(
                    {
                        key_col: key,
                        "feature": col,
                        "service": _normalize_value(lv),
                        "excel": _normalize_value(rv),
                    }
                )

    mismatches = pd.DataFrame(rows, columns=[key_col, "feature", "service", "excel"])
    report = CompareReport(
        ok=(len(only_service) == 0 and len(only_excel) == 0 and len(rows) == 0),
        n_service=len(left),
        n_excel=len(right),
        n_matched_keys=len(common),
        n_only_service=len(only_service),
        n_only_excel=len(only_excel),
        n_mismatch_cells=len(rows),
        features_compared=compared,
        features_missing_in_excel=missing_excel,
        features_missing_in_service=missing_service,
        only_service_losses=only_service[:100],
        only_excel_losses=only_excel[:100],
        mismatch_preview=rows[:preview_limit],
    )
    return report, mismatches


def write_compare_artifacts(
    report: CompareReport,
    mismatches: pd.DataFrame,
    reports_dir: Path,
    stem: str = "vector_compare",
    paired: pd.DataFrame | None = None,
) -> tuple[Path, Path]:
    """Записать JSON-отчёт и CSV с расхождениями (long + опционально paired)."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / f"{stem}.json"
    csv_path = reports_dir / f"{stem}_mismatches.csv"
    json_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    mismatches.to_csv(csv_path, index=False, encoding="utf-8-sig")
    if paired is not None:
        paired_path = reports_dir / f"{stem}_paired.csv"
        paired.to_csv(paired_path, index=False, encoding="utf-8-sig")
    return json_path, csv_path


def report_to_frame(report: CompareReport) -> pd.DataFrame:
    """Краткая сводка отчёта одной строкой."""
    return pd.DataFrame(
        [
            {
                "ok": report.ok,
                "n_service": report.n_service,
                "n_excel": report.n_excel,
                "n_matched_keys": report.n_matched_keys,
                "n_only_service": report.n_only_service,
                "n_only_excel": report.n_only_excel,
                "n_mismatch_cells": report.n_mismatch_cells,
                "n_features_compared": len(report.features_compared),
                "n_missing_in_excel": len(report.features_missing_in_excel),
                "n_missing_in_service": len(report.features_missing_in_service),
            }
        ]
    )


def mismatch_feature_counts(mismatches: pd.DataFrame) -> pd.DataFrame:
    """Сколько раз каждая фича расходится (без процентов)."""
    if mismatches.empty:
        return pd.DataFrame(columns=["feature", "n_mismatch"])
    return (
        mismatches.groupby("feature", as_index=False)
        .size()
        .rename(columns={"size": "n_mismatch"})
        .sort_values("n_mismatch", ascending=False)
        .reset_index(drop=True)
    )


def feature_match_stats(
    mismatches: pd.DataFrame,
    *,
    features: Sequence[str],
    n_keys: int,
) -> pd.DataFrame:
    """По каждой колонке: совпадения / расхождения и ``match_pct`` среди общих ключей."""
    if n_keys < 0:
        raise ValueError(f"n_keys должно быть >= 0, получено {n_keys}")

    counts: dict[str, int] = {}
    if not mismatches.empty and "feature" in mismatches.columns:
        counts = mismatches.groupby("feature").size().astype(int).to_dict()

    rows: list[dict] = []
    for feat in features:
        n_mismatch = int(counts.get(feat, 0))
        n_match = max(n_keys - n_mismatch, 0)
        match_pct = round(100.0 * n_match / n_keys, 2) if n_keys else float("nan")
        rows.append(
            {
                "feature": feat,
                "n_keys": n_keys,
                "n_match": n_match,
                "n_mismatch": n_mismatch,
                "match_pct": match_pct,
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=["feature", "n_keys", "n_match", "n_mismatch", "match_pct"]
        )
    return (
        pd.DataFrame(rows)
        .sort_values(["match_pct", "n_mismatch", "feature"], ascending=[True, False, True])
        .reset_index(drop=True)
    )


def mismatched_keys(mismatches: pd.DataFrame, key_col: str = KEY_COL) -> list[str]:
    """Уникальные ключи, у которых есть хотя бы одно расхождение."""
    if mismatches.empty or key_col not in mismatches.columns:
        return []
    return (
        mismatches[key_col]
        .map(normalize_loss_number)
        .loc[lambda s: s != ""]
        .drop_duplicates()
        .tolist()
    )


def paired_compare_frame(
    service_df: pd.DataFrame,
    excel_df: pd.DataFrame,
    *,
    keys: Sequence[object] | None = None,
    features: Sequence[str] | None = None,
    mismatches: pd.DataFrame | None = None,
    only_mismatch_cols: bool = True,
    key_col: str = KEY_COL,
    source_col: str = "source",
) -> pd.DataFrame:
    """Две строки на ключ: ``source=service|excel``, колонки = фичи.

    Так удобно сравнивать один ``LOSS_NUMBER`` фильтром по ключу, без
    long-таблицы «фича × убыток» (которая на больших N убивает ноутбук).
    """
    left = service_df.copy()
    right = excel_df.copy()
    left["_key"] = _normalize_loss_key(left[key_col])
    right["_key"] = _normalize_loss_key(right[key_col])

    if keys is None:
        if mismatches is not None and not mismatches.empty:
            key_list = mismatched_keys(mismatches, key_col=key_col)
        else:
            key_list = sorted(set(left["_key"]) & set(right["_key"]) - {""})
    else:
        key_list = [normalize_loss_number(k) for k in keys]
        key_list = [k for k in key_list if k]

    cols, _, _ = resolve_feature_columns(
        service_df,
        excel_df,
        features=features,
        all_overlap=features is None,
        key_col=key_col,
    )

    mismatch_cols_by_key: dict[str, set[str]] = {}
    if only_mismatch_cols and mismatches is not None and not mismatches.empty:
        tmp = mismatches.copy()
        tmp["_key"] = tmp[key_col].map(normalize_loss_number)
        for key, grp in tmp.groupby("_key"):
            mismatch_cols_by_key[str(key)] = set(grp["feature"].astype(str))

    blocks: list[pd.DataFrame] = []
    for key in key_list:
        left_row = left.loc[left["_key"] == key]
        right_row = right.loc[right["_key"] == key]
        if left_row.empty and right_row.empty:
            continue

        if only_mismatch_cols and key in mismatch_cols_by_key:
            use_cols = [c for c in cols if c in mismatch_cols_by_key[key]]
        elif only_mismatch_cols and mismatches is not None:
            # ключ без записей в mismatches — пропускаем
            continue
        else:
            use_cols = list(cols)
        if not use_cols:
            continue

        def _one(row_df: pd.DataFrame, source: str) -> dict:
            out: dict = {key_col: key, source_col: source}
            if row_df.empty:
                for c in use_cols:
                    out[c] = None
                return out
            row = row_df.iloc[0]
            for c in use_cols:
                out[c] = row[c] if c in row_df.columns else None
            return out

        blocks.append(pd.DataFrame([_one(left_row, "service"), _one(right_row, "excel")]))

    if not blocks:
        return pd.DataFrame(columns=[key_col, source_col, *cols])
    return pd.concat(blocks, ignore_index=True)


def side_by_side_for_loss(
    service_df: pd.DataFrame,
    excel_df: pd.DataFrame,
    loss_number: object,
    features: Sequence[str] | None = None,
    *,
    key_col: str = KEY_COL,
) -> pd.DataFrame:
    """По одному ключу: фича | service | excel | match (для точечного разбора)."""
    key = normalize_loss_number(loss_number)
    left = service_df.copy()
    right = excel_df.copy()
    left["_key"] = _normalize_loss_key(left[key_col])
    right["_key"] = _normalize_loss_key(right[key_col])

    left_row = left.loc[left["_key"] == key]
    right_row = right.loc[right["_key"] == key]
    if left_row.empty and right_row.empty:
        raise KeyError(f"{key_col}={key} нет ни в service, ни в excel")

    cols, _, _ = resolve_feature_columns(
        service_df if not left_row.empty else excel_df,
        excel_df if not right_row.empty else service_df,
        features=features,
        all_overlap=features is None,
        key_col=key_col,
    )

    rows: list[dict] = []
    lv = left_row.iloc[0] if not left_row.empty else None
    rv = right_row.iloc[0] if not right_row.empty else None
    for col in cols:
        s_val = None if lv is None or col not in left_row.columns else lv[col]
        e_val = None if rv is None or col not in right_row.columns else rv[col]
        rows.append(
            {
                "feature": col,
                "service": _normalize_value(s_val),
                "excel": _normalize_value(e_val),
                "match": _values_equal(s_val, e_val),
            }
        )
    return pd.DataFrame(rows)
