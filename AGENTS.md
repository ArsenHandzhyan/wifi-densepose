# AgentHub Enforcement

Для агентных задач в этом репозитории обязательны следующие правила:

1. Любая новая агентная задача стартует только через `/Users/arsen/Desktop/wifi-densepose/scripts/agent_hub_task.sh start`.
2. Любое обновление статуса и любое завершение задачи выполняется только через `/Users/arsen/Desktop/wifi-densepose/scripts/agent_hub_task.sh update|complete`.
3. Wrapper должен по возможности автоматически привязывать внешний executor PID к AgentHub record; если задача идёт из Codex/Claude/OpenCode/Qoder, PID этого исполнителя должен попадать в ledger как `executor_pid`.
4. Перед новым `start` wrapper автоматически запускает strict preflight:
   `/Users/arsen/Desktop/wifi-densepose/scripts/agent_hub_strict_preflight.py`
5. Strict preflight обязан блокировать новый `start`, если:
   - текущий git checkout находится в `detached HEAD`,
   - работа идёт из `main` / `master`,
   - уже существует незавершённая AgentHub-задача с тем же `agent`,
   - audit находит незарегистрированные `docs/AGENTCLOUD_*_REPORT.md`.
6. Быстрый ручной preflight:
   `/Users/arsen/Desktop/wifi-densepose/scripts/agent_hub_preflight.sh`
7. Wrapper обязан автоматически писать текущую git-ветку в AgentHub record, если она не была передана явно.
8. Агентные задачи должны запускаться из отдельной рабочей ветки/worktree, а не из `main`.
9. `complete` без уже существующего report-файла считается нарушением процесса и должен быть запрещён wrapper'ом.
10. Рапорт в `docs/AGENTCLOUD_*_REPORT.md` без записи в AgentHub считается нарушением процесса.

## Recording Validity Rule

1. Видео-backed запись не считается валидно стартовавшей только по факту `recording=true` или росту `teacher.mp4`.
2. После каждого `record/start` обязателен post-start CSI guard в первые секунды сессии.
3. Минимальный критерий живого старта:
   - есть CSI-пакеты,
   - активны минимум `3` core-ноды,
   - `chunk_pps` не нулевой и проходит guard threshold.
4. Если post-start guard не пройден, сессия должна быть немедленно остановлена с причиной `csi_dead_on_start`.
5. Сессия с `csi_dead_on_start` не считается пригодной для обучения, разметки или coordinate-eval даже если teacher video записался полностью.

## Canonical Recording Reuse Rule

1. Любой агент, который собирается запускать запись, обязан сначала опираться на канонический recording-процесс из:
   `/Users/arsen/Desktop/wifi-densepose/docs/RUNBOT_CSI_CANONICAL_RECORDING_PROCESS_2026-03-20.md`
2. Запрещено придумывать новый recording-flow, новый preflight, новую voice-схему или отдельную "капчу" запуска, если текущие canonical UI/API и уже сохранённые правила покрывают задачу.
3. Канонический entrypoint для operator/live записи:
   - `CSI Operator UI`
   - `/api/v1/csi/record/start`
   - `/api/v1/csi/record/status`
   - `/api/v1/csi/record/stop`
4. Перед любой записью агент обязан использовать уже существующие safeguards, а не обходить их:
   - preflight/health check,
   - post-start CSI guard,
   - auto-stop с причиной `csi_dead_on_start`,
   - teacher-video coverage contract.
5. Если агент запускает запись с озвучкой, по умолчанию он обязан использовать зафиксированную "крутую" canonical voice:
   - `Lily - Velvety Actress`
   - `voice_id = pFZP5JQG7iQjIQuC4Bku`
   Другой голос допустим только если:
   - пользователь явно попросил другой голос,
   - или более новый canonical document явно заменил этот default.
6. Агент обязан переиспользовать уже сохранённые наработки по записи и валидации, включая:
   - `startup_signal_guard`,
   - UI-обработку `csi_dead_on_start`,
   - holdout/truth rubric,
   - promotion/operator checklist,
   - актуальный shadow/runtime contract.
7. Если агент не уверен, какой recording-path считать главным, он должен выбрать existing canonical path, а не собирать новый параллельный стек.
