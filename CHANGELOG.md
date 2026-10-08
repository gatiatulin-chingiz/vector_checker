# Changelog

## 2026-10-08

- Ноутбук `notebooks/vector_checker.ipynb`: полный цикл prepare → Excel → compare без CLI.
- Excel проверяется только на шаге сверки, а не в конфиге.
- Зачем: можно подготовить запрос для 1С из тетрадки, пока выгрузки ещё нет.
- Проверка: `USE_SYNTHETIC=False`, указать `DF_PATH`, прогнать ячейки до prepare — должен появиться `work/query_for_1c.txt`.
