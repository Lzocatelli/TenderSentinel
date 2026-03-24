# Design System Document: The Authoritative Editorial

## 1. Overview & Creative North Star

**Creative North Star: "The Informed Sentinel"**
This design system moves away from the generic "SaaS-in-a-box" aesthetic to create a high-stakes, editorial experience tailored for the US tender market. It rejects the clutter of traditional dashboards in favor of **Organic Brutalism**—a style that combines the structural rigidity of government procurement with the sophisticated, breathing room of high-end financial journalism.

We break the "template" look through:
*   **Intentional Asymmetry:** Using the 12-column grid as a suggestion rather than a cage, allowing white space to act as a functional element that directs the eye.
*   **High-Contrast Typography Scale:** Juxtaposing massive `display-lg` headlines with meticulous `label-sm` monospace data points to create a sense of scale and precision.
*   **Atmospheric Depth:** Replacing harsh lines with tonal layering to simulate the feeling of reviewing physical dossiers on a backlit, high-resolution light table.

---

## 2. Colors & Surface Logic

The palette is rooted in deep, authoritative blues and architectural slates, punctuated by a high-energy secondary orange (`#9f4200`) that signals urgency and action.

### The "No-Line" Rule
**Explicit Instruction:** Do not use 1px solid borders for sectioning or containment. Boundaries must be defined solely through background color shifts. 
*   *Example:* A feature block should be `surface-container-low` sitting on a `surface` background. The transition of color is the border.

### Surface Hierarchy & Nesting
Treat the UI as a series of stacked, semi-opaque sheets.
*   **Base:** `surface` (#f8f9ff)
*   **Level 1 (Subtle Inset):** `surface-container-low` (#eff4ff)
*   **Level 2 (Active Cards):** `surface-container` (#e5eeff)
*   **Level 3 (Prominent Highlights):** `surface-container-high` (#dce9ff)

### The Glass & Gradient Rule
To achieve "The Informed Sentinel" look, use glassmorphism for floating navigation and data overlays.
*   **Glass Specs:** Use `surface-container-lowest` (#ffffff) at 70% opacity with a `20px` backdrop-blur.
*   **Signature Textures:** Apply a subtle linear gradient from `primary` (#000000) to `primary-container` (#131b2e) on hero backgrounds to provide a "deep-space" depth that flat black cannot achieve.

---

## 3. Typography

The typographic system is a dialogue between the modern clarity of **Inter**, the utilitarian warmth of **Work Sans**, and the technical precision of **Space Grotesk**.

*   **Display & Headline (Inter):** Used for high-impact statements. The tight tracking and bold weights convey the "Trustworthy" and "Authoritative" pillar of the brand.
*   **Title & Body (Work Sans):** Chosen for its high legibility in dense data environments. It softens the "Brutalist" edges of the layout, making the platform feel approachable.
*   **Labels (Space Grotesk):** This is our "Data Signature." Use this for ID numbers, tender dates, and status chips to evoke a sense of high-tech monitoring and US market professionalism.

---

## 4. Elevation & Depth

### The Layering Principle
Depth is achieved through **Tonal Layering**. Instead of drop shadows, place a `surface-container-lowest` element on a `surface-container-low` section. This creates a soft, "natural lift" that feels premium and integrated.

### Ambient Shadows
If a floating element (like a modal or a floating action button) requires a shadow, use:
*   **Color:** A tinted version of `on-surface` (#0b1c30) at 6% opacity.
*   **Blur:** Minimum `32px` to mimic natural, diffuse light.

### The "Ghost Border" Fallback
If accessibility requires a visual container, use a "Ghost Border":
*   **Token:** `outline-variant` (#c6c6cd) at **15% opacity**. High-contrast, 100% opaque borders are strictly forbidden.

---

## 5. Components

### Buttons
*   **Primary:** Solid `primary` (#000000) or `secondary` (#9f4200) with `on-primary` text. No border. Use `radius-md` (0.375rem).
*   **Secondary:** `surface-container-high` background with `primary` text. This feels like a soft "pressed" state into the page.
*   **Tertiary:** Text-only in `primary`, using `label-md` (Space Grotesk) for a technical, "command-line" feel.

### Input Fields
*   **Styling:** Forgo the box. Use a `surface-container` background with a 2px bottom-accent of `outline-variant` at 20% opacity. 
*   **Focus State:** The bottom accent transitions to `secondary` (#9f4200).

### Cards & Lists
*   **No Dividers:** Forbid the use of horizontal lines between list items. Use vertical white space (`spacing-4`) or alternating tonal shifts (zebra striping using `surface` and `surface-container-low`).
*   **Contextual Chips:** Use `secondary-container` (#fc7218) for "High Priority" tenders and `tertiary-container` (#001e2f) with `on-tertiary-container` (#008cc7) for "Monitoring" states.

### The "Pulse" Indicator (App-Specific)
A custom component for tender monitoring: A small dot using `secondary` (#9f4200) with a CSS ripple animation to indicate live data feeds, placed next to `label-sm` typography.

---

## 6. Do's and Don'ts

### Do
*   **Do** use asymmetrical margins (e.g., 20% left margin, 5% right margin) for editorial-style content blocks.
*   **Do** use the `0.5` spacing (0.125rem) for micro-adjustments in data tables to keep them dense but readable.
*   **Do** embrace "Surface Bleed"—allowing background colors to extend to the edge of the viewport to create distinct content "zones."

### Don't
*   **Don't** use pure `#000000` for body text; use `on-surface` (#0b1c30) to maintain a soft, premium legibility.
*   **Don't** use "Card-in-Card" layouts with shadows; use nested tonal shifts (Container High inside Container Low).
*   **Don't** use standard icon sets; use thin-stroke (1px or 1.5px) icons that match the `outline` weight.