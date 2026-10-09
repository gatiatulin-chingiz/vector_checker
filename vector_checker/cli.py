"""CLI: prepare / compare / demo."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from .compare_features import (
    compare_feature_frames,
    load_excel_export,
    write_compare_artifacts,
)
from .paths import (
    DEFAULT_QUERY_OUT,
    DEFAULT_SAMPLE_META,
    EXCEL_DIR,
    KEY_COL,
    REPORTS_DIR,
    WORK_DIR,
    ensure_work_dirs,
    resolve_dataset,
    resolve_query,
)
from .query_inject import (
    load_sample_meta,
    read_query_text,
    sample_loss_numbers,
    unique_loss_numbers,
    write_injected_query,
    write_sample_meta,
)
from .synthetic import write_synthetic_fixtures


def _filter_by_keys(df: pd.DataFrame, losses: list[str], key_col: str = KEY_COL) -> pd.DataFrame:
    keys = {str(x).strip() for x in losses}
    mask = df[key_col].map(lambda x: str(x).strip() if pd.notna(x) else "").isin(keys)
    return df.loc[mask].copy()


def _cmd_prepare(args: argparse.Namespace) -> int:
    ensure_work_dirs()
    df_path = resolve_dataset(args.df)
    query_path = resolve_query(args.query)
    out_path = Path(args.out)
    sample_meta_path = Path(args.sample_meta)
    key_col = args.key_col

    df = pd.read_parquet(df_path)
    if key_col not in df.columns:
        raise SystemExit(f"В {df_path} нет колонки {key_col}")

    all_losses = unique_loss_numbers(df[key_col].tolist())
    n = args.n if args.n is not None else args.limit
    seed = int(args.seed)
    losses = sample_loss_numbers(all_losses, n, random_seed=seed)

    write_injected_query(
        query_path,
        losses,
        out_path,
        source_df=df_path,
        as_strings=args.as_strings,
        n_total=len(all_losses),
        random_seed=seed if n is not None else None,
    )
    write_sample_meta(
        sample_meta_path,
        losses,
        source_df=df_path,
        query_path=query_path,
        n_total=len(all_losses),
        n=n,
        random_seed=seed,
    )
    print(f"dataset        : {df_path}")
    print(f"query template : {query_path}")
    print(f"ключей всего   : {len(all_losses)}")
    print(f"в выборке      : {len(losses)}" + (f" (n={n}, seed={seed})" if n is not None else ""))
    print(f"запрос для 1С  : {out_path}")
    print(f"sample meta    : {sample_meta_path}")
    print(f"положите Excel в: {EXCEL_DIR}")
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    ensure_work_dirs()
    df_path = resolve_dataset(args.df)
    excel_path = Path(args.excel)
    if not excel_path.is_file():
        raise SystemExit(f"Excel не найден: {excel_path}")

    service = pd.read_parquet(df_path)
    excel = load_excel_export(excel_path)
    key_col = args.key_col

    sample_meta_path = Path(args.sample_meta) if args.sample_meta else DEFAULT_SAMPLE_META
    if args.use_sample_meta and sample_meta_path.is_file():
        meta = load_sample_meta(sample_meta_path)
        losses = [str(x) for x in meta.get("loss_numbers") or []]
        before = len(service)
        service = _filter_by_keys(service, losses, key_col=key_col)
        print(
            f"sample meta    : {sample_meta_path} "
            f"(service {before} → {len(service)} rows, seed={meta.get('random_seed')})"
        )

    report, mismatches = compare_feature_frames(
        service,
        excel,
        all_overlap=args.all_overlap or True,
        rtol=args.rtol,
        key_col=key_col,
    )
    if args.strict_features and report.features_missing_in_excel:
        report.ok = False

    stem = args.report_stem or "vector_compare"
    json_path, csv_path = write_compare_artifacts(
        report, mismatches, Path(args.reports_dir), stem=stem
    )

    print(f"dataset        : {df_path}")
    print(f"excel          : {excel_path}")
    print(f"keys match     : {report.n_matched_keys}")
    print(f"only service   : {report.n_only_service}")
    print(f"only excel     : {report.n_only_excel}")
    print(f"mismatch cells : {report.n_mismatch_cells}")
    print(f"features       : {len(report.features_compared)}")
    if report.features_missing_in_excel:
        print(f"нет в Excel    : {report.features_missing_in_excel}")
    print(f"report json    : {json_path}")
    print(f"mismatches csv : {csv_path}")
    print(f"RESULT         : {'OK' if report.ok else 'FAIL'}")
    return 0 if report.ok else 1


def _cmd_demo(args: argparse.Namespace) -> int:
    ensure_work_dirs()
    paths = write_synthetic_fixtures(n_rows=args.n_rows)
    print("synthetic fixtures:")
    for name, path in paths.items():
        print(f"  {name}: {path}")

    query_out = WORK_DIR / "query_for_1c_demo.txt"
    df = pd.read_parquet(paths["df"])
    all_losses = unique_loss_numbers(df[KEY_COL].tolist())
    n = args.n if args.n is not None else min(3, len(all_losses))
    seed = int(args.seed)
    losses = sample_loss_numbers(all_losses, n, random_seed=seed)
    write_injected_query(
        paths["query_stub"],
        losses,
        query_out,
        source_df=paths["df"],
        as_strings=False,
        n_total=len(all_losses),
        random_seed=seed,
    )
    write_sample_meta(
        DEFAULT_SAMPLE_META,
        losses,
        source_df=paths["df"],
        query_path=paths["query_stub"],
        n_total=len(all_losses),
        n=n,
        random_seed=seed,
    )
    injected, _ = read_query_text(query_out)
    if "&Убыток" in injected:
        print("FAIL: в demo-запросе остался &Убыток")
        return 1
    if "Убыток.Номер В (" not in injected:
        print("FAIL: не найдена подстановка Убыток.Номер В (...)")
        return 1
    # номера без кавычек: В (123, 456), не В ("123", "456")
    if 'Убыток.Номер В ("' in injected:
        print("FAIL: номера подставлены как строки, нужны int")
        return 1
    print(f"prepare demo   : {query_out} ({len(losses)}/{len(all_losses)} keys, seed={seed})")

    service_full = pd.read_parquet(paths["df"])
    service = _filter_by_keys(service_full, losses)
    excel_ok = _filter_by_keys(load_excel_export(paths["excel_ok"]), losses)
    report_ok, mism_ok = compare_feature_frames(service, excel_ok, all_overlap=True)
    write_compare_artifacts(report_ok, mism_ok, REPORTS_DIR, stem="demo_ok")
    print(
        f"compare ok     : RESULT={'OK' if report_ok.ok else 'FAIL'} "
        f"(mismatches={report_ok.n_mismatch_cells})"
    )

    report_bad, mism_bad = compare_feature_frames(
        service_full, load_excel_export(paths["excel_bad"]), all_overlap=True
    )
    write_compare_artifacts(report_bad, mism_bad, REPORTS_DIR, stem="demo_mismatch")
    print(
        f"compare bad    : RESULT={'OK' if report_bad.ok else 'FAIL'} "
        f"(mismatches={report_bad.n_mismatch_cells}, only_service={report_bad.n_only_service})"
    )

    if sample_loss_numbers(all_losses, n, random_seed=seed) != losses:
        print("FAIL: sample не детерминирован")
        return 1

    ok_cells = report_ok.n_mismatch_cells == 0 and report_ok.n_only_service == 0
    bad_detected = (not report_bad.ok) and (
        report_bad.n_mismatch_cells > 0 or report_bad.n_only_service > 0
    )
    if ok_cells and bad_detected:
        print("RESULT         : OK (synthetic pipeline works)")
        return 0
    print("RESULT         : FAIL")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m vector_checker",
        description="Сверка вектора 1С с датафреймом любой модели",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_prep = sub.add_parser("prepare", help="Подставить ключи в запрос для 1С")
    p_prep.add_argument("--df", required=False, default=None, help="parquet датасета")
    p_prep.add_argument("--query", default=None, help="Шаблон запроса 1С (.txt)")
    p_prep.add_argument("--out", default=str(DEFAULT_QUERY_OUT), help="Выходной запрос")
    p_prep.add_argument("--key-col", default=KEY_COL, help="Колонка-ключ (default: LOSS_NUMBER)")
    p_prep.add_argument("-n", "--n", type=int, default=None, help="Размер случайной выборки")
    p_prep.add_argument("--seed", type=int, default=42, help="random_seed")
    p_prep.add_argument("--limit", type=int, default=None, help="алиас для --n")
    p_prep.add_argument("--sample-meta", default=str(DEFAULT_SAMPLE_META))
    p_prep.add_argument(
        "--as-strings",
        action="store_true",
        help="Подставлять номера в кавычках (по умолчанию int без кавычек)",
    )
    p_prep.set_defaults(func=_cmd_prepare)

    p_cmp = sub.add_parser("compare", help="Сверить Excel 1С с датасетом")
    p_cmp.add_argument("--excel", required=True)
    p_cmp.add_argument("--df", default=None)
    p_cmp.add_argument("--key-col", default=KEY_COL)
    p_cmp.add_argument("--reports-dir", default=str(REPORTS_DIR))
    p_cmp.add_argument("--report-stem", default="vector_compare")
    p_cmp.add_argument("--sample-meta", default=str(DEFAULT_SAMPLE_META))
    p_cmp.add_argument(
        "--use-sample-meta",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    p_cmp.add_argument("--all-overlap", action="store_true", default=True)
    p_cmp.add_argument("--strict-features", action="store_true")
    p_cmp.add_argument("--rtol", type=float, default=0.0)
    p_cmp.set_defaults(func=_cmd_compare)

    p_demo = sub.add_parser("demo", help="Синтетический smoke")
    p_demo.add_argument("--n-rows", type=int, default=5)
    p_demo.add_argument("-n", "--n", type=int, default=None)
    p_demo.add_argument("--seed", type=int, default=42)
    p_demo.set_defaults(func=_cmd_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
