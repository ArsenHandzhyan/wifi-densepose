export const MANUAL_CAPTURE_PRESETS = [
  {
    id: 'custom',
    label: 'Свой вариант',
    labelValue: '',
    motionType: '',
    personCount: 1,
    notesPrefix: '',
    variants: [
      {
        id: 'custom',
        label: 'Без шаблона',
        notes: ''
      }
    ]
  },
  {
    id: 'quiet_static',
    label: 'Тихая статика',
    labelValue: 'quiet_static',
    motionType: 'static',
    personCount: 1,
    notesPrefix: 'single_person, quiet_static',
    variants: [
      { id: 'center', label: 'Центр гаража', notes: 'zone=CENTER, still' },
      { id: 'door', label: 'У двери', notes: 'zone=DOOR, still' },
      { id: 'offset', label: 'Смещение от центра', notes: 'zone=OFFSET, still' }
    ]
  },
  {
    id: 'normal_breath',
    label: 'Обычное дыхание',
    labelValue: 'normal_breath',
    motionType: 'breathing',
    personCount: 1,
    notesPrefix: 'single_person, normal_breath',
    variants: [
      { id: 'center', label: 'Центр гаража', notes: 'zone=CENTER, breathing=normal' },
      { id: 'offset', label: 'Смещение от центра', notes: 'zone=OFFSET, breathing=normal' }
    ]
  },
  {
    id: 'deep_breath',
    label: 'Глубокое дыхание',
    labelValue: 'deep_breath',
    motionType: 'breathing',
    personCount: 1,
    notesPrefix: 'single_person, deep_breath',
    variants: [
      { id: 'center', label: 'Центр гаража', notes: 'zone=CENTER, breathing=deep' },
      { id: 'offset', label: 'Смещение от центра', notes: 'zone=OFFSET, breathing=deep' }
    ]
  },
  {
    id: 'empty_room',
    label: 'Пустое помещение',
    labelValue: 'empty_room',
    motionType: 'empty',
    personCount: 0,
    notesPrefix: 'no_person',
    variants: [
      { id: 'center_clear', label: 'Пустой центр', notes: 'zone=CENTER, empty_room' },
      { id: 'door_clear', label: 'Пустой дверной проход', notes: 'zone=DOOR, empty_room' },
      { id: 'full_clear', label: 'Пустой гараж', notes: 'space=garage, empty_room' }
    ]
  },
  {
    id: 'walking',
    label: 'Ходьба',
    labelValue: 'walking',
    motionType: 'walking',
    personCount: 1,
    notesPrefix: 'single_person, walking',
    variants: [
      { id: 'center_pass', label: 'Проход по центру', notes: 'path=CENTER, walk=continuous' },
      { id: 'short_loop', label: 'Короткая проходка', notes: 'path=SHORT_LOOP, walk=continuous' },
      { id: 'door_lane', label: 'Проход у двери', notes: 'path=DOOR_LANE, walk=continuous' }
    ]
  },
  {
    id: 'in_place_motion',
    label: 'Движение на месте',
    labelValue: 'in_place_motion',
    motionType: 'in_place_motion',
    personCount: 1,
    notesPrefix: 'single_person, in_place_motion',
    variants: [
      { id: 'bend_forward', label: 'Наклоны вперёд', notes: 'step=bend_forward, zone=CENTER' },
      { id: 'squat_cycle', label: 'Приседания', notes: 'step=squat_cycle, zone=CENTER' },
      { id: 'turn_in_place', label: 'Повороты на месте', notes: 'step=turn_in_place, zone=CENTER' },
      { id: 'reach_left_right', label: 'Дотягивания влево/вправо', notes: 'step=reach_left_right, zone=CENTER' },
      { id: 'arm_wave_cycle', label: 'Подъём рук', notes: 'step=arm_wave_cycle, zone=CENTER' },
      { id: 'stand_weight_shift', label: 'Перенос веса', notes: 'step=stand_weight_shift, zone=CENTER' },
      { id: 'sit_fidget', label: 'Сидячее ёрзание', notes: 'step=sit_fidget, zone=CENTER' }
    ]
  },
  {
    id: 'transition',
    label: 'Переходное движение',
    labelValue: 'transition',
    motionType: 'transition',
    personCount: 1,
    notesPrefix: 'single_person, transition_focus',
    variants: [
      { id: 'walk_to_stop', label: 'Ходьба к резкой остановке', notes: 'step=walk_to_stop, transition_focus' },
      { id: 'stop_to_walk', label: 'Стойка в ходьбу', notes: 'step=stop_to_walk, transition_focus' },
      { id: 'enter_and_settle', label: 'Вход и фиксация', notes: 'step=enter_and_settle, transition_focus' },
      { id: 'stand_then_exit', label: 'Стойка и выход', notes: 'step=stand_then_exit, transition_focus' },
      { id: 'sit_down_onset', label: 'Посадка', notes: 'step=sit_down_onset, transition_focus' },
      { id: 'stand_up_onset', label: 'Подъём', notes: 'step=stand_up_onset, transition_focus' },
      { id: 'turn_and_stop', label: 'Разворот и стоп', notes: 'step=turn_and_stop, transition_focus' },
      { id: 'enter_quick_exit', label: 'Быстрый вход-выход', notes: 'step=enter_quick_exit, transition_focus' }
    ]
  },
  {
    id: 'entry_exit',
    label: 'Вход / выход',
    labelValue: 'entry_exit',
    motionType: 'entry_exit',
    personCount: 1,
    notesPrefix: 'single_person, entry_exit',
    variants: [
      { id: 'entry_hold', label: 'Вход и фиксация', notes: 'entry_then_hold, zone=DOOR' },
      { id: 'exit_after_hold', label: 'Стойка и выход', notes: 'hold_then_exit, zone=DOOR' },
      { id: 'quick_entry_exit', label: 'Быстрый вход-выход', notes: 'quick_entry_exit, zone=DOOR' }
    ]
  },
  {
    id: 'mixed',
    label: 'Смешанная активность',
    labelValue: 'mixed',
    motionType: 'mixed',
    personCount: 1,
    notesPrefix: 'single_person, mixed_activity',
    variants: [
      { id: 'mixed_center', label: 'Смешанная активность в центре', notes: 'zone=CENTER, mixed_activity' },
      { id: 'mixed_door', label: 'Смешанная активность у двери', notes: 'zone=DOOR, mixed_activity' }
    ]
  }
];

export function getManualCapturePreset(presetId) {
  return MANUAL_CAPTURE_PRESETS.find((item) => item.id === presetId) || MANUAL_CAPTURE_PRESETS[0];
}

export function getManualCapturePresetVariant(presetId, variantId) {
  const preset = getManualCapturePreset(presetId);
  if (!preset) {
    return null;
  }
  return preset.variants.find((item) => item.id === variantId) || preset.variants[0] || null;
}

export function buildManualCaptureLabel(preset, variant) {
  return variant?.labelValue || preset?.labelValue || '';
}

export function buildManualCaptureNotes(preset, variant) {
  return [preset?.notesPrefix, variant?.notes].filter(Boolean).join(', ');
}
