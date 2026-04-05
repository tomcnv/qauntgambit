## DeepTrader Dashboard

### High-Level Architecture
- **App shell** uses React Router for landing, auth, and operator workbench routes.
- **State** handled via Zustand stores + React Query for async resources (hooks already stubbed for backend integration).
- **Design system** is Tailwind + shadcn-inspired primitives (`Button`, `Card`, `Badge`, etc.) with CSS variable-driven tokens.
- **Theming** is runtime switchable via `ThemeProvider`, storing preference in `localStorage`.

### Upgrade Hooks / Extension Points
1. **Navigation registry** – `pages/dashboard/layout.jsx` consumes `NAV_ITEMS`. Add new modules by appending to this array; sidebar + routing highlight automatically.
2. **Data clients** – drop API adapters under `src/lib/api/` and hydrate React Query hooks within each page without touching layout code.
3. **Config Studio** – version cards are driven by `versions` array today; replace with API data but keep the same schema to benefit from built-in diff/promote controls.
4. **Signal Lab** – metrics arrays intentionally simple so they can be swapped with backend-provided TTL caches.
5. **Landing page** – hero callouts live inside `productHighlights` constant; marketing team can update copy without altering layout.
6. **Theme tokens** – update CSS variables in `tailwind.config.js` to match brand refreshes without sweeping markup.

### Next Steps
- Wire auth pages to backend tokens (current mock uses local store).
- Introduce websocket client for live telemetry and plug into overview charts.
- Build granular forms for config drafts (leveraging `react-hook-form` + dynamic JSON schema).
- Implement `CommandPalette` and `Notification Drawer` as overlay primitives.

### API & Data Flow
- REST base url is controlled via `VITE_API_BASE_URL` (defaults to `http://localhost:3001/api`).
- Typed contracts live in `src/lib/api/types.ts`; Axios client + React Query hooks in `src/lib/api/*`.
- Data currently pulls from `/api/monitoring/dashboard`, `/api/monitoring/fast-scalper`, `/api/monitoring/fast-scalper/rejections`, and `/api/monitoring/alerts`.
- Overview/Trading/Signal/Intelligence pages hydrate directly from those live services, so the UI always reflects the real bot/infra state.
