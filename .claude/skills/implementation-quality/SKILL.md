---
name: implementation-quality
description: "Skill de revisión de calidad de código y TDD. SOLO se activa cuando el usuario la invoca EXPLÍCITAMENTE — nunca de forma automática. Úsala cuando el usuario pida revisar, mejorar o auditar código ('review this code', 'check quality', 'refactor this', 'is this code good?', 'revisa este código'). También se activa para crear o modificar features → aplicar flujo TDD. NO usar si el usuario solo pide ayuda para implementar algo sin solicitar revisión de calidad o TDD explícitamente. Cubre: diseño de funciones (SRP), hardcoding, DRY, documentación, manejo de errores, seguridad, performance y testing. Solo reporta problemas reales — omite principios donde el código ya está bien."
---

# Implementation Quality

Skill para revisar y mejorar implementaciones de código en cualquier lenguaje. Cubre dos modos de operación: **revisión de calidad** y **TDD**. Solo reporta problemas reales — si un principio ya está bien aplicado, se omite sin mencionarlo.

**IMPORTANTE: Solo se activa cuando la invocas explícitamente.** No se dispara automáticamente.

---

## Modos de Operación

Esta skill tiene dos modos. El modo se detecta por la intención del usuario:

| Modo | Cuándo activar |
|---|---|
| 🔍 **Code Review** | Usuario pide revisar, auditar o refactorizar código existente |
| 🧪 **TDD** | Usuario quiere crear una nueva feature o modificar código existente |

---

## Modo 1 — 🔍 Flujo de Revisión de Calidad

Cuando el usuario comparte código y pide revisión:

### 1. Escanear los 8 principios (internamente)

Evaluar el código contra cada principio. Solo proceder a reportar los que tengan problemas reales.

### 2. Respuesta: solo problemas encontrados

```
🔍 REVISIÓN DE CALIDAD

Problemas encontrados: [N]

─────────────────────────────
[ÍCONO] [PRINCIPIO AFECTADO]
─────────────────────────────
Problema: [Descripción clara de qué está mal]

❌ Tu código:
[fragmento problemático]

✅ Cómo debería ser:
[fragmento corregido]

💡 Por qué: [explicación breve de la regla o riesgo]
```

Si no hay problemas en ningún principio:
```
✅ El código está bien estructurado. No se encontraron problemas de calidad significativos.
```

### 3. Checklist de cierre (solo ítems con problemas)

Al final, un resumen compacto de qué corregir y en qué orden de prioridad (crítico → importante → menor).

---

## Los 8 Principios

### 1. 🧩 Diseño de Funciones (SRP)

Cada función debe hacer una sola cosa y hacerla bien.

**Red flags**:
- Funciones con nombres vagos: `process()`, `handle()`, `do()`
- Funciones > 30 líneas mezclando concerns (fetch + transform + log)
- Lógica anidada > 3 niveles
- Más de 4 parámetros sin agrupar en objeto

**Patrón**:
```
❌ function generateReport(data, filters, format) {
  // 50+ líneas: validar, consultar DB, transformar, formatear, manejar errores
}

✅ function validateReportInput(data) { ... }
   function fetchReportData(filters) { ... }
   function transformData(raw) { ... }
   function formatOutput(data, format) { ... }
   function generateReport(data, filters, format) { /* orquesta las anteriores */ }
```

---

### 2. 🔢 Eliminar Hardcoding

Ningún "magic string" o "magic number" debe estar disperso en el código.

**Red flags**:
- Strings repetidos: URLs, rutas, formatos de fecha, roles
- Números sin nombre: timeouts, límites, multiplicadores
- Credenciales o secrets en código
- Valores de entorno embebidos directamente

