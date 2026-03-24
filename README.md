# homeassistant-ev_auto_smart_charge

Home Assistant custom integration **EV Auto Smart Charge** (`homeassistant_ev_auto_smart_charge`) uses **hourly spot prices** from [Energi Data Service](https://github.com/MTrab/energidataservice) together with **two EV battery % sensors** (for example [Tesla Custom](https://github.com/alandtse/tesla) and [Volkswagen Connect](https://github.com/robinostlund/homeassistant-volkswagencarnet)) to estimate the **cheapest upcoming hours** and **approximate cost** to reach a target state of charge for both cars.

**Note:** Home Assistant integration domains cannot contain hyphens. This project’s GitHub name uses `homeassistant-ev_auto_smart_charge`; the folder under `custom_components` and the integration domain are `homeassistant_ev_auto_smart_charge`.

## Prerequisites

- Home Assistant (recent version with UI config flows).
- **Energi Data Service** installed and a **spot price sensor** that exposes `raw_today` and `raw_tomorrow` attributes.
- Two **numeric sensors** for **battery level in percent** (one per vehicle).

## Installation

### Install with HACS

1. Install [HACS](https://hacs.xyz/docs/setup/download/) if you do not already use it.
2. In Home Assistant, open **HACS → Integrations**.
3. Open the menu in the top-right corner (**⋮** or **⁝**) and choose **Custom repositories**.
4. In **Repository**, paste the URL of this GitHub repository (for example `https://github.com/mikkel/homeassistant-ev_auto_smart_charge`).  
   Set **Category** to **Integration**, then click **Add**.
5. Find **EV Auto Smart Charge** in the HACS integration list (or use search), open it, and click **Download** (pick the default branch or latest release if offered).
6. **Restart Home Assistant** (**Settings → System → Restart**). A reload is not enough the first time.

HACS can update the integration later from the same entry; after an upgrade, restart Home Assistant again if HACS prompts you to.

### Manual installation (without HACS)

On the machine where Home Assistant reads its config (Supervised, Container, OS, or Core):

1. Open your configuration directory (the folder that contains `configuration.yaml`).
2. If `custom_components` does not exist, create it.
3. Copy the entire `homeassistant_ev_auto_smart_charge` folder from this repository into `custom_components`, so you get:

   ```text
   <config>/
     configuration.yaml
     custom_components/
       homeassistant_ev_auto_smart_charge/
         __init__.py
         manifest.json
         const.py
         coordinator.py
         config_flow.py
         sensor.py
         strings.json
         translations/
           en.json
   ```

   Do **not** place the files loose inside `custom_components`; the domain folder must be `custom_components/homeassistant_ev_auto_smart_charge/`.

4. **Restart Home Assistant** (**Settings → System → Restart**).

### Add the integration (HACS or manual)

1. Go to **Settings → Devices & services**.
2. Click **Add integration**.
3. Search for **EV Auto Smart Charge** (or `homeassistant_ev_auto_smart_charge`).
4. Complete the form:
   - **Spot price sensor**: your Energi Data Service entity.
   - **EV 1 / EV 2 battery level**: the two % sensors.
   - **Battery capacities (kWh)** and **wallbox power (kW)** as appropriate for your setup.
   - **Target SOC (%)** for planning.

After setup, a **Charge plan** sensor appears on the device. Use **Configure** on the integration entry to change capacities, charger power, or target SOC without removing the integration.

### Migrating from the old `ha_charge` integration

If you previously used the `ha_charge` custom component: remove that integration and delete `custom_components/ha_charge/`, install this package, restart Home Assistant, then add **EV Auto Smart Charge** again. Entity IDs and the integration domain will change.

## Notes

- This integration **plans only**; it does not start or stop charging. Use automations if you want to act on the `cheapest_hours` attribute.
- The planner assumes a **single effective charging power** (one shared wallbox or one combined budget). Adjust **Wallbox power (kW)** to match how you charge both cars.

## Uninstall

Remove the integration under **Settings → Devices & services**. Then either remove **EV Auto Smart Charge** from **HACS → Integrations** (if you used HACS) or delete `custom_components/homeassistant_ev_auto_smart_charge/` manually, and restart Home Assistant.
