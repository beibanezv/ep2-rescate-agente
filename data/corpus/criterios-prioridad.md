# Criterios de priorización de zonas — Central de operaciones

Regla de trabajo del analista de operaciones para ordenar el barrido:

    prioridad = probabilidad de la zona × facilidad de barrido / tiempo de barrido

## Factores

- **Probabilidad**: la ruta declarada y sus variantes mandan; el último
  contacto reciente sube la probabilidad de la zona donde ocurrió; un equipo
  declarado incompatible con terreno técnico baja la probabilidad de las zonas
  técnicas.
- **Facilidad de barrido**: una zona cubierta por dron y con acceso vehicular
  se barre antes que una quebrada de acceso técnico.
- **Urgencia**: temperatura nocturna baja, horas transcurridas y pronóstico
  adverso suben la urgencia general, no la de una zona específica.

## Reglas de desempate

1. Primero la zona donde está el último contacto confirmado.
2. Luego las zonas de la ruta declarada, en orden de facilidad.
3. Las zonas no declaradas y técnicas quedan para la última fase, salvo
   evidencia nueva.

## Ejemplo de aplicación

- Zona en la ruta declarada, cubierta por dron y con acceso vehicular →
  primera prioridad.
- Quebrada técnica sin equipo declarado en la persona → última prioridad; solo
  Fase III.