**Patrón**:
```
❌ const data = await fetch('https://api.example.com/users/' + id);
   setTimeout(() => retry(), 5000);
   if (items.length > 100) { ... }

✅ const API_USERS_ENDPOINT = `${process.env.API_BASE_URL}/users`;
   const RETRY_DELAY_MS = 5000;
   const MAX_ITEMS_PER_PAGE = 100;
```

---

### 3. ♻️ DRY (Don't Repeat Yourself)

Si la misma lógica aparece dos o más veces, debe extraerse.

**Red flags**:
- Mismo bloque condicional en 3+ lugares
- Loops idénticos con distinto nombre de variable
- Validación duplicada en múltiples servicios
- Copy-paste con cambios mínimos

**Patrón**:
```
❌ // En UserService, PostService y CommentService:
   if (entity.role !== 'admin' && entity.role !== 'moderator') return null;

✅ // En permissions.ts:
   const PRIVILEGED_ROLES = ['admin', 'moderator'];
   function isPrivileged(entity) {
     return PRIVILEGED_ROLES.includes(entity.role);
   }
```

---

### 4. 📝 Documentación y Claridad

El código debe comunicar su intención. La lógica compleja debe tener comentarios explicando el *por qué*, no el *qué*.

**Red flags**:
- Variables de una letra en lógica compleja (`x`, `tmp`, `data`)
- Funciones públicas/APIs sin docstring
- Comentarios desactualizados que contradicen el código
- Comentarios que explican lo obvio (`i++; // incrementa i`)
- Lógica de negocio sin contexto

**Patrón**:
```
❌ function calc(p, r, t) { return p * r * t; }

✅ /**
    * Calcula el interés simple.
    * @param {number} principal - Capital inicial
    * @param {number} rate - Tasa de interés anual (decimal, e.g. 0.05 = 5%)
    * @param {number} time - Tiempo en años
    * @returns {number} Interés generado
    */
   function calculateSimpleInterest(principal, rate, time) {
     return principal * rate * time;
   }
```

---

### 5. 🚨 Manejo de Errores y Logging

Los fallos deben anticiparse, capturarse y comunicarse con contexto suficiente para diagnosticar.

**Red flags**:
- `catch (e) {}` vacío (falla silenciosa)
- Mensajes genéricos: `"Error occurred"`
- No distinción entre errores transitorios (retry) y permanentes (throw)
- Recursos no liberados en finally
- Logs sin contexto (sin URL, sin ID, sin código de error)

**Patrón**:
```
❌ try {
     const data = await fetchAPI();
   } catch (e) {
     console.log('error');
   }

✅ try {
     const data = await fetchAPI();
   } catch (error) {
     if (error.code === 'ECONNREFUSED') {
       logger.warn(`API unreachable at ${API_URL}, retrying...`);
       return retryWithBackoff();
     }
     logger.error(`Unexpected error: ${error.message}`, { statusCode: error.statusCode });
     throw error;
   }
```

---

### 6. 🔒 Seguridad y Validación de Inputs

Todo input externo debe validarse. Nunca confiar en datos del cliente.

**Red flags**:
- Inputs de usuario sin validación de tipo, longitud o formato
- Interpolación directa en queries SQL (`"SELECT * WHERE id = " + id`)
- HTML renderizado sin escapar
- Credentials o API keys logueados
- Operaciones destructivas sin autenticación/autorización
- File uploads sin validación de tipo o tamaño

**Patrón**:
```
❌ db.query(`SELECT * FROM users WHERE id = ${req.params.id}`);

✅ const id = parseInt(req.params.id, 10);
   if (isNaN(id)) return res.status(400).json({ error: 'Invalid ID' });
   db.query('SELECT * FROM users WHERE id = ?', [id]);
```

---

### 7. ⚡ Performance y Optimización

Eliminar cuellos de botella evidentes antes de que lleguen a producción.

**Red flags**:
- Queries dentro de loops (problema N+1)
- Recalcular valores costosos en cada iteración
- I/O sincrónico bloqueando el hilo principal
- Event listeners que nunca se limpian
- Recursión sin límite de profundidad
- Objetos grandes copiados innecesariamente

