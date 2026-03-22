export const GUIDED_CAPTURE_PACKS = [
  {
    id: 'f1_in_place_motion',
    code: 'F1',
    name: 'F1 In-Place Motion',
    shortLabel: 'in_place_motion focus',
    description: '7 клипов в центре гаража без empty baseline. Фокус на in-place motion и контролируемых движениях на месте.',
    motionType: 'in_place_motion',
    personCount: 1,
    withVideo: false,
    voiceEnabledByDefault: true,
    preflightCheckVideo: false,
    countdownSec: 4,
    pauseBetweenStepsSec: 3,
    labelPrefix: 'train',
    sessionSlug: 'v2gap_f1',
    notesPrefix: 'Session F1 v2 taxonomy gap fill, no empty-garage steps',
    steps: [
      {
        id: 'bend_forward',
        label: 'Наклоны вперёд',
        durationSec: 30,
        instruction: 'Стой в центре. Плавно наклоняйся вперёд и возвращайся. Повторяй. Ноги на месте.',
        notes: 'step=bend_forward, zone=CENTER'
      },
      {
        id: 'squat_cycle',
        label: 'Приседания',
        durationSec: 30,
        instruction: 'Стой в центре. Медленно приседай, держи 3 секунды, встань. Повторяй. Ноги на месте.',
        notes: 'step=squat_cycle, zone=CENTER'
      },
      {
        id: 'turn_in_place',
        label: 'Повороты на месте',
        durationSec: 30,
        instruction: 'Стой в центре. Повернись на 90 градусов влево, вернись. Повернись вправо, вернись. Повторяй.',
        notes: 'step=turn_in_place, zone=CENTER'
      },
      {
        id: 'reach_left_right',
        label: 'Дотягивания влево/вправо',
        durationSec: 30,
        instruction: 'Стой в центре. Вытяни руку максимально влево, потом вправо. Повторяй плавно.',
        notes: 'step=reach_left_right, zone=CENTER'
      },
      {
        id: 'arm_wave_cycle',
        label: 'Подъём рук',
        durationSec: 30,
        instruction: 'Стой в центре. Медленно подними обе руки вверх, опусти. Повторяй.',
        notes: 'step=arm_wave_cycle, zone=CENTER'
      },
      {
        id: 'stand_weight_shift',
        label: 'Перенос веса',
        durationSec: 30,
        instruction: 'Стой в центре. Плавно переноси вес с ноги на ногу. Не сходи с места.',
        notes: 'step=stand_weight_shift, zone=CENTER'
      },
      {
        id: 'sit_fidget',
        label: 'Сидячее ёрзание',
        durationSec: 30,
        instruction: 'Сядь на стул в центре. Ёрзай, двигай корпусом и руками, слегка поворачивайся. Не вставай.',
        notes: 'step=sit_fidget, zone=CENTER'
      }
    ]
  },
  {
    id: 'f2_transition_focus',
    code: 'F2',
    name: 'F2 Transition Focus',
    shortLabel: 'transition focus',
    description: '8 transition-клипов без empty-garage шагов. Фокус на onset/offset, enter/exit и резких сменах состояния.',
    motionType: 'transition',
    personCount: 1,
    withVideo: false,
    voiceEnabledByDefault: true,
    preflightCheckVideo: false,
    countdownSec: 4,
    pauseBetweenStepsSec: 5,
    labelPrefix: 'train',
    sessionSlug: 'v2gap_f2',
    notesPrefix: 'Session F2 v2 taxonomy gap fill, no empty-garage steps',
    steps: [
      {
        id: 'walk_to_stop',
        label: 'Ходьба к резкой остановке',
        durationSec: 30,
        instruction: 'Иди по центру гаража обычным шагом. По команде резко остановись и замри.',
        notes: 'step=walk_to_stop, transition_focus'
      },
      {
        id: 'stop_to_walk',
        label: 'Стойка в ходьбу',
        durationSec: 30,
        instruction: 'Стой в центре неподвижно 5 секунд. Потом начни идти обычным шагом.',
        notes: 'step=stop_to_walk, transition_focus'
      },
      {
        id: 'enter_and_settle',
        label: 'Вход и фиксация',
        durationSec: 30,
        instruction: 'Выйди за дверь. После старта войди, дойди до центра, остановись и замри.',
        notes: 'step=enter_and_settle, transition_focus'
      },
      {
        id: 'stand_then_exit',
        label: 'Стойка и выход',
        durationSec: 30,
        instruction: 'Стой в центре неподвижно 5 секунд. Потом иди к двери и выйди из гаража.',
        notes: 'step=stand_then_exit, transition_focus'
      },
      {
        id: 'sit_down_onset',
        label: 'Посадка',
        durationSec: 30,
        instruction: 'Стой рядом со стулом. После старта сядь на стул и замри сидя.',
        notes: 'step=sit_down_onset, transition_focus'
      },
      {
        id: 'stand_up_onset',
        label: 'Подъём',
        durationSec: 30,
        instruction: 'Сиди на стуле. После старта встань и замри стоя.',
        notes: 'step=stand_up_onset, transition_focus'
      },
      {
        id: 'turn_and_stop',
        label: 'Разворот и стоп',
        durationSec: 30,
        instruction: 'Иди от двери вглубь. На середине развернись на 180 градусов и остановись.',
        notes: 'step=turn_and_stop, transition_focus'
      },
      {
        id: 'enter_quick_exit',
        label: 'Быстрый вход-выход',
        durationSec: 30,
        instruction: 'Выйди за дверь. После старта войди, дойди до центра, сразу развернись и выйди обратно.',
        notes: 'step=enter_quick_exit, transition_focus'
      }
    ]
  },
  {
    id: 'f3_door_center_zone_diversity',
    code: 'F3',
    name: 'F3 Door/Center Zone Diversity',
    shortLabel: 'door / center focus',
    description: '10 клипов у двери и в центре без deep-зоны и без empty quick-start. Фокус на in-place near DOOR/CENTER и переходах по узкому коридору дверь↔центр.',
    motionType: 'zone_diversity',
    personCount: 1,
    withVideo: false,
    voiceEnabledByDefault: true,
    preflightCheckVideo: false,
    countdownSec: 4,
    pauseBetweenStepsSec: 5,
    labelPrefix: 'train',
    sessionSlug: 'v2gap_f3',
    notesPrefix: 'Session F3 v2 taxonomy gap fill, door-center only, no deep-zone dependency',
    steps: [
      {
        id: 'bend_forward_door',
        label: 'Наклоны у двери',
        durationSec: 30,
        instruction: 'Перейди к двери. Стой на месте и плавно наклоняйся вперёд с возвратом в стойку.',
        notes: 'step=bend_forward, zone=DOOR'
      },
      {
        id: 'squat_cycle_door',
        label: 'Приседания у двери',
        durationSec: 30,
        instruction: 'Останься у двери. Делай спокойные приседания с короткой фиксацией внизу.',
        notes: 'step=squat_cycle, zone=DOOR'
      },
      {
        id: 'turn_in_place_door',
        label: 'Повороты у двери',
        durationSec: 30,
        instruction: 'Останься у двери. Поворачивайся корпусом влево и вправо, не сходя с места.',
        notes: 'step=turn_in_place, zone=DOOR'
      },
      {
        id: 'reach_left_right_center',
        label: 'Дотягивания в центре',
        durationSec: 30,
        instruction: 'Перейди в центр. Тянись руками влево и вправо, сохраняя опорную стойку.',
        notes: 'step=reach_left_right, zone=CENTER'
      },
      {
        id: 'head_nod_turn_door',
        label: 'Кивки и повороты у двери',
        durationSec: 30,
        instruction: 'Вернись к двери. Чередуй кивки головой и лёгкие повороты корпуса.',
        notes: 'step=head_nod_turn, zone=DOOR'
      },
      {
        id: 'walk_door_to_center_stop',
        label: 'Дверь → центр и стоп',
        durationSec: 30,
        instruction: 'Стартуй у двери. Иди по узкому проходу к центру, затем резко остановись и замри.',
        notes: 'step=walk_door_to_center_stop, transition_path=DOOR_CENTER'
      },
      {
        id: 'walk_center_to_door_stop',
        label: 'Центр → дверь и стоп',
        durationSec: 30,
        instruction: 'Стартуй из центра. Иди к двери и остановись у двери без лишних шагов.',
        notes: 'step=walk_center_to_door_stop, transition_path=CENTER_DOOR'
      },
      {
        id: 'enter_outside_to_center',
        label: 'Вход снаружи → центр',
        durationSec: 30,
        instruction: 'Выйди за дверь. После старта войди, дойди до центра и зафиксируйся в центре.',
        notes: 'step=enter_outside_to_center, transition_path=OUTSIDE_CENTER'
      },
      {
        id: 'stand_center_then_exit',
        label: 'Центр → выход',
        durationSec: 30,
        instruction: 'Стой в центре. После команды иди к двери и выйди наружу без deep-зоны.',
        notes: 'step=stand_center_then_exit, transition_path=CENTER_OUTSIDE'
      },
      {
        id: 'sit_down_onset_door',
        label: 'Посадка у двери',
        durationSec: 30,
        instruction: 'Останься у двери рядом со стулом. После старта сядь и зафиксируйся сидя.',
        notes: 'step=sit_down_onset, zone=DOOR'
      }
    ]
  },
  {
    id: 'sp1_static_sequence_pack',
    code: 'SP1',
    name: 'SP1 Static Sequence Pack',
    shortLabel: 'static holds for seq model',
    description: '8 one-action static hold clips for sequence model training. Sustained 60–90 sec holds in diverse zones/poses. Leakage-safe clip-level grouping.',
    motionType: 'static',
    personCount: 1,
    withVideo: true,
    voiceEnabledByDefault: true,
    preflightCheckVideo: true,
    countdownSec: 4,
    pauseBetweenStepsSec: 10,
    labelPrefix: 'static_pack_seq1',
    sessionSlug: 'sp1_static_seq',
    notesPrefix: 'SP1 targeted static capture for sequence model branch',
    steps: [
      {
        id: 'center_stand_hold_90',
        label: 'Стоять в центре 90с',
        durationSec: 90,
        instruction: 'Встань в центр гаража. Смотри прямо, стой спокойно, не ходи и не меняй позу. Удерживай позицию девяносто секунд.',
        notes: 'step=center_stand_hold_90, zone=CENTER, pose=stand'
      },
      {
        id: 'center_chair_sit_hold_90',
        label: 'Сидеть на стуле в центре 90с',
        durationSec: 90,
        instruction: 'Сядь на стул в центре гаража. Руки на коленях, не вставай и не ёрзай. Удерживай позицию девяносто секунд.',
        notes: 'step=center_chair_sit_hold_90, zone=CENTER, pose=sit_chair'
      },
      {
        id: 'door_stand_facing_inward_90',
        label: 'Стоять у двери лицом внутрь 90с',
        durationSec: 90,
        instruction: 'Подойди к двери гаража. Встань у двери лицом внутрь. Стой спокойно и неподвижно девяносто секунд.',
        notes: 'step=door_stand_facing_inward_90, zone=DOOR, pose=stand_facing_inward'
      },
      {
        id: 'deep_wall_stand_90',
        label: 'Стоять у дальней стены 90с',
        durationSec: 90,
        instruction: 'Подойди к дальней стене гаража, в глубокую зону. Встань лицом к двери и стой неподвижно девяносто секунд.',
        notes: 'step=deep_wall_stand_90, zone=DEEP, pose=stand'
      },
      {
        id: 'left_wall_stand_90',
        label: 'Стоять у левой стены 90с',
        durationSec: 90,
        instruction: 'Если смотреть из центра в сторону двери, узкий проход к двери находится слева. Встань у левой стены, рядом с этим проходом. Стой неподвижно девяносто секунд.',
        notes: 'step=left_wall_stand_90, zone=LEFT_WALL, pose=stand'
      },
      {
        id: 'center_crouch_hold_60',
        label: 'Присед в центре 60с',
        durationSec: 60,
        instruction: 'Встань в центр гаража. Затем присядь и удерживай эту низкую позу шестьдесят секунд. Не перемещайся по комнате.',
        notes: 'step=center_crouch_hold_60, zone=CENTER, pose=crouch'
      },
      {
        id: 'exit_threshold_hold_90',
        label: 'Стоять на пороге 90с',
        durationSec: 90,
        instruction: 'Стартовая точка — центр гаража. Пройди к выходу через левый узкий проход, если смотреть из центра в сторону двери. Остановись на пороге и стой неподвижно девяносто секунд.',
        notes: 'step=exit_threshold_hold_90, zone=EXIT, pose=stand_threshold'
      },
      {
        id: 'center_phone_hold_60',
        label: 'Стоять с телефоном в центре 60с',
        durationSec: 60,
        instruction: 'Встань в центр гаража. Держи телефон перед собой, как будто читаешь. Стой неподвижно шестьдесят секунд.',
        notes: 'step=center_phone_hold_60, zone=CENTER, pose=phone_hold'
      }
    ]
  }
];

export function getGuidedCapturePack(packId) {
  return GUIDED_CAPTURE_PACKS.find((pack) => pack.id === packId) || null;
}

export function getGuidedCapturePackSummary(pack) {
  if (!pack) {
    return {
      clipCount: 0,
      activeSeconds: 0,
      transitionSeconds: 0,
      totalSeconds: 0
    };
  }

  const clipCount = pack.steps.length;
  const activeSeconds = pack.steps.reduce((sum, step) => sum + Number(step.durationSec || 0), 0);
  const transitionSeconds = Math.max(0, clipCount - 1) * Number(pack.pauseBetweenStepsSec || 0);

  return {
    clipCount,
    activeSeconds,
    transitionSeconds,
    totalSeconds: activeSeconds + transitionSeconds
  };
}
