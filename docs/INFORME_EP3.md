# Informe de observabilidad y monitoreo — Evaluación Parcial 3

**Proyecto:** `ep2-rescate-agente` (ISY0101 — Ingeniería de Soluciones con IA)
**Fecha:** 16 de noviembre de 2026
**Fuente de datos:** `logs/trace-morado.jsonl`, `docs/salida-acto1.txt`, `docs/salida-acto2.txt`, `docs/plan-v2-evidencia.json`, `README.md` y `agents.md` de este repositorio.

## 1. Contexto y objetivo

El sistema es un coordinador de búsqueda y rescate andino que convierte el reporte de una persona desaparecida en un plan de búsqueda por fases y lo replanifica cuando el pronóstico invalida la ventana de un medio aéreo. La decisión es determinista y se calcula en Python (`tools/rastreo.py`, `agent/rastreo.py`); el LLM (Groq `openai/gpt-oss-120b`) solo redacta el parte narrativo. La orquestación es un grafo LangGraph de cinco nodos (`contexto → calcular → publicar → redactar → memorizar`).

Este informe aplica métricas de observabilidad al agente, analiza la trazabilidad disponible y propone mejoras de monitoreo. **Todas las cifras proceden de los artefactos citados arriba**; no se ejecutaron nuevas corridas ni se generaron datos sintéticos. La muestra es pequeña (una consulta y dos actos documentados), por lo que los valores son observaciones, no estimaciones estadísticas.

## 2. Métricas implementadas y aplicadas

| Métrica | Definición operativa | Valor observado | Evidencia |
|---|---|---|---|
| **Latencia** | Delta entre marcas de tiempo de los eventos de la traza de consulta | **76 s** de extremo a extremo (20:08:46 → 20:10:02 UTC): 73 s consulta→memoria, 0 s memoria→recuperación, 3 s recuperación→respuesta final | `logs/trace-morado.jsonl` |
| **Consistencia** | Proporción de planes con igual prioridad de zonas, igual número de fases e igual secuencia de traza | **2/2** planes con prioridad `Z-2 > Z-5 > Z-1 > Z-4 > Z-3` y 5 fases; **5/5** pasos de traza idénticos en ambos actos | `docs/salida-acto1.txt`, `docs/salida-acto2.txt`, `docs/plan-v2-evidencia.json` |
| **Precisión (conformidad al contrato)** | Fracción de pruebas del contrato determinista declaradas como superadas | **31/31 (100 %)**: 27 funcionales + 4 del arnés de métricas, verificado con `pytest -q` | `README.md` §Estado; `agents.md`; `tests/test_metricas.py` |
| **Frecuencia de errores** | Registros con evento de error / registros de traza disponibles | **0/14** registros (4 de consulta + 5 por acto); ningún evento de fallo, rechazo ni excepción | `logs/trace-morado.jsonl`, salidas de actos |
| **Uso de recursos** | Fragmentos recuperados, herramientas invocadas, memoria y almacenamiento | **5 fragmentos** (3 de `protocolo-busqueda`, 2 de `criterios-prioridad`), **3 herramientas**, buffer de **20 turnos**, **2 colecciones Chroma** (`conocimiento`, `memoria`), **6 citas** en el plan v2 | `logs/trace-morado.jsonl`, `README.md`, `docs/plan-v2-evidencia.json` |

*Nota de alcance.* La latencia reportada es tiempo transcurrido entre eventos de traza (reloj de pared) de una sola corrida con Groq real, no tiempo neto de inferencia. La precisión se define aquí como conformidad a un contrato determinista verificado por pruebas, no como exactitud frente a un corpus etiquetado: el propio informe EP2 señala que el parte narrativo no se evaluó con métricas de calidad (`scripts/gen_informe_pdf.py`).

## 3. Análisis de trazas y hallazgos

