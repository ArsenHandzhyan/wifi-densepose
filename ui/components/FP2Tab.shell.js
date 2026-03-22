export const FP2_TAB_SHELL = `
  <div class="fp2-page-header">
    <div class="fp2-page-header-left">
      <h2 data-i18n="fp2.page.title">Карта CSI</h2>
      <p class="help-text" data-i18n="fp2.page.help">Карта движения, зоны, события и диагностика CSI.</p>
    </div>
    <div class="fp2-page-header-right">
      <button id="fp2Refresh" class="btn btn--secondary btn--sm" data-i18n="common.refresh">Обновить</button>
      <span id="fp2UpdatedAt" class="fp2-last-update">-</span>
    </div>
  </div>

  <div id="fp2FallAlert" class="fp2-fall-alert" style="display:none;">
    <div class="fp2-fall-alert-icon">&#x26A0;</div>
    <div class="fp2-fall-alert-body">
      <strong data-i18n="fp2.fall_detected">Обнаружено падение</strong>
      <span id="fp2FallAlertText" data-i18n="fp2.fall_default">Сенсор зафиксировал возможное падение</span>
    </div>
    <span id="fp2FallAlertTime" class="fp2-fall-alert-time">-</span>
  </div>

  <div class="fp2-hero-bar">
    <div class="fp2-hero-metric fp2-hero-metric--presence">
      <span class="fp2-hero-label" data-i18n="fp2.hero.presence">Присутствие</span>
      <span id="fp2PresenceValue" class="presence-pill absent" data-i18n="common.absent">НЕТ</span>
      <span id="fp2PresenceDuration" class="fp2-hero-sub">-</span>
    </div>
    <div class="fp2-hero-metric">
      <span id="fp2TargetsLabel" class="fp2-hero-label" data-i18n="fp2.hero.targets">Цели</span>
      <span id="fp2PersonsCount" class="fp2-hero-value">0</span>
      <span id="fp2TargetsHint" class="fp2-hero-sub">-</span>
      <span id="fp2CoordinateStream" class="chip chip--warn fp2-hero-sub" data-i18n="common.waiting">ОЖИДАНИЕ</span>
    </div>
    <div class="fp2-hero-metric">
      <span class="fp2-hero-label" data-i18n="fp2.hero.movement">Движение</span>
      <strong id="fp2MovementEvent" class="fp2-hero-value fp2-hero-value--sm">-</strong>
    </div>
    <div class="fp2-hero-metric">
      <span class="fp2-hero-label" data-i18n="fp2.hero.light">Свет</span>
      <strong id="fp2LightLevel" class="fp2-hero-value">-</strong>
    </div>
    <div class="fp2-hero-metric fp2-hero-metric--rssi">
      <span class="fp2-hero-label" data-i18n="fp2.hero.signal">Сигнал</span>
      <div class="fp2-rssi-gauge">
        <canvas id="fp2RssiGauge" width="80" height="44"></canvas>
        <strong id="fp2RssiValue" class="fp2-rssi-text">-</strong>
      </div>
    </div>
    <div class="fp2-hero-metric">
      <span class="fp2-hero-label" data-i18n="fp2.hero.zones">Зоны</span>
      <strong id="fp2ZonesCount" class="fp2-hero-value">0</strong>
      <strong id="fp2CurrentZone" class="fp2-hero-sub">-</strong>
    </div>
  </div>

  <div class="fp2-card fp2-card--home">
    <div class="fp2-card-header-row">
      <h3 data-i18n="fp2.home.title">Обзор Aqara Home</h3>
      <div class="fp2-home-range">
        <button id="fp2HomeRangeDay" class="btn btn--secondary btn--sm" data-i18n="fp2.home.range.day">День</button>
        <button id="fp2HomeRangeWeek" class="btn btn--secondary btn--sm" data-i18n="fp2.home.range.week">Неделя</button>
        <button id="fp2HomeClearHistory" class="btn btn--secondary btn--sm" data-i18n="fp2.home.clear_history">Очистить историю</button>
      </div>
    </div>
    <div class="fp2-home-grid">
      <article class="fp2-home-card">
        <span class="fp2-home-card-label" data-i18n="fp2.home.current_people">Текущее количество</span>
        <strong id="fp2HomeCurrentPeople" class="fp2-home-card-value">-</strong>
      </article>
      <article class="fp2-home-card">
        <span class="fp2-home-card-label" data-i18n="fp2.home.presence_duration">Присутствие длится</span>
        <strong id="fp2HomePresenceDuration" class="fp2-home-card-value">-</strong>
      </article>
      <article class="fp2-home-card">
        <span id="fp2HomeVisitorsLabel" class="fp2-home-card-label" data-i18n="fp2.home.visitors_today">Посетителей сегодня</span>
        <strong id="fp2HomeVisitorsToday" class="fp2-home-card-value">-</strong>
      </article>
      <article class="fp2-home-card">
        <span id="fp2HomeWalkingLabel" class="fp2-home-card-label" data-i18n="fp2.home.walking_today">Пройдено сегодня</span>
        <strong id="fp2HomeWalkingToday" class="fp2-home-card-value">-</strong>
      </article>
      <article class="fp2-home-card">
        <span class="fp2-home-card-label" data-i18n="fp2.home.light_now">Освещенность</span>
        <strong id="fp2HomeLightNow" class="fp2-home-card-value">-</strong>
      </article>
    </div>
    <div class="fp2-home-chart-grid">
      <div class="fp2-home-chart-card">
        <div class="fp2-home-chart-head">
          <h4 data-i18n="fp2.home.people_chart">Люди</h4>
          <strong id="fp2HomePeopleChartValue">-</strong>
        </div>
        <canvas id="fp2HomePeopleChart" width="480" height="220"></canvas>
      </div>
      <div class="fp2-home-chart-card">
        <div class="fp2-home-chart-head">
          <h4 data-i18n="fp2.home.light_chart">Освещенность</h4>
          <strong id="fp2HomeLightChartValue">-</strong>
        </div>
        <canvas id="fp2HomeLightChart" width="480" height="220"></canvas>
      </div>
    </div>
  </div>

  <div class="fp2-card fp2-card--map">
    <div class="fp2-card-header-row fp2-card-header-row--map">
      <div class="fp2-map-title">
        <h3 data-i18n="fp2.movement_map">Карта движения</h3>
        <div id="fp2RoomProfileMeta" class="fp2-map-profile-meta">-</div>
      </div>
      <div class="fp2-map-toolbar">
        <div class="fp2-map-profile-picker">
          <label for="fp2RoomProfileSelect" data-i18n="fp2.layout.label">Профиль</label>
          <select id="fp2RoomProfileSelect" class="fp2-map-select"></select>
        </div>
        <div id="fp2CsiRenderModeGroup" class="fp2-map-profile-picker" hidden>
          <label for="fp2CsiRenderMode" data-i18n="fp2.map.render_mode.label">Режим CSI</label>
          <select id="fp2CsiRenderMode" class="fp2-map-select">
            <option value="raw" data-i18n="fp2.map.render_mode.raw">CSI raw</option>
            <option value="assisted" data-i18n="fp2.map.render_mode.assisted">CSI assisted</option>
          </select>
        </div>
        <div class="fp2-map-calibration">
          <div class="fp2-map-calibration-buttons">
            <button id="fp2CalibrationCaptureLeft" class="btn btn--secondary btn--sm" data-i18n="fp2.calibration.capture_left">Левый край</button>
            <button id="fp2CalibrationCaptureRight" class="btn btn--secondary btn--sm" data-i18n="fp2.calibration.capture_right">Правый край</button>
            <button id="fp2CalibrationCaptureFar" class="btn btn--secondary btn--sm" data-i18n="fp2.calibration.capture_far">Дальняя стена</button>
            <button id="fp2CalibrationApply" class="btn btn--secondary btn--sm" data-i18n="fp2.calibration.apply">Применить</button>
            <button id="fp2CalibrationReset" class="btn btn--secondary btn--sm" data-i18n="fp2.calibration.reset">Сброс</button>
          </div>
          <div id="fp2CalibrationStatus" class="fp2-map-calibration-status">-</div>
        </div>
        <div class="fp2-map-layout-actions">
          <button id="fp2RoomEditMode" class="btn btn--secondary btn--sm fp2-layout-edit-btn" data-i18n="fp2.layout.edit_mode">Редактировать план</button>
          <button id="fp2RoomConfigExport" class="btn btn--secondary btn--sm" data-i18n="fp2.layout.export_config">Экспорт плана</button>
          <button id="fp2RoomConfigImport" class="btn btn--secondary btn--sm" data-i18n="fp2.layout.import_config">Импорт плана</button>
          <input id="fp2RoomConfigFile" type="file" accept="application/json" hidden>
        </div>
        <label class="fp2-map-toggle" for="fp2AnimalFilterToggle">
          <input id="fp2AnimalFilterToggle" type="checkbox">
          <span data-i18n="fp2.filter.animals">Фильтр животных</span>
        </label>
        <button id="fp2RoomProfileSave" class="btn btn--secondary btn--sm" data-i18n="fp2.layout.save">Сохранить</button>
        <button id="fp2RoomProfileDelete" class="btn btn--secondary btn--sm" data-i18n="fp2.layout.delete">Удалить</button>
        <div class="fp2-map-badges">
          <span id="fp2AnimalFilterStatus" class="chip chip--neutral">-</span>
          <span id="fp2MapMode" class="chip chip--info">-</span>
          <span id="fp2CoordinateCount" class="fp2-map-badge-count">-</span>
        </div>
      </div>
    </div>
    <div id="fp2TruthStatus" class="fp2-map-calibration-status">-</div>
    <canvas id="fp2MovementCanvas" class="fp2-movement-canvas" width="960" height="500"></canvas>
    <div class="fp2-layout-studio">
      <div class="fp2-layout-boundary-panel">
        <div class="fp2-card-header-row fp2-card-header-row--map">
          <h4 data-i18n="fp2.layout.room_boundary.title">Контур помещения</h4>
          <div class="fp2-map-badges">
            <span id="fp2RoomBoundaryStatus" class="chip chip--neutral">-</span>
          </div>
        </div>
        <div class="fp2-map-layout-actions">
          <button id="fp2RoomBoundaryStart" class="btn btn--secondary btn--sm" data-i18n="fp2.layout.room_boundary.start">Начать захват</button>
          <button id="fp2RoomBoundaryCapture" class="btn btn--secondary btn--sm" data-i18n="fp2.layout.room_boundary.capture">Зафиксировать угол</button>
          <button id="fp2RoomBoundaryUndo" class="btn btn--secondary btn--sm" data-i18n="fp2.layout.room_boundary.undo">Убрать последнюю точку</button>
          <button id="fp2RoomBoundaryClear" class="btn btn--secondary btn--sm" data-i18n="fp2.layout.room_boundary.clear">Очистить контур</button>
          <span id="fp2RoomBoundarySummary" class="fp2-layout-boundary-summary">-</span>
        </div>
        <p class="fp2-layout-hint" data-i18n="fp2.layout.room_boundary.hint">Встаньте в угол помещения и нажмите «Зафиксировать угол». Повторите последовательно для всех углов. Контур будет построен в координатах сенсора и автоматически определит тип фигуры.</p>
        <div id="fp2RoomBoundaryPoints" class="fp2-layout-boundary-points"></div>
      </div>
      <div class="fp2-card-header-row fp2-card-header-row--map">
        <h4 data-i18n="fp2.layout.items_title">Предметы в помещении</h4>
        <div class="fp2-layout-section-actions">
          <button id="fp2RoomAddToggle" class="btn btn--secondary btn--sm" data-i18n="fp2.layout.add">Добавить</button>
          <button id="fp2RoomItemsClear" class="btn btn--secondary btn--sm" data-i18n="fp2.layout.items_clear">Очистить предметы</button>
          <div class="fp2-map-badges">
            <span id="fp2RoomStorageStatus" class="chip chip--neutral">-</span>
            <span id="fp2RoomItemsSummary" class="fp2-map-badge-count">-</span>
          </div>
        </div>
      </div>
      <p class="fp2-layout-hint" data-i18n="fp2.layout.items_hint">Нажмите «Добавить», затем выберите предмет, стену или зону. После этого элемент сразу появится в рабочем потоке редактирования.</p>
      <div id="fp2RoomAddPanel" class="fp2-layout-add-panel" hidden>
        <label class="fp2-layout-field">
          <span data-i18n="fp2.layout.add_kind_label">Что добавить</span>
          <select id="fp2RoomAddKind" class="fp2-map-select">
            <option value="item" data-i18n="fp2.layout.add_kind.item">Предмет</option>
            <option value="wall" data-i18n="fp2.layout.add_kind.wall">Стена</option>
            <option value="zone" data-i18n="fp2.layout.add_kind.zone">Зона</option>
          </select>
        </label>
        <label id="fp2RoomAddItemField" class="fp2-layout-field">
          <span data-i18n="fp2.layout.add_item_label">Предмет</span>
          <select id="fp2RoomAddItemType" class="fp2-map-select"></select>
        </label>
        <div class="fp2-layout-add-actions">
          <button id="fp2RoomAddConfirm" class="btn btn--primary btn--sm" data-i18n="fp2.layout.add_confirm.item">Добавить на карту</button>
          <button id="fp2RoomAddCancel" class="btn btn--secondary btn--sm" data-i18n="fp2.layout.add_cancel">Закрыть</button>
        </div>
      </div>
      <div id="fp2RoomItemInspector" class="fp2-layout-inspector">
        <div class="fp2-layout-inspector-head">
          <strong id="fp2SelectedRoomItemName">-</strong>
          <div class="fp2-layout-inspector-actions">
            <span id="fp2RoomEditModeStatus" class="chip chip--neutral">-</span>
            <button id="fp2SelectedRoomItemRotateLeft" class="btn btn--secondary btn--sm" data-i18n="fp2.layout.rotate_left">-90°</button>
            <button id="fp2SelectedRoomItemRotateRight" class="btn btn--secondary btn--sm" data-i18n="fp2.layout.rotate_right">+90°</button>
            <button id="fp2SelectedRoomItemDelete" class="btn btn--secondary btn--sm" data-i18n="fp2.layout.item_remove">Удалить</button>
          </div>
        </div>
        <div class="fp2-layout-inspector-grid">
          <label class="fp2-layout-field">
            <span>X</span>
            <input id="fp2RoomItemX" type="range" min="-500" max="500" step="1">
            <strong id="fp2RoomItemXValue">-</strong>
          </label>
          <label class="fp2-layout-field">
            <span>Y</span>
            <input id="fp2RoomItemY" type="range" min="0" max="600" step="1">
            <strong id="fp2RoomItemYValue">-</strong>
          </label>
          <label class="fp2-layout-field">
            <span data-i18n="fp2.layout.field_width">Ширина</span>
            <input id="fp2RoomItemWidth" type="range" min="20" max="400" step="1">
            <strong id="fp2RoomItemWidthValue">-</strong>
          </label>
          <label class="fp2-layout-field">
            <span data-i18n="fp2.layout.field_depth">Глубина</span>
            <input id="fp2RoomItemDepth" type="range" min="20" max="400" step="1">
            <strong id="fp2RoomItemDepthValue">-</strong>
          </label>
          <label class="fp2-layout-field">
            <span data-i18n="fp2.layout.field_rotation">Поворот</span>
            <input id="fp2RoomItemRotation" type="range" min="0" max="345" step="15">
            <strong id="fp2RoomItemRotationValue">-</strong>
          </label>
        </div>
        <p class="fp2-layout-hint" data-i18n="fp2.layout.drag_hint">Предмет можно перетаскивать на карте. Потяните за правый нижний угол, чтобы изменить размер.</p>
      </div>
      <div id="fp2RoomItemsList" class="fp2-layout-items"></div>
      <div class="fp2-layout-structures-panel">
        <div class="fp2-card-header-row fp2-card-header-row--map">
          <h4 data-i18n="fp2.layout.structures_title">Внутренние границы и препятствия</h4>
          <div class="fp2-map-badges">
            <span id="fp2RoomStructureDrawStatus" class="chip chip--neutral">-</span>
            <span id="fp2RoomStructuresSummary" class="fp2-map-badge-count">-</span>
          </div>
        </div>
        <div class="fp2-map-layout-actions">
          <button id="fp2RoomStructureFinish" class="btn btn--secondary btn--sm" data-i18n="fp2.layout.structure_finish">Замкнуть контур</button>
          <button id="fp2RoomStructureCancel" class="btn btn--secondary btn--sm" data-i18n="fp2.layout.structure_cancel">Отменить контур</button>
          <button id="fp2RoomStructuresClear" class="btn btn--secondary btn--sm" data-i18n="fp2.layout.structure_clear">Очистить границы</button>
        </div>
        <p class="fp2-layout-hint" data-i18n="fp2.layout.structure_draw_hint">В режиме редактирования выберите «Стена» или «Зона». Для стены достаточно двух точек, для зоны ставьте вершины по клику на карте. Толщину стены можно менять после выбора.</p>
        <div id="fp2RoomStructureInspector" class="fp2-layout-inspector">
          <div class="fp2-layout-inspector-head">
            <strong id="fp2SelectedRoomStructureName">-</strong>
            <div class="fp2-layout-inspector-actions">
              <span id="fp2RoomStructureSelectionStatus" class="chip chip--neutral">-</span>
              <button id="fp2SelectedRoomStructureDelete" class="btn btn--secondary btn--sm" data-i18n="fp2.layout.item_remove">Удалить</button>
            </div>
          </div>
          <div class="fp2-layout-inspector-grid">
            <label class="fp2-layout-field">
              <span data-i18n="fp2.layout.structure_field_name">Название</span>
              <input id="fp2RoomStructureLabel" type="text" maxlength="64">
            </label>
            <label class="fp2-layout-field">
              <span data-i18n="fp2.layout.structure_field_thickness">Толщина стены</span>
              <input id="fp2RoomStructureThickness" type="range" min="6" max="120" step="1">
              <strong id="fp2RoomStructureThicknessValue">-</strong>
            </label>
            <div class="fp2-layout-field">
              <span data-i18n="fp2.layout.structure_field_kind">Тип</span>
              <strong id="fp2RoomStructureKindValue">-</strong>
            </div>
            <div class="fp2-layout-field">
              <span data-i18n="fp2.layout.structure_field_points">Точки</span>
              <strong id="fp2RoomStructurePointsValue">-</strong>
            </div>
            <div class="fp2-layout-field">
              <span data-i18n="fp2.layout.structure_field_length">Длина</span>
              <strong id="fp2RoomStructureLengthValue">-</strong>
            </div>
            <div class="fp2-layout-field">
              <span data-i18n="fp2.layout.structure_field_area">Площадь</span>
              <strong id="fp2RoomStructureAreaValue">-</strong>
            </div>
          </div>
          <div id="fp2RoomStructurePointEditor" class="fp2-layout-structure-point-editor"></div>
          <p class="fp2-layout-hint" data-i18n="fp2.layout.structure_editor_hint">Выделите стену или зону на карте. Стены редактируются перетаскиванием концов и изменением толщины, зону можно корректировать вершинами.</p>
        </div>
        <div id="fp2RoomStructuresList" class="fp2-layout-structures"></div>
      </div>
    </div>
  </div>

  <div class="fp2-card fp2-card--telemetry-health">
    <div class="fp2-card-header-row">
      <div>
        <h3 data-i18n="fp2.telemetry_health.title">Состояние устройств и сигнала</h3>
        <p class="help-text" data-i18n="fp2.telemetry_health.help">Быстрая проверка: жив ли FP2, приходят ли CSI-пакеты, какие узлы реально шлют данные и не отвалилась ли связь.</p>
      </div>
      <div id="fp2TelemetryHealthBadges" class="fp2-map-badges"></div>
    </div>
    <div class="fp2-telemetry-health-grid">
      <section class="fp2-telemetry-health-block">
        <h4 data-i18n="fp2.telemetry_health.fp2">FP2 / транспорт</h4>
        <div id="fp2TelemetryFp2Overview" class="fp2-telemetry-health-list"></div>
      </section>
      <section class="fp2-telemetry-health-block">
        <h4 data-i18n="fp2.telemetry_health.csi">CSI / поток</h4>
        <div id="fp2TelemetryCsiOverview" class="fp2-telemetry-health-list"></div>
      </section>
      <section class="fp2-telemetry-health-block">
        <h4 data-i18n="fp2.telemetry_health.sources">Узлы / источники</h4>
        <div id="fp2TelemetrySources" class="fp2-telemetry-status-grid"></div>
      </section>
      <section class="fp2-telemetry-health-block">
        <h4 data-i18n="fp2.telemetry_health.routers">Роутеры / сбор</h4>
        <div id="fp2TelemetryRouters" class="fp2-telemetry-status-grid"></div>
      </section>
    </div>
  </div>

  <div class="fp2-grid fp2-grid--info">
    <div class="fp2-card fp2-card--accent">
      <h3 data-i18n="fp2.connection">Подключение</h3>
      <div class="fp2-kv"><span data-i18n="fp2.connection.api">API</span><span id="fp2ApiStatus" class="chip chip--neutral">-</span></div>
      <div class="fp2-kv fp2-kv--actions">
        <span data-i18n="fp2.telemetry_source.label">Источник телеметрии</span>
        <span class="fp2-inline-actions fp2-inline-actions--telemetry-source">
          <select id="fp2TelemetrySourceMode" class="fp2-map-select fp2-map-select--compact">
            <option value="auto" data-i18n="fp2.telemetry_source.mode.auto">Авто</option>
            <option value="csi" data-i18n="fp2.telemetry_source.mode.csi">Только CSI</option>
            <option value="fp2" data-i18n="fp2.telemetry_source.mode.fp2">Только FP2</option>
          </select>
          <span id="fp2TelemetrySourceResolved" class="chip chip--neutral">-</span>
        </span>
      </div>
      <div class="fp2-kv"><span data-i18n="fp2.telemetry_source.help">Что использовать для карты, координат и статуса</span><strong id="fp2TelemetrySourceHint">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.connection.sensor_link">Связь с сенсором</span><span id="fp2StreamStatus" class="chip chip--neutral" data-i18n="common.offline">НЕ В СЕТИ</span></div>
      <div class="fp2-kv"><span data-i18n="fp2.connection.state">Состояние</span><strong id="fp2ConnectionState">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.connection.transport">Транспорт</span><strong id="fp2TransportValue">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.connection.source">Источник</span><code id="fp2EntityId">fp2</code></div>
      <div class="fp2-kv"><span data-i18n="fp2.connection.last_packet">Последний пакет</span><strong id="fp2LastPacketAge">-</strong></div>
    </div>

    <div class="fp2-card">
      <h3 data-i18n="fp2.device">Устройство</h3>
      <div class="fp2-device-title">
        <strong id="fp2DeviceName">Aqara FP2</strong>
        <span id="fp2DeviceModel">-</span>
      </div>
      <div class="fp2-kv"><span data-i18n="fp2.device_id">ID устройства</span><code id="fp2DeviceId">-</code></div>
      <div class="fp2-kv"><span data-i18n="fp2.mac">MAC</span><code id="fp2DeviceMac">-</code></div>
      <div class="fp2-kv"><span data-i18n="fp2.endpoint">Endpoint</span><code id="fp2DeviceIp">-</code></div>
      <div class="fp2-kv"><span data-i18n="fp2.pairing_id">ID pairing</span><code id="fp2PairingId">-</code></div>
      <div class="fp2-kv"><span data-i18n="fp2.cloud_did">Cloud DID</span><code id="fp2CloudDid">-</code></div>
      <div class="fp2-kv"><span data-i18n="fp2.position_id">Position ID</span><code id="fp2PositionId">-</code></div>
      <div class="fp2-kv"><span data-i18n="fp2.room">Комната</span><strong id="fp2RoomValue">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.firmware">Прошивка</span><strong id="fp2FirmwareValue">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.network">Сеть</span><strong id="fp2NetworkValue">-</strong></div>
    </div>

    <div class="fp2-card">
      <h3 data-i18n="fp2.sensor_diagnostics">Диагностика сенсора</h3>
      <div class="fp2-kv"><span data-i18n="fp2.online">Онлайн</span><strong id="fp2OnlineState">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.sensor_angle">Угол сенсора</span>
        <span class="fp2-angle-row"><strong id="fp2SensorAngle">-</strong><canvas id="fp2AngleDial" width="32" height="32"></canvas></span>
      </div>
      <div class="fp2-kv"><span data-i18n="fp2.fall_state">Состояние падения</span><strong id="fp2FallState">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.device_timestamp">Время устройства</span><strong id="fp2DeviceTimestamp">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.coordinate_change">Изменение координат</span><strong id="fp2CoordinateChangeAge">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.coordinate_confidence">Надежность координат</span><span id="fp2CoordinateConfidence" class="chip chip--neutral">-</span></div>
      <div class="fp2-kv"><span data-i18n="fp2.coordinate_updates_rate">Апдейты координат</span><strong id="fp2CoordinateUpdateRate">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.coordinate_health">Качество потока</span><span id="fp2CoordinateHealthBadge" class="chip chip--neutral">-</span></div>
      <div class="fp2-kv fp2-kv--actions">
        <span data-i18n="fp2.coordinate_control">Отправка координат</span>
        <span class="fp2-inline-actions">
          <span id="fp2CoordinateSwitchState" class="chip chip--neutral">-</span>
          <button id="fp2CoordinateEnable" class="btn btn--secondary btn--sm" data-i18n="fp2.coordinate_enable">Включить координаты</button>
        </span>
      </div>
      <div class="fp2-coordinate-monitor">
        <canvas id="fp2CoordinateQualityCanvas" width="320" height="72"></canvas>
      </div>
      <div class="fp2-kv"><span data-i18n="fp2.api_domain">Домен API</span><strong id="fp2ApiDomain">-</strong></div>
    </div>

    <div class="fp2-card">
      <h3 data-i18n="fp2.advanced.title">Расширенные функции</h3>
      <div class="fp2-kv"><span data-i18n="fp2.advanced.realtime_people">Людей сейчас</span><strong id="fp2RealtimePeople">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.advanced.visitors_1m">Посетители (1 мин)</span><strong id="fp2Visitors1m">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.advanced.area_entries_10s">Входы по зоне (10с)</span><strong id="fp2AreaEntries10s">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.advanced.walking_distance">Дистанция ходьбы</span><strong id="fp2WalkingDistance">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.advanced.people_mode">Режим статистики людей</span><span id="fp2PeopleMode" class="chip chip--neutral">-</span></div>
      <div class="fp2-kv"><span data-i18n="fp2.advanced.distance_mode">Режим дистанции</span><span id="fp2DistanceMode" class="chip chip--neutral">-</span></div>
    </div>

    <div class="fp2-card fp2-card--scenario">
      <div class="fp2-card-header-row">
        <div>
          <h3 data-i18n="fp2.scenario.title">Сценарии</h3>
          <p class="help-text fp2-scenario-help" data-i18n="fp2.scenario.help">Пресеты для типовых сценариев: что они включают, какие каналы используют и зачем это нужно.</p>
        </div>
        <span id="fp2ScenarioStatus" class="chip chip--neutral">-</span>
      </div>
      <div id="fp2ScenarioTabs" class="fp2-scenario-tabs"></div>
      <div id="fp2ScenarioDetail" class="fp2-scenario-detail"></div>
    </div>

    <div class="fp2-card">
      <h3 data-i18n="fp2.config.modes_title">Режимы устройства</h3>
      <div class="fp2-kv"><span data-i18n="fp2.resource.realtime_position_switch">Переключатель отправки координат</span><strong id="fp2RealtimePositionSwitch">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.resource.work_mode">Режим работы</span><strong id="fp2WorkMode">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.resource.detection_mode">Режим обнаружения</span><strong id="fp2DetectionMode">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.resource.do_not_disturb_switch">Переключатель режима не беспокоить</span><strong id="fp2DoNotDisturbSwitch">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.resource.do_not_disturb_schedule">Период не беспокоить</span><strong id="fp2DoNotDisturbSchedule">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.resource.indicator_light">Индикатор</span><strong id="fp2IndicatorLight">-</strong></div>
    </div>

    <div class="fp2-card">
      <h3 data-i18n="fp2.config.installation_title">Монтаж и чувствительность</h3>
      <div class="fp2-kv"><span data-i18n="fp2.resource.installation_position">Положение установки</span><strong id="fp2InstallationPosition">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.resource.installation_height">Высота установки</span><strong id="fp2InstallationHeight">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.resource.bed_height">Высота кровати</span><strong id="fp2BedHeight">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.resource.installation_angle_status">Статус угла установки</span><strong id="fp2InstallationAngleStatus">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.resource.presence_sensitivity">Чувствительность обнаружения человека</span><strong id="fp2PresenceSensitivity">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.resource.approach_detection_level">Уровень чувствительности приближения</span><strong id="fp2ApproachLevel">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.resource.fall_detection_sensitivity">Чувствительность распознавания падения</span><strong id="fp2FallDetectionSensitivity">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.resource.fall_detection_delay">Задержка определения падения</span><strong id="fp2FallDetectionDelay">-</strong></div>
    </div>

    <div class="fp2-card">
      <h3 data-i18n="fp2.config.body_title">Телеметрия кровати и тела</h3>
      <div class="fp2-kv"><span data-i18n="fp2.resource.respiration_reporting">Отправка дыхания</span><strong id="fp2RespirationReporting">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.resource.respiration_reporting_minute">Отправка дыхания (по минутам)</span><strong id="fp2RespirationReportingMinute">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.resource.respiration_confidence">Достоверность дыхания</span><strong id="fp2RespirationConfidence">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.resource.heart_rate_confidence">Достоверность сердечного ритма</span><strong id="fp2HeartRateConfidence">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.resource.body_movement_level">Уровень телодвижения</span><strong id="fp2BodyMovementLevel">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.resource.bedside_installation_position">Положение установки у кровати</span><strong id="fp2BedsideInstallationPosition">-</strong></div>
    </div>

    <div class="fp2-card">
      <h3 data-i18n="fp2.config.system_flags_title">Служебные флаги</h3>
      <div class="fp2-kv"><span data-i18n="fp2.resource.first_network_join">Первое подключение к сети</span><strong id="fp2FirstNetworkJoin">-</strong></div>
      <div class="fp2-kv"><span data-i18n="fp2.resource.reset_absence_state">Сброс состояния отсутствия</span><strong id="fp2ResetAbsenceState">-</strong></div>
    </div>

    <div class="fp2-card">
      <h3 data-i18n="fp2.aqara_app.title">Возможности Aqara Home</h3>
      <div class="fp2-kv"><span data-i18n="fp2.aqara_app.ai_learning">AI Learning</span><span class="chip chip--neutral" data-i18n="fp2.aqara_app.app_only">Только Aqara Home</span></div>
      <div class="fp2-kv"><span data-i18n="fp2.aqara_app.body_ai">ИИ распознавание тела</span><span class="chip chip--neutral" data-i18n="fp2.aqara_app.partial">Частично</span></div>
      <div class="fp2-kv"><span data-i18n="fp2.aqara_app.room_templates">Шаблоны комнаты</span><span class="chip chip--warn" data-i18n="fp2.aqara_app.partial">Частично</span></div>
      <div class="fp2-kv"><span data-i18n="fp2.aqara_app.furniture_editor">Редактор мебели</span><span class="chip chip--warn" data-i18n="fp2.aqara_app.partial">Частично</span></div>
      <div class="fp2-kv"><span data-i18n="fp2.aqara_app.find_device">Найти устройство</span><span class="chip chip--neutral" data-i18n="fp2.aqara_app.app_only">Только Aqara Home</span></div>
      <div class="fp2-aqara-note" data-i18n="fp2.aqara_app.note">Эти функции есть в Aqara Home. В этом UI они либо зеркалятся по данным, либо помечены как app-only, если публичный Open API не отдает нужное состояние или управление.</div>
    </div>
  </div>

  <div class="fp2-card">
    <div class="fp2-card-header-row">
      <h3 data-i18n="fp2.target_telemetry">Телеметрия целей</h3>
      <div class="fp2-target-summary">
        <span><span data-i18n="fp2.target.primary">Основная</span>: <strong id="fp2PrimaryTargetId">-</strong></span>
        <span><span data-i18n="fp2.target.active">Активных</span>: <strong id="fp2ActiveTargetCount">-</strong></span>
        <span><span data-i18n="fp2.target.with_coords">С координатами</span>: <strong id="fp2CoordinateTargetCount">-</strong></span>
        <span><span data-i18n="fp2.target.session_peak">Пик сессии</span>: <strong id="fp2SessionPeakTargetCount">-</strong></span>
        <span><span data-i18n="fp2.target.type">Тип</span>: <strong id="fp2PrimaryTargetType">-</strong></span>
        <span><span data-i18n="fp2.target.coords">Коорд.</span>: <strong id="fp2PrimaryTargetCoords">-</strong></span>
        <span><span data-i18n="fp2.target.dist">Дист.</span>: <strong id="fp2PrimaryTargetDistance">-</strong></span>
        <span><span data-i18n="fp2.target.angle">Угол</span>: <strong id="fp2PrimaryTargetAngle">-</strong></span>
      </div>
    </div>
    <div id="fp2TargetList" class="fp2-target-list"></div>
  </div>

  <div class="fp2-card">
    <h3 data-i18n="fp2.zone_occupancy">Занятость зон</h3>
    <div id="fp2ZoneWindows" class="fp2-zone-windows"></div>
  </div>

  <div class="fp2-card">
    <h3 data-i18n="fp2.zone.analytics.title">Аналитика зон</h3>
    <div id="fp2ZoneAnalytics" class="fp2-zone-analytics"></div>
  </div>

  <div class="fp2-card">
    <div class="fp2-card-header-row">
      <h3 data-i18n="fp2.zone.summary.title">Сводка по зонам</h3>
      <span id="fp2ZoneSummaryRange" class="chip chip--neutral">24h</span>
    </div>
    <p class="help-text" data-i18n="fp2.zone.summary.help">Использует тот же диапазон День/Неделя, что и обзор Aqara Home.</p>
    <div id="fp2ZoneRangeSummary" class="fp2-zone-summary-list"></div>
  </div>

  <div class="fp2-grid fp2-grid--timeline">
    <div class="fp2-card fp2-card--graph">
      <h3 data-i18n="fp2.presence_timeline">Шкала присутствия</h3>
      <canvas id="fp2RealtimeGraph" width="960" height="220" style="width:100%;height:220px;border-radius:8px;"></canvas>
      <div class="fp2-graph-legend">
        <span class="legend-item"><span class="legend-color present"></span> <span data-i18n="fp2.legend.present">Есть</span></span>
        <span class="legend-item"><span class="legend-color absent"></span> <span data-i18n="fp2.legend.absent">Нет</span></span>
        <span class="legend-item"><span class="legend-color targets"></span> <span data-i18n="fp2.legend.targets">Цели</span></span>
      </div>
    </div>

    <div class="fp2-card fp2-card--events">
      <h3 data-i18n="fp2.event_log">Журнал событий</h3>
      <ul id="fp2MovementList" class="fp2-history-list fp2-movement-list"></ul>
      <h4 class="fp2-events-divider" data-i18n="fp2.presence_history">История присутствия</h4>
      <ul id="fp2HistoryList" class="fp2-history-list"></ul>
    </div>
  </div>

  <div class="fp2-card">
    <h3 data-i18n="fp2.resource_channels">Каналы ресурсов</h3>
    <p class="help-text" data-i18n="fp2.resource_channels_help" style="font-size:0.72rem;color:var(--text-muted);margin-bottom:8px;">Сырые Aqara resource ID и текущие значения из live payload.</p>
    <div id="fp2ResourceGrid" class="fp2-resource-grid"></div>
  </div>

  <div class="fp2-grid fp2-grid--payloads">
    <details id="fp2SensorDetails" class="fp2-payload-details">
      <summary data-i18n="fp2.raw_sensor_telemetry">Сырая телеметрия сенсора</summary>
      <pre id="fp2SensorOutput" class="fp2-raw-output">{}</pre>
    </details>
    <details id="fp2RawDetails" class="fp2-payload-details">
      <summary data-i18n="fp2.compatibility_payload">Совместимый payload</summary>
      <pre id="fp2RawOutput" class="fp2-raw-output">{}</pre>
    </details>
  </div>
`;
