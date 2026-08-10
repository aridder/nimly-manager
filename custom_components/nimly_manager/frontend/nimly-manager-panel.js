const SLOT_MIN = 3;
const SLOT_MAX = 199;
const ACTIVE_STATES = new Set(["local_programming", "awaiting_verification"]);

class NimlyManagerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._data = null;
    this._entryId = null;
    this._selectedSlot = null;
    this._personName = "";
    this._loading = false;
    this._working = false;
    this._error = "";
    this._pollTimer = null;
  }

  set hass(value) {
    this._hass = value;
    if (this.isConnected && !this._data && !this._loading) {
      this._load();
    }
  }

  connectedCallback() {
    this._render();
    if (this._hass) this._load();
    this._pollTimer = window.setInterval(() => this._load(true), 3000);
  }

  disconnectedCallback() {
    window.clearInterval(this._pollTimer);
    this._pollTimer = null;
  }

  async _load(quiet = false) {
    if (!this._hass || this._loading || this._working) return;
    this._loading = true;
    if (!quiet) this._render();
    let changed = false;
    try {
      const data = await this._hass.callWS({ type: "nimly_manager/state" });
      changed = JSON.stringify(data) !== JSON.stringify(this._data);
      this._data = data;
      const entryIds = this._data.entries.map((entry) => entry.config_entry_id);
      if (!entryIds.includes(this._entryId)) this._entryId = entryIds[0] || null;
      this._error = "";
    } catch (error) {
      this._error = this._errorText(error);
    } finally {
      this._loading = false;
      if (!quiet || changed || this._error) this._render();
    }
  }

  get _entry() {
    return (
      this._data?.entries.find(
        (entry) => entry.config_entry_id === this._entryId,
      ) || null
    );
  }

  async _action(type, fields = {}) {
    if (!this._hass || !this._entryId || this._working) return;
    this._working = true;
    this._error = "";
    this._render();
    try {
      await this._hass.callWS({
        type,
        config_entry_id: this._entryId,
        ...fields,
      });
      this._working = false;
      await this._load();
    } catch (error) {
      this._error = this._errorText(error);
    } finally {
      this._working = false;
      this._render();
    }
  }

  _start() {
    const personName = this._personName.trim();
    if (!personName) {
      this._error = "Skriv inn navnet til personen.";
      this._render();
      return;
    }
    if (this._selectedSlot === null) {
      this._error = "Velg en ukjent slot først.";
      this._render();
      return;
    }
    this._action("nimly_manager/enrollment/start", {
      person_name: personName,
      slot: this._selectedSlot,
    });
  }

  _confirm(sessionId) {
    this._action("nimly_manager/enrollment/confirm", {
      session_id: sessionId,
    });
  }

  _cancel(sessionId) {
    this._action("nimly_manager/enrollment/cancel", {
      session_id: sessionId,
    });
  }

  _render() {
    if (!this.shadowRoot) return;
    const entry = this._entry;
    this.shadowRoot.innerHTML = `
      <style>${this._styles()}</style>
      <main>
        <header class="topbar">
          <div>
            <p class="eyebrow">HOME ASSISTANT</p>
            <h1>Nimly Manager</h1>
          </div>
          <button class="icon-button" id="refresh" aria-label="Oppdater" title="Oppdater" ${this._loading ? "disabled" : ""}>
            <span class="refresh-icon ${this._loading ? "spinning" : ""}">↻</span>
          </button>
        </header>
        ${this._error ? `<div class="alert" role="alert">${this._escape(this._error)}</div>` : ""}
        ${this._content(entry)}
        <footer>Biometri og masterfinger forlater aldri låsen.</footer>
      </main>
    `;
    this._bindEvents(entry);
  }

  _content(entry) {
    if (!this._data) {
      return `<section class="card empty"><div class="loader"></div><h2>Kobler til Nimly Manager</h2><p>Henter status fra Home Assistant.</p></section>`;
    }
    if (!entry) {
      return `
        <section class="card empty">
          <div class="empty-icon">⌂</div>
          <h2>Ingen Nimly-lås er konfigurert</h2>
          <p>Legg til Nimly Manager under Innstillinger → Enheter og tjenester, og kom tilbake hit.</p>
        </section>`;
    }

    const known = new Map(entry.slots.map((slot) => [slot.slot, slot]));
    const enrollment = entry.enrollment;
    const active = enrollment && ACTIVE_STATES.has(enrollment.state);
    const occupiedCount = entry.slots.length;
    const unknownCount = SLOT_MAX - SLOT_MIN + 1 - occupiedCount;

    return `
      ${this._deviceCard(entry)}
      ${active || enrollment?.state === "verified" ? this._workflow(entry) : ""}
      <section class="card slots-card">
        <div class="section-heading">
          <div>
            <p class="eyebrow">FINGERAVTRYKK</p>
            <h2>Slots</h2>
          </div>
          <div class="counts"><strong>${occupiedCount}</strong> kjent · <strong>${unknownCount}</strong> ukjent</div>
        </div>
        <div class="legend" aria-label="Forklaring">
          <span><i class="dot verified"></i> Verifisert</span>
          <span><i class="dot observed"></i> Observert</span>
          <span><i class="dot unknown"></i> Ukjent</span>
        </div>
        <p class="explanation">Ukjent betyr at Nimly Manager ikke har bevis for om sloten er opptatt. Velg bare en slot du vet kan brukes.</p>
        <div class="slot-grid" role="grid" aria-label="Fingeravtrykk-slots">
          ${Array.from({ length: SLOT_MAX - SLOT_MIN + 1 }, (_, index) => {
            const slot = index + SLOT_MIN;
            return this._slotButton(slot, known.get(slot), enrollment);
          }).join("")}
        </div>
        ${!active ? this._startForm(known) : `<p class="active-note">Fullfør eller avbryt aktiv registrering før du velger en ny slot.</p>`}
      </section>
    `;
  }

  _deviceCard(entry) {
    const locked = entry.lock_state === "locked";
    const unlocked = entry.lock_state === "unlocked";
    const stateText = locked ? "Låst" : unlocked ? "Ulåst" : "Ukjent";
    const mqttText = entry.last_mqtt_at
      ? `Sist sett ${this._relativeTime(entry.last_mqtt_at)}`
      : "Venter på MQTT-state";
    const entryOptions = this._data.entries
      .map(
        (item) =>
          `<option value="${this._escape(item.config_entry_id)}" ${item.config_entry_id === this._entryId ? "selected" : ""}>${this._escape(item.title)}</option>`,
      )
      .join("");
    return `
      <section class="card device-card">
        <div class="lock-orb ${locked ? "locked" : unlocked ? "unlocked" : "unknown"}">
          <span>${locked ? "●" : unlocked ? "○" : "?"}</span>
        </div>
        <div class="device-details">
          ${this._data.entries.length > 1 ? `<select id="entry-select" aria-label="Velg lås">${entryOptions}</select>` : `<h2>${this._escape(entry.title)}</h2>`}
          <div class="device-status"><strong>${stateText}</strong><span class="separator">·</span><span>${mqttText}</span></div>
          <code>${this._escape(entry.state_topic)}</code>
        </div>
      </section>`;
  }

  _workflow(entry) {
    const enrollment = entry.enrollment;
    if (!enrollment) return "";
    if (enrollment.state === "verified") {
      return `
        <section class="card success-card">
          <div class="success-icon">✓</div>
          <div><p class="eyebrow">BEKREFTET</p><h2>${this._escape(enrollment.person_name)} er registrert</h2><p>Fingeravtrykk-slot <strong>${this._escape(enrollment.keypad_slot)}</strong> ble verifisert med en ekte opplåsing.</p></div>
        </section>`;
    }
    const local = enrollment.state === "local_programming";
    return `
      <section class="card workflow-card">
        <div class="section-heading">
          <div><p class="eyebrow">AKTIV REGISTRERING</p><h2>${this._escape(enrollment.person_name)} · slot ${this._escape(enrollment.keypad_slot)}</h2></div>
          <span class="expires">Utløper ${this._relativeTime(enrollment.expires_at)}</span>
        </div>
        <ol class="stepper">
          <li class="${local ? "current" : "done"}"><span>1</span><div><strong>Programmer på låsen</strong><small>Følg sekvensen under.</small></div></li>
          <li class="${local ? "" : "current"}"><span>2</span><div><strong>Verifiser fingeren</strong><small>Lås, og lås opp med den nye fingeren.</small></div></li>
        </ol>
        ${local ? this._instructions(entry.instructions) : this._verificationPrompt(entry)}
        <div class="workflow-actions">
          ${local ? `<button class="primary" id="confirm" ${this._working ? "disabled" : ""}>Jeg har programmert låsen</button>` : ""}
          <button class="secondary danger" id="cancel" ${this._working ? "disabled" : ""}>Avbryt</button>
        </div>
      </section>`;
  }

  _instructions(instructions) {
    return `
      <div class="instruction-box">
        <h3>Gjør dette ved låsen</h3>
        <ol>${instructions
          .slice(0, 5)
          .map((instruction) => `<li>${this._escape(instruction)}</li>`)
          .join("")}</ol>
        <p class="privacy">Masterfingeren brukes bare fysisk på låsen og registreres aldri i Home Assistant.</p>
      </div>`;
  }

  _verificationPrompt(entry) {
    const state = entry.lock_state;
    return `
      <div class="verification-box">
        <div class="pulse-ring"><span>◎</span></div>
        <div>
          <h3>Venter på fingeravtrykket</h3>
          <p>${state === "locked" ? "Låsen er låst. Lås den nå opp med den nye fingeren." : "Lås låsen først, og lås den deretter opp med den nye fingeren."}</p>
          <small>Siden oppdateres automatisk når Zigbee2MQTT rapporterer riktig slot.</small>
        </div>
      </div>`;
  }

  _slotButton(slot, record, enrollment) {
    const isActive = enrollment && ACTIVE_STATES.has(enrollment.state) && enrollment.slot === slot;
    const status = isActive ? "active" : record?.status || "unknown";
    const selected = this._selectedSlot === slot && !record && !isActive;
    const label = record?.person_name
      ? `${String(slot).padStart(3, "0")}: ${record.person_name}, ${status}`
      : `${String(slot).padStart(3, "0")}: ${status === "unknown" ? "ukjent" : status}`;
    const title = record?.person_name || (record ? "Eier ukjent" : "Status ukjent");
    return `<button
      class="slot ${status} ${selected ? "selected" : ""}"
      data-slot="${slot}"
      role="gridcell"
      aria-label="${this._escape(label)}"
      title="${this._escape(title)}"
      ${record || isActive ? "disabled" : ""}
    >${String(slot).padStart(3, "0")}</button>`;
  }

  _startForm(known) {
    const selectedRecord = this._selectedSlot ? known.get(this._selectedSlot) : null;
    if (selectedRecord) this._selectedSlot = null;
    return `
      <div class="enroll-form">
        <div class="form-heading">
          <div><p class="eyebrow">NY REGISTRERING</p><h3>Legg til fingeravtrykk</h3></div>
          <div class="chosen-slot">${this._selectedSlot === null ? "Velg slot" : `Slot <strong>${String(this._selectedSlot).padStart(3, "0")}</strong>`}</div>
        </div>
        <label for="person-name">Navn</label>
        <input id="person-name" maxlength="100" autocomplete="name" placeholder="For eksempel Madeleine" value="${this._escape(this._personName)}">
        <button class="primary wide" id="start" ${this._working || this._selectedSlot === null ? "disabled" : ""}>${this._working ? "Starter …" : "Start registrering"}</button>
      </div>`;
  }

  _bindEvents(entry) {
    this.shadowRoot.getElementById("refresh")?.addEventListener("click", () => this._load());
    this.shadowRoot.getElementById("entry-select")?.addEventListener("change", (event) => {
      this._entryId = event.target.value;
      this._selectedSlot = null;
      this._error = "";
      this._render();
    });
    this.shadowRoot.querySelectorAll("button.slot:not([disabled])").forEach((button) => {
      button.addEventListener("click", () => {
        this._selectedSlot = Number(button.dataset.slot);
        this._error = "";
        this._render();
        this.shadowRoot.getElementById("person-name")?.focus();
      });
    });
    this.shadowRoot.getElementById("person-name")?.addEventListener("input", (event) => {
      this._personName = event.target.value;
    });
    this.shadowRoot.getElementById("start")?.addEventListener("click", () => {
      const input = this.shadowRoot.getElementById("person-name");
      if (input) this._personName = input.value;
      this._start();
    });
    const sessionId = entry?.enrollment?.session_id;
    if (sessionId) {
      this.shadowRoot.getElementById("confirm")?.addEventListener("click", () => this._confirm(sessionId));
      this.shadowRoot.getElementById("cancel")?.addEventListener("click", () => this._cancel(sessionId));
    }
  }

  _relativeTime(value) {
    const time = new Date(value).getTime();
    if (!Number.isFinite(time)) return "ukjent";
    const seconds = Math.round((time - Date.now()) / 1000);
    const absolute = Math.abs(seconds);
    const formatter = new Intl.RelativeTimeFormat("nb", { numeric: "auto" });
    if (absolute < 60) return formatter.format(seconds, "second");
    if (absolute < 3600) return formatter.format(Math.round(seconds / 60), "minute");
    if (absolute < 86400) return formatter.format(Math.round(seconds / 3600), "hour");
    return formatter.format(Math.round(seconds / 86400), "day");
  }

  _errorText(error) {
    return error?.message || error?.body?.message || "Noe gikk galt. Prøv igjen.";
  }

  _escape(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  _styles() {
    return `
      :host { display: block; min-height: 100vh; color: var(--primary-text-color, #17211d); background: var(--primary-background-color, #f4f6f5); font-family: var(--paper-font-body1_-_font-family, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif); }
      * { box-sizing: border-box; }
      main { width: min(100%, 1040px); margin: 0 auto; padding: max(22px, env(safe-area-inset-top)) clamp(14px, 3vw, 34px) max(40px, env(safe-area-inset-bottom)); }
      .topbar { display: flex; align-items: center; justify-content: space-between; margin: 4px 0 22px; }
      h1, h2, h3, p { margin-top: 0; }
      h1 { margin-bottom: 0; font-size: clamp(27px, 4vw, 38px); line-height: 1.06; letter-spacing: -.035em; }
      h2 { margin-bottom: 7px; font-size: clamp(20px, 3vw, 26px); letter-spacing: -.02em; }
      h3 { margin-bottom: 10px; font-size: 18px; }
      p { line-height: 1.5; }
      .eyebrow { margin: 0 0 6px; color: var(--secondary-text-color, #65736c); font-size: 11px; font-weight: 750; letter-spacing: .14em; }
      .card { margin-bottom: 16px; padding: clamp(18px, 3vw, 28px); border: 1px solid var(--divider-color, #dce3df); border-radius: 22px; background: var(--card-background-color, #fff); box-shadow: 0 8px 30px rgba(20, 43, 32, .05); }
      .icon-button { display: grid; width: 44px; height: 44px; place-items: center; border: 1px solid var(--divider-color, #dce3df); border-radius: 14px; background: var(--card-background-color, #fff); color: var(--primary-text-color, #17211d); font-size: 25px; cursor: pointer; }
      button { font: inherit; }
      button:focus-visible, input:focus-visible, select:focus-visible { outline: 3px solid color-mix(in srgb, var(--primary-color, #397960) 34%, transparent); outline-offset: 2px; }
      button:disabled { cursor: not-allowed; opacity: .58; }
      .refresh-icon { display: block; line-height: 1; }
      .spinning { animation: spin 1s linear infinite; }
      @keyframes spin { to { transform: rotate(360deg); } }
      .alert { margin-bottom: 16px; padding: 14px 16px; border: 1px solid #e7aaa5; border-radius: 14px; color: #7d2823; background: #fff0ee; line-height: 1.4; }
      .device-card { display: flex; align-items: center; gap: 17px; }
      .lock-orb { display: grid; flex: 0 0 54px; width: 54px; height: 54px; place-items: center; border-radius: 18px; font-size: 24px; }
      .lock-orb.locked { color: #1f6249; background: #ddf3e8; }
      .lock-orb.unlocked { color: #8b5917; background: #fff0d5; }
      .lock-orb.unknown { color: #59645f; background: #edf0ee; }
      .device-details { min-width: 0; flex: 1; }
      .device-details h2 { margin-bottom: 4px; }
      .device-status { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 7px; color: var(--secondary-text-color, #65736c); font-size: 14px; }
      .device-status strong { color: var(--primary-text-color, #17211d); }
      .device-details code { display: block; overflow: hidden; color: var(--secondary-text-color, #65736c); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
      select { max-width: 100%; margin: 0 0 8px; padding: 9px 32px 9px 11px; border: 1px solid var(--divider-color, #dce3df); border-radius: 10px; color: var(--primary-text-color, #17211d); background: var(--card-background-color, #fff); font: inherit; font-size: 17px; font-weight: 700; }
      .section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
      .counts, .expires { color: var(--secondary-text-color, #65736c); font-size: 13px; white-space: nowrap; }
      .legend { display: flex; flex-wrap: wrap; gap: 10px 18px; margin: 13px 0; color: var(--secondary-text-color, #65736c); font-size: 13px; }
      .legend span { display: inline-flex; align-items: center; gap: 7px; }
      .dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; }
      .dot.verified { background: #3d9369; } .dot.observed { background: #d18a29; } .dot.unknown { background: #c8cfcb; }
      .explanation { margin: 0 0 18px; color: var(--secondary-text-color, #65736c); font-size: 13px; }
      .slot-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(47px, 1fr)); gap: 7px; max-height: 330px; overflow: auto; padding: 3px 4px 5px 3px; scrollbar-width: thin; }
      .slot { min-height: 39px; border: 1px solid var(--divider-color, #dce3df); border-radius: 10px; color: var(--primary-text-color, #17211d); background: var(--secondary-background-color, #f4f6f5); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; cursor: pointer; transition: transform .12s, border-color .12s, background .12s; }
      .slot:not(:disabled):hover { transform: translateY(-1px); border-color: var(--primary-color, #397960); }
      .slot.verified { border-color: #a8d8c0; color: #205b43; background: #e3f4eb; opacity: 1; }
      .slot.observed { border-color: #edc98d; color: #7c5018; background: #fff2da; opacity: 1; }
      .slot.active { border-color: #7cb4e5; color: #174f7f; background: #e2f0fc; opacity: 1; }
      .slot.selected { border-color: var(--primary-color, #397960); color: #fff; background: var(--primary-color, #397960); box-shadow: 0 0 0 2px color-mix(in srgb, var(--primary-color, #397960) 22%, transparent); }
      .enroll-form { margin-top: 25px; padding-top: 22px; border-top: 1px solid var(--divider-color, #dce3df); }
      .form-heading { display: flex; justify-content: space-between; gap: 16px; }
      .chosen-slot { align-self: center; padding: 8px 11px; border-radius: 10px; color: var(--secondary-text-color, #65736c); background: var(--secondary-background-color, #f4f6f5); font-size: 13px; }
      label { display: block; margin: 8px 0 7px; font-size: 13px; font-weight: 700; }
      input { width: 100%; min-height: 48px; padding: 0 14px; border: 1px solid var(--divider-color, #cdd6d1); border-radius: 12px; color: var(--primary-text-color, #17211d); background: var(--card-background-color, #fff); font: inherit; font-size: 16px; }
      .primary, .secondary { min-height: 46px; padding: 0 18px; border-radius: 12px; font-weight: 700; cursor: pointer; }
      .primary { border: 0; color: #fff; background: var(--primary-color, #397960); }
      .secondary { border: 1px solid var(--divider-color, #cdd6d1); color: var(--primary-text-color, #17211d); background: transparent; }
      .wide { width: 100%; margin-top: 13px; }
      .danger { color: #a13c34; }
      .active-note { margin: 19px 0 0; padding: 13px; border-radius: 11px; color: #174f7f; background: #eaf4fc; font-size: 13px; }
      .stepper { display: grid; grid-template-columns: 1fr 1fr; gap: 0; margin: 20px 0; padding: 0; list-style: none; }
      .stepper li { position: relative; display: flex; align-items: center; gap: 10px; color: var(--secondary-text-color, #65736c); }
      .stepper li:first-child::after { position: absolute; z-index: 0; top: 16px; right: 7px; left: 40px; height: 2px; content: ""; background: var(--divider-color, #dce3df); }
      .stepper li > span { z-index: 1; display: grid; flex: 0 0 32px; height: 32px; place-items: center; border: 2px solid var(--divider-color, #cdd6d1); border-radius: 50%; background: var(--card-background-color, #fff); font-weight: 800; }
      .stepper li.current > span { border-color: var(--primary-color, #397960); color: #fff; background: var(--primary-color, #397960); }
      .stepper li.done > span { border-color: #6db48e; color: #1e6648; background: #def2e7; }
      .stepper strong, .stepper small { display: block; }
      .stepper strong { color: var(--primary-text-color, #17211d); font-size: 13px; }
      .stepper small { margin-top: 3px; font-size: 11px; }
      .instruction-box, .verification-box { margin: 16px 0; padding: clamp(16px, 3vw, 22px); border-radius: 16px; background: var(--secondary-background-color, #f4f6f5); }
      .instruction-box ol { margin: 0; padding-left: 21px; }
      .instruction-box li { margin: 9px 0; padding-left: 4px; line-height: 1.45; }
      .privacy { margin: 16px 0 0; color: var(--secondary-text-color, #65736c); font-size: 12px; }
      .verification-box { display: flex; align-items: center; gap: 18px; }
      .verification-box h3, .verification-box p { margin-bottom: 5px; }
      .verification-box small { color: var(--secondary-text-color, #65736c); }
      .pulse-ring { display: grid; flex: 0 0 56px; width: 56px; height: 56px; place-items: center; border-radius: 50%; color: var(--primary-color, #397960); background: color-mix(in srgb, var(--primary-color, #397960) 12%, transparent); font-size: 29px; animation: pulse 2s ease-in-out infinite; }
      @keyframes pulse { 50% { box-shadow: 0 0 0 8px color-mix(in srgb, var(--primary-color, #397960) 7%, transparent); } }
      .workflow-actions { display: flex; flex-wrap: wrap; gap: 9px; }
      .success-card { display: flex; align-items: center; gap: 17px; border-color: #a8d8c0; background: linear-gradient(135deg, var(--card-background-color, #fff), #eef9f3); }
      .success-card h2, .success-card p { margin-bottom: 4px; }
      .success-icon { display: grid; flex: 0 0 52px; height: 52px; place-items: center; border-radius: 50%; color: #fff; background: #3d9369; font-size: 27px; font-weight: 800; }
      .empty { padding-block: 60px; text-align: center; }
      .empty p { max-width: 500px; margin: 0 auto; color: var(--secondary-text-color, #65736c); }
      .empty-icon { margin-bottom: 12px; font-size: 42px; }
      .loader { width: 34px; height: 34px; margin: 0 auto 18px; border: 3px solid var(--divider-color, #dce3df); border-top-color: var(--primary-color, #397960); border-radius: 50%; animation: spin 1s linear infinite; }
      footer { padding: 10px; color: var(--secondary-text-color, #65736c); font-size: 12px; text-align: center; }
      @media (max-width: 600px) {
        main { padding-inline: 11px; }
        .card { border-radius: 18px; }
        .section-heading { align-items: flex-start; }
        .counts, .expires { white-space: normal; text-align: right; }
        .slot-grid { grid-template-columns: repeat(5, 1fr); max-height: 350px; gap: 6px; }
        .stepper { grid-template-columns: 1fr; gap: 12px; }
        .stepper li:first-child::after { display: none; }
        .verification-box { align-items: flex-start; }
        .workflow-actions .primary, .workflow-actions .secondary { flex: 1 1 100%; }
      }
      @media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation-duration: .01ms !important; animation-iteration-count: 1 !important; } }
    `;
  }
}

if (!customElements.get("nimly-manager-panel")) {
  customElements.define("nimly-manager-panel", NimlyManagerPanel);
}
