# Hotbar / Left Navigation Bar — OpenLens UI Specification

Este documento describe la barra lateral de OpenLens (hotbar) tal como se observa en la imagen de referencia. Puede usarse como prompt para recrear la UI en otra guía o implementación.

---

## 1. Ubicación y propósito

- **Posición**: barra vertical anclada al **lado izquierdo** de la ventana.
- **Función**: acceso rápido a clústers, vistas principales y herramientas favoritas (“pinned” clusters o workspaces).
- **Comportamiento esperado**:
  - Los ítems pueden ser **anclados/des-anclados**.
  - El ítem seleccionado se resalta con un borde blanco.
  - Algunos ítems muestran un **icono de engranaje** (`⚙`) indicando que son configurables o activos.

---

## 2. Estructura general (de arriba hacia abajo)

```xml
<Hotbar orientation="vertical" side="left" background="#1e2126" width="64px">
  <!-- Header: navegación y menú -->
  <Header height="40px">
    <IconButton icon="hamburger" tooltip="Main menu" />
    <IconButton icon="home" tooltip="Home" />
    <IconButton icon="back" tooltip="Back" />
    <IconButton icon="forward" tooltip="Forward" />
  </Header>

  <!-- Separador sutil -->
  <Separator />

  <!-- Ítems anclados (cada uno es un "chip" cuadrado) -->
  <PinnedItems>
    <HotbarItem icon="home"      color="#3b8ad4" badge="⚙" />
    <HotbarItem icon="grid"      color="#3b8ad4" badge="⚙" />
    <HotbarItem label="EIC"      color="#1a8a6a" badge="⚙" />
    <HotbarItem label="EI"       color="#c77a1f" badge="⚙" />
    <HotbarItem label="ACG"      color="#6a1b9a" selected="true" badge="⚙" />
    <HotbarItem label="AC"       color="#1e3a8a" badge="⚙" />
    <HotbarItem empty="true" />
    <HotbarItem empty="true" />
    <HotbarItem empty="true" />
    <HotbarItem empty="true" />
    <HotbarItem empty="true" />
    <HotbarItem empty="true" />
  </PinnedItems>

  <!-- Footer: indicador de página/posición -->
  <Footer height="24px">
    <PageIndicator current="1" />
  </Footer>
</Hotbar>
```

---

## 3. Detalles visuales de cada elemento

### 3.1 Header superior

| Elemento | Descripción |
|----------|-------------|
| **Hamburger menu** | Tres líneas horizontales, color blanco/gris, alineado a la izquierda. |
| **Home** | Icono de casita, alineado a la izquierda del header. |
| **Back / Forward** | Flechas `<` y `>` para navegación del historial. |

> Nota: el header es una zona de altura reducida, del mismo ancho que el resto de la hotbar.

### 3.2 HotbarItems (botones cuadrados anclados)

Cada ítem es un **cuadrado con esquinas redondeadas**, del mismo tamaño (~48×48 px), con margen uniforme entre ellos.

```xml
<HotbarItem
  id="1"
  shape="rounded-square"
  size="48x48"
  margin="8px"
  background="#3b8ad4"
  textColor="#ffffff"
  selected="false"
>
  <Icon src="home.svg" position="center" size="24px" />
  <Badge type="settings" icon="gear" position="bottom-right" size="12px" />
</HotbarItem>
```

#### Paleta observada

| Ítem | Fondo | Texto/Icono | Badge | Estado |
|------|-------|-------------|-------|--------|
| Inicio / Home | `#3b8ad4` (azul) | blanco | ⚙ | normal |
| Cuadrícula / Grid | `#3b8ad4` (azul) | blanco | ⚙ | normal |
| EIC | `#1a8a6a` (verde oscuro / teal) | blanco | ⚙ | normal |
| EI | `#c77a1f` (naranja / ámbar) | blanco | ⚙ | normal |
| ACG | `#6a1b9a` (púrpura) | blanco | ⚙ | **seleccionado** |
| AC | `#1e3a8a` (azul oscuro) | blanco | ⚙ | normal |

#### Estado `selected`

El ítem seleccionado (en la imagen: **ACG**) muestra:

- Un **borde blanco sólido de 2 px** alrededor del cuadrado.
- Ligera sombra o halo que lo separa del resto.

```css
.hotbar-item.selected {
  border: 2px solid #ffffff;
  box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.2);
}
```

#### Badge de configuración

- Pequeño icono de engranaje (`⚙`) ubicado en una esquina del cuadrado (inferior derecha o inferior izquierda, según el ítem).
- Indica que el clúster/ítem tiene opciones o está activo.

```xml
<Badge
  icon="gear"
  size="12px"
  position="bottom-right"
  color="#9ca3af"
/>
```

### 3.3 Ítems vacíos

- Los slots sin anclar se muestran como **cuadrados gris oscuro vacíos** (`#2a2d33`) con esquinas redondeadas.
- Sirven como placeholders para futuros clústers anclados.

```xml
<HotbarItem empty="true" background="#2a2d33" />
```

### 3.4 Footer

- Zona inferior de la hotbar.
- Muestra un pequeño indicador numérico `"1"` en la esquina inferior izquierda.
- Posible paginación: indica que estamos en la página 1 de N.

```xml
<Footer>
  <PageIndicator value="1" color="#6b7280" />
</Footer>
```

---

## 4. Especificación CSS de referencia

```css
.hotbar {
  width: 64px;
  height: 100vh;
  background-color: #1e2126;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 8px;
}

.hotbar-header {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 10px;
  padding: 0 8px 12px 8px;
  color: #e5e7eb;
}

.hotbar-items {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
  align-items: center;
}

.hotbar-item {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  font-size: 14px;
  font-weight: 600;
  position: relative;
  cursor: pointer;
  transition: transform 0.1s ease, box-shadow 0.1s ease;
}

.hotbar-item:hover {
  transform: scale(1.05);
}

.hotbar-item.selected {
  border: 2px solid #ffffff;
  box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.25);
}

.hotbar-item .badge {
  position: absolute;
  bottom: 2px;
  right: 2px;
  width: 12px;
  height: 12px;
  color: #d1d5db;
  font-size: 10px;
}

.hotbar-footer {
  height: 24px;
  width: 100%;
  display: flex;
  align-items: center;
  padding-left: 8px;
  color: #9ca3af;
  font-size: 11px;
}
```

---

## 5. Comportamientos deseados (para el prompt)

1. **Anclar clúster**: drag & drop de un clúster a un slot vacío → el slot se convierte en un `HotbarItem` con el color/label del clúster.
2. **Seleccionar clúster**: clic en un ítem → borde blanco + carga el contexto de ese clúster en la vista principal.
3. **Des-anclar**: context menu (clic derecho) con opción “Remove from Hotbar”.
4. **Configuración rápida**: clic en el badge `⚙` → menú contextual del clúster.
5. **Paginación**: si hay más ítems de los que caben, aparecen flechas de scroll o pestañas numéricas.

---

## 6. Resumen visual en una frase

> Barra vertical oscura a la izquierda con iconos de navegación arriba, una columna de chips cuadrados de colores que representan clústers anclados (algunos con engranaje), un ítem púrpura seleccionado con borde blanco, slots vacíos abajo y un indicador de página "1" al pie.
