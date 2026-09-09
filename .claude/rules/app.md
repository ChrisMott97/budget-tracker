---
paths:
  - "app/src/**/*.{ts,tsx}"
  - "app/vite.config.ts"
  - "app/package.json"
---

# App conventions (React 19, TypeScript, Vite, Tailwind 4)

- Function components and hooks only. Server state lives in hooks under `src/hooks/`, HTTP calls in `src/api/`, components stay presentational.
- Server state goes through TanStack Query (decided 2026-09-09): `useQuery` for reads, `useMutation` for writes. The `QueryClient` is created once in `main.tsx`. Do not hand-roll `useState` + `useEffect` fetching.
- Hooks expose async state as a discriminated union (`idle | loading | success | error`) as in `useCsvImport`, which renames TanStack's `pending` to `loading` and hides the raw mutation object. No boolean soup in components.
- Styling is Tailwind utility classes in JSX. No CSS modules, no styled-components, no inline style objects.
- `verbatimModuleSyntax` is on: use `import type` for types. Imports of local files include the extension as the existing code does.
- Forms are uncontrolled with `FormData` unless live validation is needed. Label every control. Buttons have visible text.
- Do not introduce a router or a client state library without asking. Those are still roadmap decisions; data fetching is settled on TanStack Query.
- Tests use vitest with `@testing-library/react`. Test behaviour through hooks and rendered output, not implementation details. Stub `fetch` with `vi.stubGlobal` and reset it after each test. Anything using TanStack Query is rendered with `createQueryWrapper()` from `src/test/queryClientWrapper.tsx`, and its state is read through `waitFor` because TanStack notifies subscribers a tick after a request settles.
- Before finishing: `npm run lint`, `npx tsc -b`, `npm test` all pass.