La traza de consulta registra cuatro eventos (`consulta`, `memoria`, `recuperacion`, `respuesta_final`); las trazas de los actos registran cinco (`planificacion`, `memoria_semantica`, `plan_publicado`, `parte_narrativo`, `memoria`). El modelo queda identificado en la respuesta final (`openai/gpt-oss-120b`) y en el parte narrativo de ambos actos.

1. **Cuello de botella temporal (IE3).** El tramo entre la consulta y el evento de memoria consume 73 de los 76 s observados (96 %). La traza no desagrega ese tramo, por lo que no es posible atribuirlo a carga de embeddings, recuperación o inferencia; es el candidato principal a optimizar.
2. **Redundancia en recuperación (IE4).** Los 5 fragmentos recuperados provienen de solo 2 fuentes, con 3 fragmentos repetidos de `protocolo-busqueda` y 2 de `criterios-prioridad`. La respuesta final citó una sola fuente (`plan-publicado`), lo que sugiere baja cobertura de citas respecto al contexto recuperado.
3. **Continuidad de memoria verificada (IE1).** Entre el acto 1 y el acto 2, `recuerdos` pasa de 0 a 1 y `cita_plan_previo` de `False` a `True`; el parte del acto 2 incorpora `memoria-semantica:caso-morado` y `memoria:caso-morado` entre sus fuentes. El mecanismo funciona según lo previsto.
4. **Adaptación sin deriva de invariantes (IE1/IE4).** El plan v2 sustituye los medios de Z-2 y Z-5 (HEL-1 queda fuera por viento de 41 y 38 km/h ≥ 35; DR-1 solo en Z-5 con 38 ≤ 40), pero conserva la prioridad de zonas, las 5 fases y la fase nocturna sin zonas técnicas. El cambio está explicado con la regla §3 citada, como exige el protocolo §4.
5. **Brechas de trazabilidad (IE3).** La evidencia de los actos indica `logs/trace.jsonl`, pero el archivo presente es `logs/trace-morado.jsonl`. Además, los eventos individuales no registran `latencia_ms`, `tokens` ni `error`; la latencia tuvo que derivarse de marcas de tiempo. `LangSmith` está implementado en `agent/observabilidad.py` pero permanece inactivo sin `LANGSMITH_API_KEY`.

## 4. Dashboard de monitoreo (figuras)

La superficie de monitoreo existente es el Centro de Operaciones de Streamlit (`app.py`): muestra por turno el modelo, la latencia en milisegundos y el número de fuentes, además de un panel de traza y un registro de decisión por fase. No existe una captura de un panel de monitoreo dedicado, por lo que esta sección describe la infraestructura disponible y propone su extensión; no se inventa una imagen.

La **Figura 1** muestra la arquitectura y el bloque de observabilidad (traza JSONL, LangSmith opcional, cinco pasos por plan). La **Figura 2** muestra la adaptación del acto 2 y, en su franja inferior, la secuencia de traza del plan.

**Figura 1.** Arquitectura del agente y orquestación LangGraph, con el bloque de observabilidad. Archivo: `docs/figuras/figura-1-arquitectura.png`.

**Figura 2.** Acto 2: ventana de viento invalidada, replanificación y secuencia de traza. Archivo: `docs/figuras/figura-2-acto2.png`.

Paneles propuestos, alimentados de la misma traza: (i) latencia de extremo a extremo y por fase, con mediana y p95; (ii) tasa de errores y de rechazos fuera de dominio; (iii) consistencia (hash de prioridad + número de fases); (iv) fragmentos y fuentes únicas por consulta; (v) última versión de plan publicada y su motivo de cambio.

## 5. Recomendaciones técnicas y escalabilidad

