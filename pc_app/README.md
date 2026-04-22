# ESP32-S3 Digital Oscilloscope — PC Interface

Aplicación de escritorio escrita en Python (PyQt6 + PyQtGraph) que funciona como la interfaz gráfica (UI) para el firmware del osciloscopio digital basado en el ESP32-S3.

## 🚀 Arquitectura del Sistema

La aplicación sigue una arquitectura modular separando estrictamente la interfaz gráfica de la lógica de negocio y procesamiento de datos.

### 1. Núcleo (`core/`)
Encargado de la lógica de procesamiento, comunicación y cálculos pesados. Opera independientemente de la interfaz gráfica.

* **`serial_reader.py`**: Hilo secundario (`QThread`) dedicado a la lectura continua del puerto USB (CDC). Previene bloqueos en la UI y alimenta el flujo binario al parser.
* **`frame_parser.py`**: Máquina de estados que busca secuencias de sincronización (`0xAA, 0x55`), decodifica las tramas y valida la integridad de los datos mediante un algoritmo **CRC-8 (Dallas/Maxim)**.
* **`device_controller.py`**: Interfaz de comandos (`CMD_`) para controlar el ESP32. Envía instrucciones (Start, Stop, Timebase, Attenuation) y bloquea mediante `threading.Event` esperando los reconocimientos (`ACK` o `NAK`). Mantiene el estado de la configuración localmente (`OscConfig`).
* **`data_store.py`**: Almacén central (búfer circular) de las tramas decodificadas. Permite a los visualizadores acceder al historial para funciones de Persistencia, Promedios (Average) y Envolventes (Envelope).
* **`measurements_engine.py`**: Motor de mediciones en background. Calcula Vpp, Vmax, Vmin, Vrms, y Frecuencia usando NumPy y SciPy, emitiendo los resultados listos para pintar en la UI.
* **`fft_engine.py`**: Motor de análisis espectral usando la Transformada Rápida de Fourier Real (`rfft`) de SciPy. Aplica enventanado (Hanning/Hamming/Blackman) y calcula picos y THD.

### 2. Interfaz de Usuario (`ui/`)
Basada en `PyQt6` para controles estándar y dock widgets, y `PyQtGraph` para el renderizado de alto rendimiento de las gráficas aceleradas por OpenGL.

* **`main_window.py`**: Orquestador principal de UI. Aloja el loop de renderizado (`QTimer` a 30 FPS) para leer de `data_store` y pintar en los widgets, evitando abrumar el hilo principal de Qt con datos asíncronos.
* **`waveform_widget.py`**: Visualizador principal de onda (Modo YT). Incluye:
  * Grilla dinámica que recalcula las celdas manteniendo proporciones cuadradas (Aspect Ratio Aware).
  * Modo **Roll (Continuous)** para visualización de señales lentas o continuas (cinta infinita).
  * Integración con escalamiento futuro mediante Amplificador de Ganancia Programable (PGA).
  * Cursores draggables de medición para ΔT (tiempo) y ΔV (voltaje).
* **`controls_panel.py`**: Panel lateral de herramientas interactivo (Dock). Centraliza la conexión, configuración de trigger, escalas y switches de visualización.
* **Paneles modulares**: `channel_panel.py`, `trigger_panel.py`, `measurements_panel.py` para abstraer agrupaciones de configuraciones complejas.

### 3. Simulador (`test_simulated.py`)
Un entorno de pruebas sin hardware (`SimulatedSource`). Genera ondas sintéticas (senoidales, cuadradas) con ruido y offsets DC, permitiendo probar la UI completa (AC/DC coupling, trigger, Auto-scale, Roll Mode) sin requerir el ESP32-S3 conectado.

---

## 💻 Entorno y Ejecución

### Requisitos
* Python 3.11 o superior.
* Entorno virtual (`.venv`) configurado para evitar conflictos de paquetes a nivel de sistema operativo.

### Instalación
```bash
cd pc_app
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Ejecutar Modo Producción (Con ESP32)
```bash
source .venv/bin/activate
python3 main.py
```

### Ejecutar Simulador (Sin Hardware)
```bash
source .venv/bin/activate
python3 test_simulated.py
```

## 🎨 Temas (Theming)
El osciloscopio incluye un sistema dual de temas visuales cargado a través de Qt Style Sheets (QSS):
- **Keysight Dark** (`stylesheet.qss`): Tema oscuro profesional con acentos Cyan para reducir fatiga visual.
- **Light Theme** (`stylesheet_light.qss`): Versión clara para entornos de alta iluminación ambiental.

Se cambia en tiempo real desde el botón *Theme* en el Panel de Controles.
