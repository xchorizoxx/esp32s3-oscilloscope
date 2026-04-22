# Preguntas Abiertas — Decisiones Pendientes del Usuario

## Q1: Envio automatico de frames MEASUREMENTS por el firmware

**Contexto**: El protocolo define frames MEASUREMENTS (0x02) con 45 bytes por canal. El parser los interpreta correctamente. `configuration.md` menciona `measurements_enabled = true` por defecto. Sin embargo, no esta claro si el firmware envia estos frames automaticamente durante el stream continuo, o solo bajo demanda via `CMD_GET_STATUS`.

**Impacto**: Si el firmware NO envia frames MEASUREMENTS automaticamente, el `MeasurementsEngine` local (ahora conectado) cubre el caso. Si SI los envia, habra duplicacion de trabajo (firmware + PC calculando lo mismo).

**Opciones**:
1. **Mantener ambos**: El `MeasurementsEngine` local siempre calcula, y si llegan frames del firmware se muestran tambien (el ultimo en llegar gana). Simple pero redundante.
2. **Preferir firmware**: Si llega un frame MEASUREMENTS, usar esos valores y omitir el calculo local. Mas eficiente pero depende del firmware.
3. **Configurar via UI**: Agregar un checkbox "Use hardware measurements" para que el usuario decida. Mas flexible pero requiere cambio UI.

**Recomendacion**: Opcion 2 (preferir firmware, fallback a local).

---

## Q2: Persistencia de configuracion AC coupling entre sesiones

**Contexto**: El AC coupling es ahora puramente software en la PC (filtro IIR). El firmware no lo soporta, por lo que no se guarda en NVS. Al reconectar, la UI podria no recordar que un canal estaba en AC.

**Impacto**: El usuario tendria que volver a seleccionar AC tras cada reconexion.

**Opciones**:
1. **Guardar en QSettings** (AppSettings ya existe): Persistir estado de coupling en disco. Restaurar al iniciar la app.
2. **Sincronizar como parte del estado del device**: Cuando se conecta, leer del firmware (no aplica — firmware no lo soporta).
3. **No persistir**: El usuario debe reconfigurar cada vez. Comportamiento actual.

**Recomendacion**: Opcion 1 (guardar en QSettings, minimo esfuerzo, maxima UX).

---

## Q3: Comportamiento del modo Roll cuando ui_hold esta activo

**Contexto**: El modo Roll acumula datos en buffers internos y desplaza la vista. Cuando `ui_hold=True`, los datos nuevos no se renderizan, pero los buffers de roll siguen acumulando en segundo plano.

**Impacto**: Al salir de hold, la onda "salta" porque los buffers contienen datos que nunca se mostraron.

**Opciones**:
1. **Pausar acumulacion**: Cuando ui_hold=True, NO acumular en los buffers de roll. Al reanudar, continuar desde donde se pauso. Congelamiento coherente.
2. **Seguir acumulando**: Los datos se acumulan en background pero no se muestran. Al reanudar, se ve un salto temporal. Similar a un osciloscopio real con memoria profunda.
3. **Resetear buffers**: Al reanudar, empezar buffers desde cero. Pierde continuidad pero es limpio.

**Recomendacion**: Opcion 1 (pausar acumulacion) para un comportamiento de "pausa" coherente con lo que el usuario espera.

---

## Q4: Validacion de sample rate basada en capabilities del firmware

**Contexto**: `DeviceController` valida que el sample rate este entre 611-160000 Hz (limites globales del ESP32-S3). Pero el firmware podria reportar un `max_rate_hz` menor via INFO frame (ej: 83333 sin CLOCK_HACK).

**Impacto**: La UI permite seleccionar 160 kHz incluso si el firmware no soporta CLOCK_HACK, resultando en NAK.

**Opciones**:
1. **Validar contra INFO frame**: Despues de conectar, limitar el combo de rates a `max_rate_hz` reportado. Requiere poblacion dinamica del combo.
2. **Validar global (actual)**: Mantener 611-160000 como rango fijo. Si el firmware rechaza un valor, mostrar el NAK. Mas simple.
3. **Intentar y adaptar**: Si CMD_SET_RATE devuelve NAK, probar con el rate inmediatamente inferior valido.

**Recomendacion**: Opcion 1 para una UX profesional, opcion 2 si se prefiere simplicidad.
