# vector_checker

Универсальная сверка **вектора признаков из 1С** с **датафреймом любой модели** (1:1 по ключу, обычно `LOSS_NUMBER`).

Не зависит от Querulus / OutBoxML.

## Установка

```bash
cd vector_checker
pip install -e .
```

## Быстрый smoke

```bash
python -m vector_checker demo
```

## Боевой цикл

```bash
# 1) подставить ключи в запрос 1С
python -m vector_checker prepare \
  --df path/to/dataset.parquet \
  --query queries/Сутяжность.txt \
  -n 50 --seed 42

# 2) выполнить work/query_for_1c.txt в 1С → Excel в work/excel/

# 3) сверка
python -m vector_checker compare \
  --df path/to/dataset.parquet \
  --excel work/excel/export.xlsx
```

Env (опционально): `VECTOR_CHECKER_DF_PATH`, `VECTOR_CHECKER_QUERY_PATH`.

## Ноутбук

`notebooks/vector_checker.ipynb` — в конфиге задай `QUERY_PATH` и `DF_PATH`.

## Структура

- `queries/` — шаблоны запросов 1С (лежит `Сутяжность.txt`)
- `vector_checker/` — пакет
- `work/` — выходной запрос, Excel, отчёты
