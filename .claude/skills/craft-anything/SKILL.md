---
name: craft-anything
description: "Reverse-engineer and rebuild websites, e-commerce product pages, or landing pages using Craft Anything's clean-room engine. Studies visible layout at 1440px, 768px, and 390px, generates standalone responsive code, checks likeness (>=90%), and refines automatically. Use when asked to replicate a web page, clone an e-commerce layout, or build a clean-room alternative to an existing site."
---

# Craft Anything Clean-Room Web Rebuild Skill

Study any target website, e-commerce store, or landing page, and reconstruct a clean-room, high-converting standalone responsive web page.

## Workflow: Study -> Build -> Check -> Refine

1. **Study (`automation/craft_anything.py study <url>`)**:
   - Inspect target across three responsive screen widths:
     - 1440px (Desktop full grid/flex)
     - 768px (Tablet 2-column)
     - 390px (Mobile single-column sticky CTA)
   - Extract visual hierarchy: colors, typography, layout rhythm, spacing, heading structure.
   - Clean-Room Rule: Never copy copyrighted proprietary source code or private logos. Mirror layout, UX flow, and responsive behavior.

2. **Build (`automation/craft_anything.py rebuild <url> --prompt "..."`)**:
   - Generate modern, standalone, semantic HTML/CSS/JS.
   - Integrate with JARVIS LUNA e-commerce design system (Shopify/Netlify/GitHub Pages ready).

3. **Check (`check_likeness`)**:
   - Compare responsive layout and color palette coverage.
   - Score Likeness (%): Target must reach >= 90.0%.

4. **Refine**:
   - Iterate on gaps (mobile padding, button contrast, media query breakpoints) until likeness is achieved.

## Commands

```bash
# Automated Study -> Build -> Check -> Refine Pipeline
python automation/craft_anything.py rebuild https://target-site.com --prompt "쇼피파이 상세페이지 반응형 복제"

# Inspection only
python automation/craft_anything.py study https://target-site.com
```
