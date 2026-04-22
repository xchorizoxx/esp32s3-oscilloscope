"""
app_settings.py — Persistencia de la configuración de la UI.
"""

from PyQt6.QtCore import QSettings

class AppSettings:
    """Wrapper para QSettings que guarda y carga la configuración de la app."""

    def __init__(self, org_name="OscilloscopeTeam", app_name="ESPOscilloscope") -> None:
        self.settings = QSettings(org_name, app_name)

    def save(self, key: str, value: any) -> None:
        self.settings.setValue(key, value)

    def load(self, key: str, default: any = None, type_hint=None) -> any:
        if type_hint is not None:
            return self.settings.value(key, default, type=type_hint)
        return self.settings.value(key, default)

    def save_dict(self, group: str, data: dict) -> None:
        self.settings.beginGroup(group)
        for k, v in data.items():
            self.settings.setValue(k, v)
        self.settings.endGroup()

    def load_dict(self, group: str, defaults: dict) -> dict:
        result = {}
        self.settings.beginGroup(group)
        for k, default_val in defaults.items():
            t = type(default_val)
            if t == bool:
                # QSettings devuelve string 'true'/'false' en algunos OS
                val = self.settings.value(k, default_val)
                if isinstance(val, str):
                    result[k] = val.lower() == 'true'
                else:
                    result[k] = bool(val)
            elif t == int:
                result[k] = int(self.settings.value(k, default_val))
            elif t == float:
                result[k] = float(self.settings.value(k, default_val))
            else:
                result[k] = self.settings.value(k, default_val)
        self.settings.endGroup()
        return result