1. **Instrumentar sub-tramos (prioridad alta).** Añadir `latencia_ms` por span (carga de embeddings, RAG, herramientas, LLM) reutilizando `traceable` de `agent/observabilidad.py`. Justificación: el 96 % del tiempo observado está en un tramo no desagregado.
2. **Enriquecer el esquema de traza.** Registrar `error`, `tokens`, `modelo`, `n_fragmentos` y `n_herramientas` en cada evento, no solo en `respuesta_final`. Justificación: 0/14 errores no puede interpretarse sin un campo explícito de error, y la latencia actual es derivada.
3. **Reducir redundancia del RAG.** Deduplicar por fuente o aplicar un reranker antes de inyectar contexto. Justificación: 5 fragmentos → 2 fuentes únicas, con 3 fragmentos repetidos.
4. **Unificar la ruta de traza y el dashboard.** Corregir el nombre referenciado en la evidencia y concatenar los `ms` que ya calcula la UI en una serie temporal con alertas por umbral de latencia y por aparición de errores.
5. **Escalar con control.** Mantener el núcleo determinista y ampliar los casos (`data/casos/`), cachear el cliente Chroma por proceso (ya documentado como restricción) y crear un banco de evaluación del parte con rúbrica, hoy sin medir. Justificación: la consistencia observada (2/2) se sostiene porque la decisión no depende del LLM.

## 6. Seguridad y uso responsable

El repositorio declara explícitamente que se trata de una simulación académica con personas, protocolo y pronóstico ficticios, no apta para operaciones reales (`README.md`). El guardrail de `publicar_plan` valida estructura, franja ISO, zonas y medios antes de escribir, y el LLM recibe el plan ya publicado sin poder modificarlo. La puerta de dominio rechaza consultas ajenas al operativo sin consumir LLM ni crear archivos. Las trazas contienen identificadores de sesión y fuentes, sin credenciales; `logs/`, `chroma_db/` y `.env` permanecen fuera del control de versiones según las reglas del repo. El sistema propone un plan auditable, pero la decisión operativa sigue siendo humana.

## 7. Conclusión

Con la evidencia disponible, el agente muestra consistencia total en los dos planes documentados (misma prioridad, mismas 5 fases y misma secuencia de traza), cero errores registrados en 14 eventos y una adaptación correcta al evento de viento con la regla citada. La principal debilidad observacional es la latencia: 76 s de extremo a extremo, con el 96 % concentrado en un tramo sin instrumentar. Las mejoras propuestas —sub-spans, campos de error y tokens, deduplicación del RAG y un panel con series temporales— son de bajo costo porque reutilizan la traza y el código de observabilidad ya existentes. Para dar robustez estadística a estas cifras hace falta ampliar el número de corridas y evaluar la calidad del parte narrativo.

## Referencias (APA)

Chroma. (2026). *Chroma documentation*. https://docs.trychroma.com/

Groq. (2026). *Groq API documentation*. https://console.groq.com/docs

ISY0101. (2026). *Evaluación Parcial 2: Instrucciones* [Documento de curso]. Ingeniería de Soluciones con IA.

LangChain. (2026). *LangGraph documentation*. https://langchain-ai.github.io/langgraph/

Lewis, P., Perez, E., Piktus, A., Petroni, F., Karpukhin, V., Goyal, N., ... Riedel, S. (2020). Retrieval-augmented generation for knowledge-intensive NLP tasks. *Advances in Neural Information Processing Systems, 33*, 9459–9474. https://arxiv.org/abs/2005.11401

Reimers, N., & Gurevych, I. (2019). Sentence-BERT: Sentence embeddings using Siamese BERT-networks. *Proceedings of EMNLP-IJCNLP 2019*, 3982–3992. https://arxiv.org/abs/1908.10084

Russell, S., & Norvig, P. (2021). *Artificial intelligence: A modern approach* (4th ed.). Pearson.

Yao, S., Zhao, J., Yu, D., Du, N., Shafran, I., Narasimhan, K., & Cao, Y. (2023). ReAct: Synergizing reasoning and acting in language models. *International Conference on Learning Representations*. https://arxiv.org/abs/2210.03629
