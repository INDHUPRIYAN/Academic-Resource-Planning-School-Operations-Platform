/**
 * DynamicUIEngine — Singleton that adapts every page to the school's configuration.
 * 
 * Usage:
 *   1. Add `data-requires-module="leaves"` to any HTML element that should be hidden
 *      when the "leaves" module is disabled.
 *   2. Call `DynamicUI.init()` on page load (after auth). It fetches the school
 *      config once, then hides/shows elements accordingly.
 */
const DynamicUI = (() => {
  let _config = null;
  let _enabledModules = [];
  let _initialized = false;

  async function init() {
    if (_initialized) return;
    _initialized = true;

    try {
      const me = await apiRequest("/auth/me");
      let schoolId = me.school_id;

      if (me.role === "super_admin") {
        const stored = localStorage.getItem("active_school_id");
        if (stored) {
          schoolId = parseInt(stored);
        } else {
          try {
            const schools = (await apiRequest("/schools?limit=1")).items;
            if (schools.length) schoolId = schools[0].id;
          } catch (e) {}
        }
      }

      if (schoolId) {
        const cfgWrapper = await apiRequest(`/schools/${schoolId}/config`);
        _config = JSON.parse(cfgWrapper.config);
        _enabledModules = _config.enabled_modules || ["timetables", "leaves", "swaps", "exams", "reports"];
      }
    } catch (e) {
      console.warn("DynamicUI: failed to load config", e);
      _enabledModules = ["timetables", "leaves", "swaps", "exams", "reports"];
    }

    applyAll();
  }

  function isModuleEnabled(moduleName) {
    return _enabledModules.includes(moduleName);
  }

  function getConfig() {
    return _config || {};
  }

  function applyAll() {
    hideDisabledElements();
    filterSelectOptions();
  }

  /**
   * Hide any element with `data-requires-module="X"` where X is not enabled.
   */
  function hideDisabledElements() {
    document.querySelectorAll("[data-requires-module]").forEach(el => {
      const mod = el.getAttribute("data-requires-module");
      if (!isModuleEnabled(mod)) {
        el.style.display = "none";
      } else {
        // Restore if was hidden and is now re-enabled
        if (el.style.display === "none") {
          el.style.display = "";
        }
      }
    });
  }

  /**
   * Remove <option> elements inside <select> that require disabled modules.
   */
  function filterSelectOptions() {
    document.querySelectorAll("select option[data-requires-module]").forEach(opt => {
      const mod = opt.getAttribute("data-requires-module");
      if (!isModuleEnabled(mod)) {
        opt.remove();
      }
    });
  }

  /**
   * Check if resources are enabled in config.
   */
  function isResourcesEnabled() {
    if (!_config) return true;
    const res = _config.resources;
    if (typeof res === "object") return res.enabled !== false;
    return res !== false;
  }

  /**
   * Check if activities are enabled in config.
   */
  function isActivitiesEnabled() {
    if (!_config) return true;
    const act = _config.activities;
    if (typeof act === "object") return act.enabled !== false;
    return act !== false;
  }

  /**
   * Check if mediums are enabled in config.
   */
  function isMediumsEnabled() {
    if (!_config) return false;
    const med = _config.mediums;
    if (typeof med === "object") return med.enabled === true;
    return false;
  }

  return {
    init,
    isModuleEnabled,
    isResourcesEnabled,
    isActivitiesEnabled,
    isMediumsEnabled,
    getConfig,
    applyAll,
    hideDisabledElements,
    filterSelectOptions,
    hideDisabledFields: hideDisabledElements,
    hideDisabledCards: hideDisabledElements,
    filterReportOptions: filterSelectOptions,
    applyDynamicValidation: () => true
  };
})();
