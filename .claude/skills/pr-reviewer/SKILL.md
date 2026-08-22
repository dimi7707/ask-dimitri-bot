---
name: pr-review
description: >
  Revisión automatizada de Pull Requests usando git diff. SIEMPRE usa esta skill cuando el usuario pida revisar un PR, un branch, o diga frases como "revisa el PR", "review this PR", "revisa el branch", "revisa los cambios entre main y CORE-XXXX", "haz un code review de", o pase dos branches separados por ".." o "...". No esperes a que el usuario diga explícitamente "usa el skill" — si hay dos branches involucrados y se pide revisión de código, esta skill aplica.
---

# PR Review Skill

Skill para revisar Pull Requests automáticamente usando `git diff` y los 8 principios de calidad de código.

---

## Activación

El usuario invocará este skill con frases como:
- `"Revisa el PR main...CORE-8678"`
- `"Review this PR: develop...feature/login"`
- `"Revisa los cambios entre main y CORE-8678"`

**Parámetros esperados:**
- `base_branch` — rama base (ej. `main`, `develop`)
- `feature_branch` — rama a revisar (ej. `CORE-8678`, `feature/login`)

Si el usuario no especifica uno de los dos, pregúntale antes de continuar.

---

## Flujo de ejecución

### Paso 1 — Obtener archivos cambiados

```bash
git diff <base_branch>...<feature_branch> --name-only
```

Si el comando falla (rama no existe, no es un repo git, etc.), reporta el error claramente y detente.

Si no hay archivos cambiados, responde:
```
ℹ️ No se encontraron diferencias entre `<base>` y `<feature>`.
```

### Paso 2 — Obtener el diff por archivo

Para cada archivo de la lista:
```bash
git diff <base_branch>...<feature_branch> -- <filepath>
```

Procesa los archivos de a uno. No muestres el diff crudo al usuario.

### Paso 3 — Analizar cada archivo

Para cada archivo, aplica los **8 principios de calidad** definidos más abajo.

Detecta el lenguaje por extensión y aplica criterios adicionales según corresponda — ver sección **Criterios por lenguaje**.

Solo reporta problemas reales. Si un archivo no tiene issues, indícalo con `✅ Sin problemas.`

### Paso 4 — Mostrar resultados

Usa el formato de reporte definido más abajo.

### Paso 5 — Generar archivo Markdown

Al finalizar, guarda el reporte en la carpeta `pr-reviews/` dentro de la raíz del repositorio.

```bash
# Crear la carpeta si no existe
mkdir -p pr-reviews
```

El archivo se nombra con el nombre de la feature branch, sanitizado para ser válido como nombre de archivo (reemplaza `/` y caracteres especiales por `-`):

```
pr-reviews/<feature_branch>.md

# Ejemplos:
pr-reviews/CORE-8678.md
pr-reviews/feature-login.md        ← feature/login → feature-login
pr-reviews/fix-auth-token.md       ← fix/auth-token → fix-auth-token
```

Si ya existe un archivo con ese nombre, sobreescríbelo — siempre refleja el review más reciente.

Presenta el archivo al usuario para descargar al finalizar.

---

## Formato de reporte

```
🔍 PR REVIEW: `<base>...<feature>`
📂 Archivos revisados: N

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📄 <nombre_archivo>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[ÍCONO] [PRINCIPIO AFECTADO]
─────────────────────────────
Problema: [Descripción clara de qué está mal]

❌ Código actual:
[fragmento problemático]

✅ Cómo debería ser:
[fragmento corregido]

💡 Por qué: [explicación breve]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 RESUMEN FINAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Problemas encontrados: N
  🔴 Críticos:    X
  🟠 Importantes: X
  🟡 Menores:     X

Prioridad de corrección:
1. [problema crítico más urgente]
2. [siguiente]
...

Veredicto: [LISTO PARA MERGE / NECESITA CAMBIOS / BLOQUEADO]
```

Si un archivo no tiene problemas:
```
📄 <nombre_archivo>
✅ Sin problemas encontrados.
```

---

## Los 8 Principios de Calidad

### 1. 🧩 Diseño de Funciones (SRP)
Cada función debe hacer una sola cosa y hacerla bien.

**Red flags:**
- Nombres vagos: `process()`, `handle()`, `do()`
- Funciones > 30 líneas mezclando concerns
- Lógica anidada > 3 niveles
- Más de 4 parámetros sin agrupar en objeto

### 2. 🔢 Eliminar Hardcoding
Ningún magic string o magic number disperso en el código.

**Red flags:**
- URLs, rutas, formatos de fecha hardcodeados
- Números sin nombre: timeouts, límites, multiplicadores
- Credenciales o secrets en código
- Valores de entorno embebidos directamente

### 3. ♻️ DRY (Don't Repeat Yourself)
Si la misma lógica aparece dos o más veces, debe extraerse.

**Red flags:**
- Mismo bloque condicional en 3+ lugares
- Loops idénticos con distinto nombre de variable
- Validación duplicada en múltiples servicios
- Copy-paste con cambios mínimos

### 4. 📝 Documentación y Claridad
El código debe comunicar su intención. La lógica compleja necesita comentarios explicando el *por qué*, no el *qué*.

**Red flags:**
- Variables de una letra en lógica compleja
- Funciones públicas/APIs sin docstring
- Comentarios desactualizados que contradicen el código
- Lógica de negocio sin contexto

### 5. 🚨 Manejo de Errores y Logging
Los fallos deben anticiparse, capturarse y comunicarse con contexto suficiente para diagnosticar.

**Red flags:**
- `catch` vacío (falla silenciosa)
- Mensajes genéricos: `"Error occurred"`
- No distinción entre errores transitorios y permanentes
- Logs sin contexto (sin URL, sin ID, sin código de error)

