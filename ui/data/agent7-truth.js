export const AGENT7_OPERATOR_TRUTH = {
  generatedAt: '2026-03-17T02:35:00+03:00',
  productReset: {
    shellMode: 'csi_only_operator_console',
    frozenLegacy: [
      'DashboardTab',
      'FP2Tab',
      'TrainingTab',
      'legacy index shell',
      'glassmorphism dashboard layout'
    ],
    removedNoise: [
      'FP2-first hero framing',
      'generic benefits cards',
      'mixed dashboard sludge',
      'legacy training-first navigation cues'
    ]
  },
  informationArchitecture: [
    {
      id: 'live',
      label: 'Статус',
      role: 'first_screen',
      summary: 'Live‑состояние, support‑path, топология, доверие и последнее значимое событие.'
    },
    {
      id: 'signal',
      label: 'Сигнал / сенсоры',
      role: 'sensor_surface',
      summary: 'Свежесть пакетов, активность узлов, динамика движения и сигнатура топологии.'
    },
    {
      id: 'runtime',
      label: 'Запись',
      role: 'recording',
      summary: 'Guided‑запись, ручной и freeform режимы, контроль голоса/видео и статус backend.'
    },
    {
      id: 'labeling',
      label: 'Разметка',
      role: 'labeling',
      summary: 'Видео‑разметка, список пакетов, ручные правки и быстрый доступ к обзору.'
    },
    {
      id: 'validation',
      label: 'Валидация',
      role: 'dual_validation',
      summary: 'Сверка видео-лейблов и CSI-отпечатков, разбор конфликтов, согласование корпуса.'
    },
    {
      id: 'model',
      label: 'Модель',
      role: 'frozen_truth',
      summary: 'Primary runtime‑контракт, текущий best‑candidate, baseline и границы scope.'
    },
    {
      id: 'fp2',
      label: 'FP2',
      role: 'fp2',
      summary: 'FP2 мониторинг и live‑телеметрия внутри единого интерфейса.'
    },
    {
      id: 'forensics',
      label: 'Разбор',
      role: 'operator_analysis',
      summary: 'Ordered semantics, failure families, contamination notes и реестр артефактов.'
    }
  ],
  currentBest: {
    runtimePath: {
      mode: 'support_only_entry_shadow_exit_shadow',
      candidateName: 'four_node_entry_exit_shadow_core_v1',
      topologySignature: 'node01+node02+node03+node04',
      threshold: 0.996,
      scope: ['hard_empty', 'entry_shadow', 'exit_shadow'],
      supportOnly: true,
      authoritative: false,
      quietStaticCenterStatus: 'in_core',
      quietStaticDoorStatus: 'fail'
    },
    frozenBaseline: {
      baselineName: 'four_node_curated_core_rebuild_20260316_051658.entry_exit_center_core.model.json',
      threshold: 0.996,
      trainingCoreCategories: ['hard_empty', 'entry', 'exit', 'quiet_static_center'],
      excludedCategories: [
        'quiet_static_door',
        'corridor_walk',
        'vertical_transition',
        'lateral_shift',
        'quiet_static_far'
      ],
      runtimeSwitchForbidden: true
    }
  },
  canonicalResolvedStrong: {
    label: 'canonical_resolved_strong_same_run_reference',
    requiredTopologySignature: 'node01+node02+node03+node04',
    requiredThreshold: 0.996,
    mustHave: [
      'same-run paired watcher/raw bundle',
      'clean_entry_first_possible=true',
      'first_direction_assignment assigns entry before exit',
      'entry_shadow_active_seen occurs before entry_shadow_resolved',
      'entry_resolved=true before any context_invalid',
      'no unexpected_exit_before_entry before entry_resolved',
      'raw paired coverage includes the resolved entry event itself'
    ],
    policy: 'Run с пропущенным хотя бы одним условием считается failure-family evidence, а не near-miss resolved-strong.'
  },
  failureFamilies: {
    robustCore: [
      {
        label: 'collapsed_with_unresolved_overlap',
        family: 'low_response',
        rule: 'Короткий active-pulse схлопывается в review_hold и не доходит до resolved-entry.',
        evidencePath: '/Users/arsen/Desktop/wifi-densepose/temp/analysis/same_run_failed_entry_exit_forensics_20260316_143953.json'
      },
      {
        label: 'late_ramp_subthreshold_miss',
        family: 'low_response',
        rule: 'Paired overlap остаётся subthreshold, а exit-like pulse приходит слишком поздно.',
        evidencePath: '/Users/arsen/Desktop/wifi-densepose/temp/analysis/same_run_overlapping_entry_exit_forensics_20260316_150348.json'
      },
      {
        label: 'ambiguous_multi_pulse_invalid_exit_before_entry',
        family: 'high_response_semantic',
        rule: 'Сильный multi-pulse сигнал есть, но ordered semantics рушатся через exit-before-entry.',
        evidencePath: '/Users/arsen/Desktop/wifi-densepose/temp/analysis/fully_overlapping_voiced_entry_exit_forensics_20260316_153741.json'
      },
      {
        label: 'pre_assignment_multi_pulse_ambiguity',
        family: 'high_response_semantic',
        rule: 'Сильный pulse есть, но direction assignment не успевает стабилизироваться до context invalidation.',
        evidencePath: '/Users/arsen/Desktop/wifi-densepose/temp/analysis/negative_same_run_resolved_strong_gap_audit_20260316_174022.json'
      }
    ],
    conditionalSubtype: [
      {
        label: 'exit_first_prebaseline_aliasing_reproduced',
        family: 'contamination_sensitive',
        rule: 'Показывать только как conditional subtype, пока сценарий не будет повторно подтверждён после quiet pre-baseline с исправленной хореографией.',
        evidencePath: '/Users/arsen/Desktop/wifi-densepose/temp/analysis/prebaseline_exit_first_repro_forensics_20260316_160419.json'
      }
    ]
  },
  contaminationNote: {
    summary: 'Ранние exit-first run’ы с sample_index=0 не считаются устойчивым standalone-доказательством стабильного subtype.',
    robustTruth: [
      'quiet-only controls не воспроизводят aliasing',
      'control-like run может сохранять clean entry-first assignment',
      'low-response failures остаются валидными',
      'late high-response semantic failure остаётся валидным',
      'canonical resolved-strong reference всё ещё отсутствует'
    ],
    nextGate: 'Считать future exit-first prebaseline evidence устойчивым только если первый сильный pulse возникает после явно тихого outside-интервала.'
  },
  artifactRegistry: [
    {
      group: 'synthesis',
      items: [
        '/Users/arsen/Desktop/wifi-densepose/temp/analysis/four_node_live_entry_exit_line_synthesis_20260316_174553.json',
        '/Users/arsen/Desktop/wifi-densepose/temp/analysis/four_node_live_entry_exit_timing_bias_corrective_synthesis_20260316_192907.json'
      ]
    },
    {
      group: 'docs',
      items: [
        '/Users/arsen/Desktop/wifi-densepose/docs/FOUR_NODE_LIVE_ENTRY_EXIT_LINE_SYNTHESIS_2026-03-16_174553.md',
        '/Users/arsen/Desktop/wifi-densepose/docs/FOUR_NODE_LIVE_ENTRY_EXIT_TIMING_BIAS_CORRECTIVE_SYNTHESIS_2026-03-16_192907.md',
        '/Users/arsen/Desktop/wifi-densepose/docs/AGENT7_CSI_OPERATOR_UI_DIRECTION_2026-03-17.md',
        '/Users/arsen/Desktop/wifi-densepose/docs/AGENT7_CSI_OPERATOR_UI_FREEZE_PLAN_2026-03-17.md'
      ]
    },
    {
      group: 'paired_failure_evidence',
      items: [
        '/Users/arsen/Desktop/wifi-densepose/temp/analysis/same_run_failed_entry_exit_forensics_20260316_143953.json',
        '/Users/arsen/Desktop/wifi-densepose/temp/analysis/same_run_overlapping_entry_exit_forensics_20260316_150348.json',
        '/Users/arsen/Desktop/wifi-densepose/temp/analysis/fully_overlapping_voiced_entry_exit_forensics_20260316_153741.json',
        '/Users/arsen/Desktop/wifi-densepose/temp/analysis/prebaseline_exit_first_repro_forensics_20260316_160419.json',
        '/Users/arsen/Desktop/wifi-densepose/temp/analysis/negative_same_run_resolved_strong_gap_audit_20260316_174022.json'
      ]
    }
  ],
  operatorWorkflow: [
    'Сначала читай Live-консоль, чтобы отделить motion-only verdict от support evidence.',
    'Используй Сигнал / сенсоры, чтобы подтвердить topology, freshness и пригодность packet-plane.',
    'Используй Модель, чтобы проверить scope, exclusions и threshold до интерпретации support-pulse.',
    'Открывай Форензику, когда semantics ломаются или ambiguity требует объяснения через артефакты.',
    'Используй Runtime / corpus, чтобы проверить здоровье сервисов и найти точный artifact-bundle для продолжения работы.'
  ]
};
