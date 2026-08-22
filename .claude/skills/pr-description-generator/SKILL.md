---
name: pr-description-generator
description: "Genera descripciones de Pull Requests en formato markdown profesional en inglés. SOLO se activa cuando el usuario lo invoca EXPLÍCITAMENTE — nunca de forma automática. Úsala cuando el usuario pida generar, escribir o mejorar una descripción de PR ('generate PR description', 'write my PR description', 'genera la descripción del PR', 'crea el PR description'). Acepta cualquier tipo de input: texto en español, fragmentos de código, diffs, documentación SDD (spec.md, design.md, proposal.md, tasks.md, .openspec.yaml), o una mezcla. Omite secciones cuando no hay información suficiente para completarlas honestamente. Output siempre en inglés, máximo ~100 líneas."
---

# PR Description Generator

Skill para generar descripciones de Pull Requests en markdown profesional. Output siempre en inglés. Longitud controlada (~100 líneas). Nunca inventa información — omite secciones cuando no hay datos suficientes.

**IMPORTANTE: Solo se activa cuando la invocas explícitamente.**

---

## Input aceptado

Esta skill se adapta a lo que llegue:
- Descripción en español → traduce y estructura
- Fragmentos de código o diff → interpreta y resume
- Notas sueltas o bullet points → organiza y expande
- **Documentación SDD** (ver sección abajo) → extrae la información de cada archivo
- Mix de todo lo anterior → procesa todo junto

Si el input es ambiguo o incompleto, hacer **máximo 1-2 preguntas** para aclarar lo esencial antes de generar.

---

## Soporte para Documentación SDD

Cuando el usuario provea documentación generada por un flujo **SDD (Spec-Driven Development)**, leer cada archivo disponible y extraer la información relevante para armar la descripción del PR. El output final mantiene exactamente la misma estructura de siempre.

### Archivos SDD y qué extraer de cada uno

| Archivo | Qué buscar |
|---|---|
| `proposal.md` | Contexto del problema, motivación del cambio, objetivo del PR → usar para **Problem** y parte del **Approach** |
| `spec.md` | Requisitos funcionales, comportamiento esperado, casos de uso → usar para **Solution** y **Result** |
| `design.md` | Decisiones técnicas, arquitectura, componentes afectados → usar para **Technical Details** y **Root Cause** si aplica |
| `tasks.md` | Lista de tareas implementadas → usar para reforzar **Solution** y confirmar el alcance del PR |
| `.openspec.yaml` | Cambios de API (endpoints, schemas, contratos) → mencionar en **Technical Details** si hay cambios de interfaz |

### Reglas para documentación SDD

- **Leer todos los archivos disponibles** antes de generar. No asumir que falta información si no se leyó el archivo.
- Si hay **contradicción** entre archivos (ej. proposal dice X pero design dice Y), preferir `design.md` para decisiones técnicas y `spec.md` para comportamiento.
- Si algún archivo **no está presente**, simplemente ignorarlo sin mencionarlo.
- Los archivos SDD pueden estar en cualquier ruta. Si el usuario da una ruta o referencia a una carpeta con estos archivos, leerlos todos con `view` antes de generar.
- El ticket de JIRA puede aparecer en cualquiera de estos archivos (usualmente en `proposal.md` o `spec.md`) — extraerlo si está disponible.
- La información de testing (pasos, datos requeridos) puede estar en `spec.md` o `tasks.md`.

---

## Estructura del Output

Generar solo las secciones para las que hay información real. **Omitir sin mencionar** las secciones vacías.

```markdown
## Approach

**[Tipo]: [Título descriptivo del cambio]**

* JIRA ticket: [número si fue provisto, si no omitir línea]

## Problem

* [Bullet points describiendo el problema o contexto]

## Root Cause

* [Bullet points con la causa raíz, solo si fue explicada]

## Solution

* [Bullet points con lo que se implementó]

## Technical Details

* [Bullet points con detalles técnicos relevantes]

## Result

* [Bullet points con el resultado/impacto esperado]

## Testing

### Steps to Test

1. [Pasos concretos, solo si fueron provistos]

### Expected Behavior

* [Comportamiento esperado, solo si fue descrito]

### Data Required

* [Datos de prueba necesarios, solo si aplica]

## Peer Review Questions

- [x] The code does what it is supposed to do per the JIRA
- [x] The code is formatted according to our standards
- [x] The method and variable names make sense and they are as self explanatory as possible
- [x] As far as I'm aware this is the most efficient way to write this code. I have checked new queries use the ORM when possible
- [x] This code has error handling and logging as appropriate
- [x] The critical portions of the functionality are tested per unit testing standards
- [x] This code follows the "defensive coding" standards
- [x] I have added comments for any questions I have about the code
```

> La sección **Peer Review Questions** se incluye siempre — es un checklist fijo.

---

## Reglas de Calidad

**Longitud**: Apuntar a ~80-100 líneas de markdown total. Si hay mucho detalle, priorizar claridad sobre exhaustividad.

**Tono**: Profesional, técnico, directo. Verbos en pasado para lo completado, presente para comportamiento esperado.

**Tipos de PR comunes para el Approach**:
- `Fix:` — corrección de bug
- `Feature:` — nueva funcionalidad
- `Refactor:` — mejora de código sin cambio de comportamiento
- `Chore:` — tareas de mantenimiento, dependencias, config
- `Hotfix:` — corrección urgente en producción

**No inventar**:
- Números de ticket JIRA → omitir la línea si no se proveyó
- Pasos de testing → omitir la sección si no se describieron
- Módulos afectados → solo mencionar los que fueron nombrados
- Detalles técnicos → solo los que se pueden inferir del contexto dado

---

## Cómo Invocar Esta Skill

Solo responde con este flujo cuando el usuario pida **explícitamente** generar una descripción de PR:

- "Generate PR description"
- "Write my PR description"
- "Genera la descripción del PR"
- "Crea el PR description"
- "Escribe el PR para este cambio"
- "PR desc for this fix"
- "Genera el PR a partir del spec / del SDD / de la documentación"

**No activar** si el usuario simplemente describe un cambio de código sin pedir la descripción del PR.