### 6. 🔒 Seguridad y Validación de Inputs
Todo input externo debe validarse. Nunca confiar en datos del cliente.

**Red flags:**
- Inputs sin validación de tipo, longitud o formato
- Interpolación directa en queries SQL
- HTML renderizado sin escapar
- Credentials o API keys logueados
- Operaciones destructivas sin autenticación/autorización

### 7. ⚡ Performance y Optimización
Eliminar cuellos de botella evidentes antes de que lleguen a producción.

**Red flags:**
- Queries dentro de loops (problema N+1)
- Recalcular valores costosos en cada iteración
- I/O sincrónico bloqueando el hilo principal
- Event listeners que nunca se limpian
- Recursión sin límite de profundidad

### 8. 🧪 Cobertura de Tests
Los caminos críticos y casos borde deben estar cubiertos.

**Red flags:**
- Lógica de negocio crítica sin ningún test
- Tests que no cubren casos borde (null, 0, strings vacíos, listas vacías)
- Tests que dependen del orden de ejecución
- Sin mocks para dependencias externas
- Tests con nombres vagos (`test1`, `shouldWork`)

---

## Niveles de Severidad

| Nivel | Cuándo usarlo |
|---|---|
| 🔴 **Crítico** | Seguridad, datos corruptos, fallas silenciosas, injection |
| 🟠 **Importante** | Performance N+1, DRY violado, manejo de errores faltante |
| 🟡 **Menor** | Claridad, documentación, nombres de variables |

---

## Criterios por lenguaje

Detecta el lenguaje por extensión del archivo y aplica criterios adicionales:

### Python (`.py`)
- Verificar manejo de excepciones específicas (no `except Exception` genérico)
- Tipado: funciones públicas deben tener type hints
- Recursos: usar `with` para archivos, conexiones, y context managers
- Async: verificar que no haya llamadas bloqueantes dentro de funciones `async`
- Verificar que no se usen prints en lugar de logging en código de producción

### TypeScript (`.ts`, `.tsx`)
- Prohibido el uso de `any` — debe tipars correctamente
- Props de componentes React deben tener interfaces definidas
- Verificar null safety: accesos a propiedades opcionales sin `?.`
- Funciones async deben tener tipo de retorno explícito (`Promise<T>`)
- Enums o constantes en lugar de strings literales repetidos

### JavaScript (`.js`, `.jsx`)
- Verificar manejo de promesas: no mezclar `.then()` con `async/await`
- `var` debe reemplazarse por `const` o `let`
- Callbacks anidados (callback hell) deben refactorizarse
- Verificar que errores en promesas siempre tengan `.catch()` o `try/catch`
- Funciones flecha vs funciones nombradas: consistencia dentro del archivo

### PHP (`.php`)
- Queries SQL deben usar prepared statements, nunca interpolación directa
- Inputs de `$_GET`, `$_POST`, `$_REQUEST` deben sanitizarse siempre
- Verificar uso de `isset()` antes de acceder a variables de array
- Errores no deben exponerse al usuario (`display_errors` en producción)
- Verificar que contraseñas usen `password_hash()` / `password_verify()`

## Criterios por framework

Además de la extensión del archivo, detecta el framework por contexto (imports, decoradores, estructura de archivos) y aplica criterios adicionales:

### Angular (`.ts` con imports de `@angular/core`, decoradores `@Component`, `@Injectable`, etc.)
- Servicios deben inyectarse via constructor, nunca instanciarse con `new`
- Componentes no deben contener lógica de negocio — delegarla a servicios
- Subscripciones a Observables deben desuscribirse en `ngOnDestroy` o usar `takeUntilDestroyed` / `async pipe`
- Usar `OnPush` change detection cuando el componente trabaja con datos inmutables
- Evitar lógica en templates — moverla al componente o a pipes
- Módulos lazy-loaded para rutas que no son críticas al arranque

### React (`.tsx`, `.jsx` con imports de `react`)
- Hooks solo en el top level del componente — nunca dentro de condicionales o loops
- Efectos secundarios deben tener cleanup function en `useEffect` cuando corresponda
- Evitar re-renders innecesarios: verificar uso correcto de `useMemo`, `useCallback`, `React.memo`
- Props drilling profundo (3+ niveles) debe reemplazarse por Context o state management
- Keys en listas deben ser únicas y estables — nunca usar el índice del array como key
- Componentes > 150 líneas deben dividirse

### NestJS (`.ts` con imports de `@nestjs/common`, decoradores `@Controller`, `@Injectable`, `@Module`, etc.)
- Controllers deben ser delgados — solo recibir request y delegar al service
- Validación de inputs debe usar DTOs con `class-validator` decorators (`@IsString`, `@IsNotEmpty`, etc.)
- Nunca inyectar el `Repository` directamente en un Controller — siempre pasar por Service
- Excepciones deben usar las clases de NestJS (`NotFoundException`, `BadRequestException`, etc.) — no `throw new Error()`
- Guards, Interceptors y Pipes deben preferirse sobre lógica de autorización/transformación inline
- Módulos deben ser cohesivos — evitar un `AppModule` monolítico con todo importado

---

## Notas de comportamiento

- **No muestres el diff crudo** al usuario en ningún momento
- **Solo reporta problemas reales** — no inventes issues para parecer más exhaustivo
- **Sé específico**: menciona el nombre del archivo y, si es posible, la función o línea aproximada
- **El reporte debe estar en inglés** — los comentarios de PR son para el equipo y deben ser en inglés
- Si el PR tiene más de 20 archivos, avisa al usuario que el review puede tomar unos momentos
