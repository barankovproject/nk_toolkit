# nk_toolkit

Автоматизация Civil 3D для нагорных канав (НК-*), корпуса дороги/корридора и
габионных конструкций. Не про трубы/колодцы — за них отвечает соседний
репозиторий `tube_toolkit`.

Два префикса, которые встречаются по всему проекту:
- **НК-\*** (НК-1А-5, НК-2D-1, ...) — нагорные канавы → этот репозиторий.
- **В-\*** (В-4А-3, В-5А-2, ...) — водопропуски → соседний репозиторий
  `tube_toolkit`, не здесь.

Зависит от `civil3d_common` (submodule в `common/`) — оттуда обёртки Civil3D
API, конфиг линтера, хелперы inject/run, а также общие процессные доки
(`common/docs/process/01_api_exploration.md`, `02_development.md`,
`07_drawing_scripts.md`).

## Структура

```
nk_toolkit/
├── common/                    ← submodule → civil3d_common
├── build_canal_model/         ← основной строитель канав (гейбоны/лотки/рёбра)
├── build_corridors/ build_corridor_surfaces/ build_corridor_volumes/
├── build_gsi_grid/
├── build_widening_assemblies/
├── ditch/                     ← продольные/поперечные канавы у дороги
├── anchor/                    ← анкерная сетка на откосах
├── draw_*/                    ← 2D/3D аннотации (план, габионы, экскавация)
├── report_*/                  ← отчёты по объёмам
├── help_*/                    ← утилиты
├── debug/                     ← одноразовые дебаг-дампы
├── docs/                      ← project-specific доки (context.md, testing, roadmap)
├── projects/arhyz_s2/references/  ← справочники конкретно по объекту Архыз
└── paths.py                   ← свой реестр путей (CANALS_DIR, TYPES_FILE, ...)
```

## Происхождение

Выделено из `arhyz_auto` (был единый репозиторий) вместе с `civil3d_common`
(общий слой) и `tube_toolkit` (трубы/колодцы). Данные конкретно по объекту
Архыз (`config/canals/*.json` и т.д.) — в отдельном репозитории
`arhyz_s2_data`, подключаемом через `project.env`/`DATA_ROOT`.
