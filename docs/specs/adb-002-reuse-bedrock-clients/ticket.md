> Preserved verbatim as received. This ticket was pasted rather than filed in a
> tracker, so this file is its system of record. Nothing below has been edited,
> corrected, or re-scoped — corrections live in `spec.md` and `plan.md`.

---

id: adb-002
titulo: Los clientes de Bedrock se reconstruyen en cada request
tipo: bug
prioridad: crítica
severidad: bloqueante para producción
tamaño: S
estimado: ~30 min
estado: abierto
componente: embeddings / generation
proyecto: Ask Dimitri Bot
reportado: 2026-09-19
commit detectado: eb18bb9
relacionados: adb-001

---

# adb-002 · Los clientes de Bedrock se reconstruyen en cada request

| Campo | Valor |
|---|---|
| **Prioridad** | 🔴 Crítica |
| **Severidad** | Bloqueante para producción |
| **Tamaño** | S (~30 min) |
| **Estado** | Abierto |
| **Componente** | `app/api/deps.py`, `app/integrations/embeddings/`, `app/integrations/generation/` |
| **Impacto principal** | Latencia y cold start, no agotamiento de recursos |
| **Relacionado** | [[adb-001]] — misma causa raíz, mismo arreglo |

---

## Resumen

El cliente de boto3 para Bedrock y el objeto `ChatBedrock` de LangChain se construyen **en cada
request**. Construir un cliente boto3 es caro (parsea el modelo del servicio, resuelve
credenciales), y ese costo se paga hoy una vez por pregunta en vez de una vez por contenedor.

Hay un agravante irónico: el código **ya tiene una caché diseñada para evitar esto**, y esa caché
nunca llega a servir.

## El problema

Las dos factories construyen una instancia nueva en cada llamada:

```python
# app/integrations/embeddings/factory.py:7-14
def _build_bedrock_provider() -> EmbeddingProvider:
    from app.integrations.embeddings.bedrock_provider import BedrockEmbeddingProvider
    settings = get_settings()
    return BedrockEmbeddingProvider(model_id=..., region=...)
    #      └── su __init__ hace boto3.client("bedrock-runtime", ...)
```

```python
# app/integrations/generation/factory.py:7-14  →  mismo patrón con BedrockGenerationProvider
```

Y como en [[adb-001]], `app/api/deps.py:20` y `:28` son dependencias de FastAPI sin caché, que se
ejecutan una vez por request.

### La caché que no sirve

`app/integrations/generation/bedrock_provider.py:22-30` tiene esto:

```python
def _get_chat_model(self):
    """Build the Bedrock client on first use, then reuse it.

    Constructing ChatBedrock resolves AWS credentials, which blocks for ~90s on a machine
    that has none — doing it in __init__ would make simply resolving the provider hang.
    """
    if self._chat_model is None:
        self._chat_model = ChatBedrock(model=self._model_id, region=self._region)
    return self._chat_model
```

Es una caché *lazy* correcta y deliberada — el commit `eb18bb9` la introdujo justamente para
evitar un cuelgue de ~90 s. Pero **solo cachea dentro de una instancia**, y la instancia entera se
descarta al terminar el request.

Resultado: el comentario dice "then reuse it", y en la práctica nunca se reutiliza entre
preguntas. El commit arregló el síntoma (el cuelgue al resolver el provider) pero no la causa (la
instancia es efímera).

> Dentro de un mismo request sí se reutiliza: `classify_scope` y `generate_answer` comparten la
> misma instancia, así que `ChatBedrock` se construye una vez por request, no dos.

### Evidencia

```bash
uv run python -c "
from app.integrations.storage.factory import get_storage_provider as s
print('misma instancia?', s() is s())
"
```

```
misma instancia? False
```

(El mismo comportamiento aplica a las factories de embeddings y generation, que siguen el patrón
idéntico.)

## Impacto

| Dónde | Costo |
|---|---|
| Cada request | Construcción de un cliente boto3 + resolución de credenciales + construcción de `ChatBedrock` |
| Cold start de Lambda | Se suma al arranque ya pesado de LlamaIndex + LangChain |
| Máquina sin credenciales | El cuelgue de ~90 s que `eb18bb9` intentó resolver puede reaparecer en cada request en lugar de una sola vez |

A diferencia de [[adb-001]], esto **no agota un recurso compartido** — no tumba el servicio. Es
latencia y desperdicio puro. Pero en un endpoint que ya hace hasta 3 llamadas a Bedrock por
pregunta, cada milisegundo de overhead evitable cuenta.

## Qué hay que hacer

Mismo arreglo que [[adb-001]], sobre las otras dos dependencias de `app/api/deps.py`:

```python
from functools import lru_cache

@lru_cache
def get_embedder() -> EmbeddingProvider:
    return get_embedding_provider()

@lru_cache
def get_generator() -> GenerationProvider:
    return get_generation_provider()
```

Con eso la caché lazy de `_get_chat_model()` **pasa a cumplir su propósito real**: pagar la
construcción de `ChatBedrock` una vez por contenedor de Lambda, no una vez por pregunta. No hace
falta tocar `bedrock_provider.py`.

> ⚠️ Mismo aviso que en [[adb-001]]: `@lru_cache` va en `deps.py`, **no** en las factories.
> `Settings` de Pydantic no es hasheable y rompería los tests que invocan
> `get_generation_provider(settings=...)`.

**Opcional pero recomendado en el mismo cambio** — configurar timeouts explícitos en el cliente de
embeddings, ya que se va a tocar ese constructor de todos modos:

```python
from botocore.config import Config

boto3.client(
    "bedrock-runtime",
    region_name=region,
    config=Config(connect_timeout=5, read_timeout=25, retries={"mode": "standard"}),
)
```

Sin esto, un Bedrock lento se come los 30 s de timeout de la Lambda entera. Si se prefiere
mantener el ticket mínimo, esto puede salir a un ticket propio junto con el resto del hallazgo A1.

## Criterios de aceptación

- [ ] Dos llamadas consecutivas a `get_embedder()` devuelven la misma instancia.
- [ ] Dos llamadas consecutivas a `get_generator()` devuelven la misma instancia.
- [ ] Dos requests consecutivos a `POST /chat` reutilizan el mismo objeto `ChatBedrock`
      (verificable por identidad sobre `provider._chat_model`).
- [ ] El comentario de `_get_chat_model()` sigue siendo cierto: la construcción se paga **una vez
      por proceso**, no una vez por request.
- [ ] Los tests existentes de `tests/integrations/embeddings/test_factory.py` y
      `tests/integrations/generation/test_factory.py` pasan sin modificarse.
- [ ] `app.dependency_overrides` sigue funcionando en los tests de `/chat`: los fakes se inyectan
      correctamente pese a la caché.
- [ ] Suite completo verde.

## Notas

- **adb-001 y adb-002 comparten causa raíz** (dependencias de FastAPI sin caché entre requests) y
  se arreglan en el mismo archivo. Se mantienen como tickets separados porque el impacto es
  distinto: adb-001 agota conexiones y **tumba el servicio**; adb-002 solo desperdicia latencia.
  Si se resuelven juntos, cerrar ambos verificando los criterios de cada uno por separado.
- Al cachear el generador, revisar que el fallback de `classify_scope` siga comportándose igual —
  no debería cambiar nada, pero es el camino que más depende del provider.

## Fuera de alcance

- Normalizar `message.content` cuando no es un string (hallazgo M1, ticket aparte).
- Manejo de errores de Bedrock: `ThrottlingException`, `AccessDeniedException` (hallazgo A1).

---

Contexto completo del hallazgo en [[Análisis de calidad]] (B2).
