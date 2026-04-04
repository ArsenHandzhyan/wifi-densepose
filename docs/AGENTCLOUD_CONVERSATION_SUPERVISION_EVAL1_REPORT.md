# AGENTCLOUD_CONVERSATION_SUPERVISION_EVAL1_REPORT

## Verdict

- Выполнен честный offline eval текущих telemetry/model слоёв против user-confirmed truth bundle.

## Coverage

- Интервалов в truth bundle: `15`
- Интервалов с собранными model rows: `14`

## Occupancy
- `runtime_binary`: rows=`466`, intervals=`14`, acc=`0.7554`, bal_acc=`0.54`, macro_f1=`0.5318`
- `v8_binary`: rows=`46`, intervals=`7`, acc=`0.0`, bal_acc=`None`, macro_f1=`0.0`

## Zone
- `runtime_zone`: rows=`329`, intervals=`10`, acc=`0.386`, bal_acc=`0.3699`, macro_f1=`0.3249`
- `candidate_zone`: rows=`360`, intervals=`6`, acc=`0.7306`, bal_acc=`0.7306`, macro_f1=`0.7231`
- `fewshot_zone`: rows=`240`, intervals=`4`, acc=`0.5292`, bal_acc=`0.5292`, macro_f1=`0.5231`
- `prototype_zone`: rows=`240`, intervals=`4`, acc=`0.5`, bal_acc=`0.5`, macro_f1=`0.3333`
- `temporal_zone`: rows=`240`, intervals=`4`, acc=`0.5`, bal_acc=`0.5`, macro_f1=`0.3333`

## Motion