**Patrón**:
```
❌ ids.map(id => db.query(`SELECT * FROM users WHERE id = ?`, id));
   // N queries para N usuarios

✅ db.query(`SELECT * FROM users WHERE id IN (?)`, [ids]);
   // 1 query con índice
```

---

### 8. 🧪 Cobertura de Tests

Los caminos críticos y casos borde deben estar cubiertos.

**Red flags**:
- Lógica de negocio crítica sin ningún test
- Tests que no cubren casos borde (null, 0, strings vacíos, listas vacías)
- Tests que dependen del orden de ejecución
- Sin mocks para dependencias externas (DB, APIs, sistema de archivos)
- Tests con nombres vagos (`test1`, `shouldWork`)

**Patrón**:
```
❌ // Sin tests para addTax()

✅ describe('addTax', () => {
     test('adds 10% to a positive price', () => expect(addTax(100)).toBe(110));
     test('handles zero price', () => expect(addTax(0)).toBe(0));
     test('throws on negative price', () => expect(() => addTax(-10)).toThrow());
     test('handles floating point precision', () => expect(addTax(19.99)).toBeCloseTo(21.989, 2));
   });
```

---

## Niveles de Severidad

Al reportar problemas, clasificar cada uno:

| Nivel | Cuándo usarlo |
|---|---|
| 🔴 **Crítico** | Seguridad, datos corruptos, fallas silenciosas, injection |
| 🟠 **Importante** | Performance N+1, DRY violado, manejo de errores faltante |
| 🟡 **Menor** | Claridad, documentación, nombres de variables |

---

## Modo 2 — 🧪 TDD (Test-Driven Development)

Activar siempre que el usuario quiera **crear una nueva feature** o **modificar código existente**.

### Flujo obligatorio Red → Green → Refactor

```
🧪 TDD FLOW

Feature: [nombre de la feature o cambio]

─────────────────────────────
🔴 RED — Escribe el test primero
─────────────────────────────
Antes de escribir una sola línea de implementación, define qué debe cumplir el código.

[test(s) que fallan porque la implementación aún no existe]

─────────────────────────────
🟢 GREEN — Implementación mínima
─────────────────────────────
Escribe solo el código necesario para que los tests pasen. Nada más.

[implementación mínima]

─────────────────────────────
🔵 REFACTOR — Mejora sin romper tests
─────────────────────────────
Ahora limpia: extrae funciones, elimina duplicación, mejora nombres.
Los tests deben seguir pasando.

[implementación refactorizada]
```

### Reglas TDD

- **Nunca escribir implementación sin test previo.** Si el usuario trae código sin tests, señalarlo y proponer los tests primero.
- **Un test a la vez.** No adelantar casos borde hasta que el caso básico pase.
- **El test define el contrato**, no al revés. Si el test es difícil de escribir, es señal de mal diseño.
- **Casos mínimos a cubrir siempre**: happy path, edge case (null/0/vacío), error path.

### Red flags en contexto TDD

- Implementación propuesta sin ningún test → 🔴 Crítico: detener y generar tests primero
- Tests escritos *después* de la implementación como afterthought → 🟠 Importante
- Tests que solo verifican el happy path → 🟡 Menor

---

## Cómo Invocar Esta Skill

### 🔍 Code Review
- "Review this code"
- "Check the quality of this"
- "Refactor this"
- "Is this code good?"
- "Revisa este código"
- "Qué problemas tiene este código"
- "Audit this implementation"

### 🧪 TDD
- "I want to build [feature] using TDD"
- "Help me add [feature] with tests first"
- "Let's do TDD for this"
- "Write tests before implementing"
- "Quiero implementar esto con TDD"

**No activar** si el usuario pide ayuda para implementar algo nuevo sin solicitar revisión de calidad o TDD explícitamente.